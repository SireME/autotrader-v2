import math
import MetaTrader5 as mt5
from broker.broker_interface import BrokerInterface

from config.symbols import get_broker_symbol, SYMBOL_ALIASES


# If the signal's SL or TP is more than this % from live price, it's stale/hallucinated.
MAX_PRICE_DEVIATION = 0.05   # 5%
MAX_LOT_SIZE = 0.02           # Maximum allowed lot size
LOT_SIZE = 0.02               # If set, this lot size will be enforced

# If signal entry is more than this % from live price AND fallback SL/TP were used,
# the signal is almost certainly hallucinated — block it entirely.
MAX_ENTRY_DEVIATION_FOR_FALLBACK = 0.10  # 10%


class MT5Broker(BrokerInterface):
    _connected = False

    def connect(self):
        if self._connected:
            return True
        if not mt5.initialize():
            raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
        self._connected = True
        print("✅ MT5 connected (broker)")
        return True

    def get_open_positions_count(self) -> int:
        if not self._connected:
            self.connect()
        positions = mt5.positions_get()
        if positions is None:
            return 0
        return len(positions)

    def get_today_pnl(self) -> float:
        if not self._connected:
            self.connect()
        from datetime import datetime
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        deals = mt5.history_deals_get(today, datetime.now())
        if deals is None or len(deals) == 0:
            return 0.0
        return sum(deal.profit for deal in deals)

    # ── helpers ───────────────────────────────────────────────
    @staticmethod
    def get_symbol_info(symbol: str):
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol_info() returned None for {symbol}")
        return info

    @staticmethod
    def get_pip_size(symbol_info) -> float:
        return symbol_info.point * 10 if symbol_info.digits >= 5 else symbol_info.point

    @staticmethod
    def round_lot(volume: float, lot_step: float) -> float:
        return round(math.floor(volume / lot_step) * lot_step, 2)

    # ── SL / TP validation & repair ───────────────────────────
    @staticmethod
    def _validate_and_fix_sl_tp(live_price: float, signal_entry: float,
                                  sl: float, tp: float,
                                  is_buy: bool, pip_size: float) -> tuple:
        """
        Validate SL/TP using TWO separate checks:

          1. Directional check  → uses SIGNAL ENTRY (not live price)
             BUY:  sl < signal_entry  and  tp > signal_entry
             SELL: sl > signal_entry  and  tp < signal_entry

          2. Staleness check   → uses LIVE PRICE
             Both SL and TP must be within MAX_PRICE_DEVIATION of live price.

        If either check fails we recompute, anchoring pip distances to live price.
        This means a valid signal whose market has moved slightly still uses its
        original SL/TP, rather than being silently replaced.
        """
        max_dist = live_price * MAX_PRICE_DEVIATION

        def levels_ok() -> bool:
            # Staleness: SL and TP must be close enough to the live price
            if abs(sl - live_price) > max_dist or abs(tp - live_price) > max_dist:
                return False
            # Directional: check against signal's intended entry, not live price
            if is_buy and not (sl < signal_entry and tp > signal_entry):
                return False
            if not is_buy and not (sl > signal_entry and tp < signal_entry):
                return False
            return True

        if levels_ok():
            print(f"✅ SL/TP from signal are valid: sl={sl}, tp={tp}")
            return sl, tp

        # ── Recompute anchored to live price, preserving pip distances ────────
        sl_pips = abs(sl - signal_entry) / pip_size if sl != 0 else 30
        tp_pips = abs(tp - signal_entry) / pip_size if tp != 0 else 60

        max_pips = max_dist / pip_size
        sl_pips = min(sl_pips, max_pips)
        tp_pips = min(tp_pips, max_pips)

        if is_buy:
            new_sl = round(live_price - sl_pips * pip_size, 5)
            new_tp = round(live_price + tp_pips * pip_size, 5)
        else:
            new_sl = round(live_price + sl_pips * pip_size, 5)
            new_tp = round(live_price - tp_pips * pip_size, 5)

        print(
            f"⚠️  Signal SL/TP were invalid (sl={sl}, tp={tp}) — "
            f"recomputed to sl={new_sl}, tp={new_tp} "
            f"({sl_pips:.1f} / {tp_pips:.1f} pips from live price {live_price})"
        )
        return new_sl, new_tp

    # ── main ──────────────────────────────────────────────────
    def place_trade(self, trade):
        signal_symbol = trade["symbol"]

        # Map signal symbol to broker's actual symbol name
        symbol = get_broker_symbol(signal_symbol)

        if symbol != signal_symbol:
            print(f"🔄 Symbol mapped: '{signal_symbol}' → '{symbol}'")

        print(f"DEBUG → signal_symbol: {signal_symbol}")
        print(f"DEBUG → mapped_symbol: {symbol}")

        if not mt5.symbol_select(symbol, True):
            available = mt5.symbols_get()
            if available:
                similar = [s.name for s in available if signal_symbol[:3] in s.name.upper()]
                error_msg = f"Symbol not available: {symbol} (mapped from {signal_symbol})"
                if similar:
                    error_msg += f"\n💡 Similar symbols found: {', '.join(similar[:5])}"
                    error_msg += f"\n   Update config/symbols.py to map '{signal_symbol}' to the correct symbol"
                else:
                    error_msg += f"\n💡 Run find_xm_symbols.py to see all available symbols"
                raise RuntimeError(error_msg)
            raise RuntimeError(f"Symbol not available: {symbol} (mapped from {signal_symbol})")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"No tick data for {symbol}")

        info     = self.get_symbol_info(symbol)
        pip_size = self.get_pip_size(info)

        # ── direction & live price ──────────────────────────
        is_buy       = trade["direction"].lower() == "buy"
        live_price   = tick.ask if is_buy else tick.bid
        signal_entry = trade.get("entry", live_price)
        tick_size    = info.trade_tick_size if info.trade_tick_size > 0 else info.point

        # Broker minimum stop distance floor.
        # Many brokers report stops_level=0 but silently enforce a larger minimum.
        # Use conservative floors based on instrument type:
        #   Gold (2-decimal):  15 points minimum  (broker often enforces 10–15)
        #   Forex (5-decimal):  5 points minimum
        reported_min  = info.trade_stops_level * info.point
        symbol_floor  = 15 * info.point if info.digits <= 2 else 5 * info.point
        min_stop_dist = max(reported_min, symbol_floor)

        print(f"DEBUG → stops_level={info.trade_stops_level}, point={info.point}, "
              f"digits={info.digits}, tick_size={tick_size:.4f}, "
              f"reported_min={reported_min:.4f}, effective_min={min_stop_dist:.4f}")

        # ── Entry range & order type decision ───────────────
        # Provider gives ranges like "5010 - 5007" (BUY) or "5017 – 5020" (SELL).
        # AI extracts: entry = better bound (lower for BUY, higher for SELL)
        #              entry_range_width = abs(high - low)
        #
        # We reconstruct the full range here regardless of which bound the AI gave:
        #   BUY:  range = [entry .. entry + range_width]  (entry is the LOW bound)
        #   SELL: range = [entry - range_width .. entry]  (entry is the HIGH bound)
        #
        # Decision:
        #   live in range → execute at market now
        #   live outside range → skip (too early or too late)

        entry_range_width = trade.get("metadata", {}).get("entry_range_width", 1.0)
        if entry_range_width == 0.0:
            entry_range_width = 1.0   # treat single-price entry as ±1pt zone

        has_explicit_entry = (
            trade.get("order_type") == "limit"
            and not trade.get("metadata", {}).get("used_market_price", False)
        )

        if has_explicit_entry:
            if is_buy:
                # BUY: entry is the LOWER bound, range extends UP by range_width
                range_low  = signal_entry
                range_high = signal_entry + entry_range_width
                if live_price < range_low - 1.0:
                    raise RuntimeError(
                        f"⏭️  BUY skipped — live price {live_price} is "
                        f"{range_low - live_price:.1f}pts below entry range "
                        f"({range_low}–{range_high:.1f}). Zone not yet reached."
                    )
                if live_price > range_high + 1.0:
                    raise RuntimeError(
                        f"⏭️  BUY skipped — live price {live_price} is above entry range "
                        f"({range_low}–{range_high:.1f}). Entry zone already passed."
                    )
                print(f"✅ Live price {live_price} within BUY range "
                      f"({range_low}–{range_high:.1f}) — executing at market")
            else:
                # SELL: entry should be the UPPER bound, range extends DOWN.
                # AI sometimes returns the lower number — correct it here.
                range_high = signal_entry + entry_range_width   # upper bound
                range_low  = signal_entry                        # lower bound
                if live_price > range_high + 1.0:
                    raise RuntimeError(
                        f"⏭️  SELL skipped — live price {live_price} is "
                        f"{live_price - range_high:.1f}pts above entry range "
                        f"({range_low:.1f}–{range_high:.1f}). Zone not yet reached."
                    )
                if live_price < range_low - 1.0:
                    raise RuntimeError(
                        f"⏭️  SELL skipped — live price {live_price} is below entry range "
                        f"({range_low:.1f}–{range_high:.1f}). Entry zone already passed."
                    )
                print(f"✅ Live price {live_price} within SELL range "
                      f"({range_low:.1f}–{range_high:.1f}) — executing at market")

        # Always execute at market — no pending orders
        order_type  = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
        action      = mt5.TRADE_ACTION_DEAL
        order_price = live_price
        print(f"📍 Market execution at {order_price}")

        # ── FIX 4: Block hallucinated signals ────────────────
        used_fallback = trade.get("metadata", {}).get("used_fallback_sl", False)
        is_market_cmd = trade.get("metadata", {}).get("used_market_price", False)

        # Block signals where AI hallucinated an entry from commentary text.
        # These will have used_fallback_sl=True but NOT be explicit market commands.
        # Real signals either: (a) have explicit SL/TP, or (b) are "buy/sell now" market cmds.
        if used_fallback and not is_market_cmd:
            raise RuntimeError(
                f"❌ Blocked likely hallucinated signal — fallback SL/TP used on "
                f"non-market-command message: '{trade.get('raw', '')[:60]}'"
            )

        # ── build TP list ────────────────────────────────────
        all_tps = trade.get("take_profit", [])
        if not all_tps:
            all_tps = [0.0]

        # ── filter TPs that are still valid at execution price ──
        # When live price is above signal entry (common for ranged signals),
        # early TPs may already be below the ask — MT5 rejects these.
        # Skip invalid TPs and use only those still ahead of live price.
        valid_tps = []
        min_tp_dist = min_stop_dist  # same minimum distance as SL
        for tp_candidate in all_tps:
            if tp_candidate == 0.0:
                valid_tps.append(tp_candidate)
                continue
            if is_buy and tp_candidate > live_price + min_tp_dist:
                valid_tps.append(tp_candidate)
            elif not is_buy and tp_candidate < live_price - min_tp_dist:
                valid_tps.append(tp_candidate)
            else:
                print(f"⏭️  Skipping TP {tp_candidate} — already {'below' if is_buy else 'above'} "
                      f"execution price {live_price} (min dist={min_tp_dist:.2f}pts)")

        if not valid_tps:
            raise RuntimeError(
                f"❌ No valid TPs remain after filtering against live price {live_price}. "
                f"All TPs already passed. Signal entry zone too far from current market."
            )
        all_tps = valid_tps
        print(f"✅ Valid TPs after filtering: {all_tps}")

        # ── determine filling mode ────────────────────────
        # All orders are now market orders — no more pending limits.
        filling_type = info.filling_mode
        if filling_type & 1:
            filling_mode = mt5.ORDER_FILLING_FOK
        elif filling_type & 2:
            filling_mode = mt5.ORDER_FILLING_IOC
        elif filling_type & 4:
            filling_mode = mt5.ORDER_FILLING_RETURN
        else:
            filling_mode = mt5.ORDER_FILLING_FOK
        print(f"🔧 Using filling mode: {filling_mode}")

        # ── calculate per-order volume ────────────────────
        # Split total lot evenly across all TP levels to mirror provider's
        # multi-TP structure (TP1, TP2, TP3 + optional runner).
        num_orders = len(all_tps)
        base_volume = LOT_SIZE if LOT_SIZE is not None else trade.get("lot_size", 0.01)
        base_volume = min(base_volume, MAX_LOT_SIZE)

        split_volume = self.round_lot(base_volume / num_orders, info.volume_step)

        if split_volume < info.volume_min:
            # Split too small for broker — collapse to single order at TP1
            print(f"⚠️  Split volume {split_volume} < broker min {info.volume_min} "
                  f"— collapsing to single order")
            split_volume = self.round_lot(base_volume, info.volume_step)
            num_orders = 1
            all_tps = all_tps[:1]

        split_volume = min(split_volume, info.volume_max)

        print(f"🔒 Placing {num_orders} order(s) × {split_volume} lots "
              f"(total exposure: {round(split_volume * num_orders, 2)}) "
              f"across {num_orders} TP level(s): {all_tps}")

        # ── validate SL once (same for all orders) ────────
        # Validate direction against signal_entry, staleness against live_price
        sl_validated, _ = self._validate_and_fix_sl_tp(
            live_price, signal_entry, trade["stop_loss"],
            all_tps[0], is_buy, pip_size
        )

        # Enforce minimum stop distance from order price.
        # Compare DISTANCE (always positive) not absolute SL value.
        sl_distance = abs(order_price - sl_validated)
        if sl_distance < min_stop_dist * 1.2:
            if is_buy:
                sl_validated = round(order_price - min_stop_dist * 1.2, info.digits)
            else:
                sl_validated = round(order_price + min_stop_dist * 1.2, info.digits)
            print(f"⚠️  SL too close ({sl_distance:.2f}pts < min {min_stop_dist*1.2:.2f}pts) "
                  f"— adjusted to {sl_validated}")

        print(f"✅ Final SL: {sl_validated} "
              f"({abs(order_price - sl_validated):.2f} pts from order price)")

        # ── place one order per TP level ──────────────────
        tickets = []
        for i, raw_tp in enumerate(all_tps):
            tp_label = f"TP{i+1}"

            # Always use order_price (live price) as TP reference — all orders are market now
            _, tp_validated = self._validate_and_fix_sl_tp(
                order_price, signal_entry, trade["stop_loss"],
                raw_tp, is_buy, pip_size
            )

            request = {
                "action":       action,
                "symbol":       symbol,
                "volume":       split_volume,
                "type":         order_type,
                "price":        order_price,
                "sl":           sl_validated,
                "tp":           tp_validated,
                "deviation":    20,
                "magic":        10001,
                "comment":      f"TelegramBot_{tp_label}|E:{order_price:.2f}|SL:{sl_validated:.2f}|TP:{tp_validated:.2f}|STAGE:0",
                "type_filling": filling_mode,
                "type_time":    mt5.ORDER_TIME_GTC,
            }

            print(f"📊 Order validation: price={order_price}, sl={sl_validated}, "
                  f"sl_dist={abs(order_price-sl_validated):.2f}pts, "
                  f"tp={tp_validated}, tp_dist={abs(order_price-tp_validated):.2f}pts, "
                  f"min_required={min_stop_dist:.4f}")
            print(f"📤 Sending {tp_label} (market) order: "
                  f"price={order_price}, sl={sl_validated}, tp={tp_validated}, vol={split_volume}")
            result = mt5.order_send(request)

            if result is None:
                print(f"⚠️  {tp_label} failed: order_send() returned None — "
                      f"last_error={mt5.last_error()}")
                continue
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"⚠️  {tp_label} failed: retcode={result.retcode}, "
                      f"comment={result.comment}")
                continue

            print(f"✅ {tp_label} executed: ticket={result.order}")
            tickets.append(result.order)

        if not tickets:
            raise RuntimeError("All orders failed — no tickets returned")

        # Return first ticket as int (for DB logging), full list in metadata
        print(f"✅ All tickets: {tickets}")
        return tickets[0]