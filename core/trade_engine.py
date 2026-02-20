from config.settings import MIN_CONFIDENCE
from config.symbols import get_broker_symbol


class TradeEngine:
    def __init__(self, broker, risk_manager, trade_repository=None):
        self.broker = broker
        self.risk_manager = risk_manager
        self.trade_repository = trade_repository

    def process_signal(self, signal):
        if not signal or signal.get("entry") is None:
            return

        confidence = signal.get("confidence", 0.0)
        if confidence < MIN_CONFIDENCE:
            print(f"⏭️ Signal skipped — confidence {confidence} < minimum {MIN_CONFIDENCE}")
            return

        # ─── SYMBOL MAPPING (CRITICAL FIX) ────────────────────
        raw_symbol = signal["symbol"]
        broker_symbol = get_broker_symbol(raw_symbol)

        if broker_symbol != raw_symbol:
            print(f"🔄 Symbol mapped: '{raw_symbol}' → '{broker_symbol}'")

        # Overwrite signal symbol so entire system uses broker symbol
        signal["symbol"] = broker_symbol

        # ─── RISK CHECKS ───────────────────────────────────────
        if not self.risk_manager.can_open_new_trade(
            self.broker.get_open_positions_count()
        ):
            print("⏭️ Signal skipped — max open trades reached")
            return

        today_pnl = self.broker.get_today_pnl()
        if self.risk_manager.daily_loss_breached(today_pnl):
            print("⏭️ Signal skipped — daily loss limit reached")
            return

        # ─── SYMBOL INFO ───────────────────────────────────────
        info = self.broker.get_symbol_info(broker_symbol)
        pip_size = self.broker.get_pip_size(info)

        sl_pips = abs(signal["entry"] - signal["stop_loss"]) / pip_size

        if sl_pips == 0:
            print("⚠️ SL == entry, cannot calculate lot size — skipping")
            return

        signal["lot_size"] = self.risk_manager.calculate_lot_size(sl_pips, 1)

        # ─── EXECUTE TRADE ─────────────────────────────────────
        ticket = self.broker.place_trade(signal)

        if self.trade_repository is not None:
            self.trade_repository.insert_trade(signal, ticket)

