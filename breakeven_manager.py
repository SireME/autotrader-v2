"""
Breakeven & Trailing Stop Manager v4 — Inference-Based
========================================================
Each order is treated as fully independent.

Stage is INFERRED from current SL position relative to entry and TP —
no external state, no comment updates, no database needed.

Comment written at order creation (read-only after that):
    TelegramBot_TP1|E:5031.00|SL:5028.00|TP:5036.00

Fields used:
    E  = original entry price (fixed reference)
    SL = original stop loss   (fixed reference, not updated)
    TP = this order's target  (fixed reference)

Stage inference logic (per order, every scan):
    Stage 0 — Watching:
        pos.sl is still near original SL (below entry for BUY)
        → wait for price to reach TP

    Stage 1 — Breakeven:
        pos.sl has moved to approximately entry level
        → wait and enter trailing

    Stage 2 — Trailing:
        pos.sl is above entry (BUY) / below entry (SELL)
        price has gone beyond TP
        → trail SL behind price

Trailing peak is held in-memory (resets to current price on restart —
acceptable since SL is already locked in and "never worsen" guard applies).

Usage in main.py:
    from breakeven_manager import BreakevenManager
    asyncio.create_task(BreakevenManager().run())
"""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Dict, Optional

import MetaTrader5 as mt5

# ── Config ────────────────────────────────────────────────────────
CHECK_INTERVAL_SECONDS = 1

# Trail distance after TP is hit
TRAIL_PTS      = 3.0    # pts behind current price
TRAIL_STEP_PTS = 1.0    # min advance before moving SL (avoids tick noise)

# Buffer above entry for breakeven SL (avoids broker rejection at exact entry)
BE_BUFFER_PTS  = 0.5

# Tolerance for "SL is at entry" check — accounts for the BE buffer
BE_TOLERANCE_PTS = 2.0


# ─────────────────────────────────────────
# Comment parsing (read-only, creation only)
# ─────────────────────────────────────────

@dataclass
class OrderMeta:
    entry:  float   # original execution price
    sl_ref: float   # original SL (reference only)
    tp:     float   # this order's TP target

COMMENT_RE = re.compile(r'E:(\d+)\|SL:(\d+)\|TP:(\d+)')

def parse_comment(comment: str) -> Optional[OrderMeta]:
    """Extract fixed reference data from order comment. Returns None if not a bot order."""
    if not comment.startswith("B_TP"):
        return None
    m = COMMENT_RE.search(comment)
    if not m:
        return None
    return OrderMeta(
        entry  = float(m.group(1)),
        sl_ref = float(m.group(2)),
        tp     = float(m.group(3)),
    )


# ─────────────────────────────────────────
# In-memory trailing state (per ticket)
# ─────────────────────────────────────────

@dataclass
class TrailState:
    trail_peak: float = 0.0     # best price seen so far during trailing


# ─────────────────────────────────────────
# Stage inference
# ─────────────────────────────────────────

def infer_stage(pos, meta: OrderMeta, is_buy: bool) -> int:
    """
    Derive current stage purely from where pos.sl sits
    relative to the fixed entry and TP reference points.

    Stage 0 — SL is below entry (BUY) / above entry (SELL)
               i.e. still at or near the original risk level
    Stage 1 — SL is approximately at entry (within BE_TOLERANCE)
    Stage 2 — SL is above entry (BUY) / below entry (SELL)
               i.e. already locked in profit, in trailing territory
    """
    sl    = pos.sl
    entry = meta.entry

    if sl == 0.0:
        return 0    # no SL set yet — treat as watching

    if is_buy:
        if sl >= entry + BE_TOLERANCE_PTS:
            return 2    # SL above entry — trailing
        if sl >= entry - BE_TOLERANCE_PTS:
            return 1    # SL near entry — breakeven
        return 0        # SL below entry — watching
    else:
        if sl <= entry - BE_TOLERANCE_PTS:
            return 2    # SL below entry — trailing
        if sl <= entry + BE_TOLERANCE_PTS:
            return 1    # SL near entry — breakeven
        return 0        # SL above entry — watching


# ─────────────────────────────────────────
# Manager
# ─────────────────────────────────────────

class BreakevenManager:

    def __init__(self, check_interval: float = CHECK_INTERVAL_SECONDS):
        self.check_interval = check_interval
        self._running       = False
        # ticket → TrailState (in-memory trailing peak only)
        self._trail: Dict[int, TrailState] = {}

    async def run(self):
        self._running = True
        print(
            f"🔒 SL Manager started | "
            f"interval={self.check_interval}s | "
            f"trail={TRAIL_PTS}pts | "
            f"step={TRAIL_STEP_PTS}pt | "
            f"BE buffer={BE_BUFFER_PTS}pt"
        )
        while self._running:
            try:
                self._scan()
            except Exception as e:
                print(f"⚠️  SL Manager error: {e}")
            await asyncio.sleep(self.check_interval)

    def stop(self):
        self._running = False

    # ─────────────────────────────────────────
    # Scan
    # ─────────────────────────────────────────

    def _scan(self):
        positions = mt5.positions_get()
        if not positions:
            return

        active_tickets = set()

        for pos in positions:
            meta = parse_comment(pos.comment)
            if meta is None:
                continue    # not a bot order or pre-v4 comment

            active_tickets.add(pos.ticket)

            tick = mt5.symbol_info_tick(pos.symbol)
            info = mt5.symbol_info(pos.symbol)
            if not tick or not info:
                continue

            is_buy = (pos.type == mt5.ORDER_TYPE_BUY)
            price  = tick.bid if is_buy else tick.ask
            digits = info.digits
            pt     = info.point

            # Infer stage from current SL position
            stage = infer_stage(pos, meta, is_buy)

            if stage == 0:
                self._handle_watching(pos, meta, price, is_buy, digits, pt, tick)
            elif stage == 1:
                self._handle_breakeven(pos, meta, price, is_buy, digits, pt, tick)
            elif stage == 2:
                self._handle_trailing(pos, meta, price, is_buy, digits, pt, tick)

        # Clean up trail state for closed positions
        for t in set(self._trail) - active_tickets:
            del self._trail[t]

    # ─────────────────────────────────────────
    # Stage 0: Watching — wait for TP hit
    # ─────────────────────────────────────────

    def _handle_watching(self, pos, meta: OrderMeta, price: float,
                         is_buy: bool, digits: int, pt: float, tick):
        if not self._hit(is_buy, price, meta.tp):
            return

        buf    = BE_BUFFER_PTS * pt * 100
        new_sl = round(meta.entry + (buf if is_buy else -buf), digits)

        if self._modify(pos, new_sl, tick, pt, digits, is_buy):
            direction = "BUY" if is_buy else "SELL"
            print(
                f"\n{'─'*45}\n"
                f"🔒 BREAKEVEN SET\n"
                f"   Ticket : {pos.ticket}  {pos.symbol} {direction}\n"
                f"   TP hit : {meta.tp:.{digits}f}  (price @ {price:.{digits}f})\n"
                f"   SL     : {pos.sl:.{digits}f} → {new_sl:.{digits}f}  (entry, zero risk)\n"
                f"{'─'*45}"
            )

    # ─────────────────────────────────────────
    # Stage 1: Breakeven — transition to trail
    # ─────────────────────────────────────────

    def _handle_breakeven(self, pos, meta: OrderMeta, price: float,
                          is_buy: bool, digits: int, pt: float, tick):
        """
        SL is at entry — start trailing immediately.
        Initialise trail_peak at current price so first trail
        step is meaningful.
        """
        if pos.ticket not in self._trail:
            self._trail[pos.ticket] = TrailState(trail_peak=price)
            print(f"🏃 TRAILING STARTED  ticket={pos.ticket} | peak={price:.{digits}f} | trail={TRAIL_PTS}pts behind price")
        # Fall through to trailing logic immediately
        self._handle_trailing(pos, meta, price, is_buy, digits, pt, tick)

    # ─────────────────────────────────────────
    # Stage 2: Trailing
    # ─────────────────────────────────────────

    def _handle_trailing(self, pos, meta: OrderMeta, price: float,
                         is_buy: bool, digits: int, pt: float, tick):
        """Trail SL behind price by TRAIL_PTS, stepping by TRAIL_STEP_PTS."""

        # Initialise trail state if not present (e.g. after bot restart)
        if pos.ticket not in self._trail:
            self._trail[pos.ticket] = TrailState(trail_peak=price)
            print(f"🔄 TRAIL RESUMED     ticket={pos.ticket} | peak reset @ {price:.{digits}f} (bot restarted)")

        state = self._trail[pos.ticket]

        if is_buy:
            # Update peak
            if price > state.trail_peak:
                state.trail_peak = price

            desired_sl = round(state.trail_peak - TRAIL_PTS, digits)
            advance    = desired_sl - pos.sl

            if desired_sl > pos.sl and advance >= TRAIL_STEP_PTS * pt * 100:
                if self._modify(pos, desired_sl, tick, pt, digits, is_buy):
                    print(f"📈 TRAIL ↑           ticket={pos.ticket} | price={price:.{digits}f}  peak={state.trail_peak:.{digits}f} | SL {pos.sl:.{digits}f} → {desired_sl:.{digits}f}")
        else:
            if state.trail_peak == 0.0 or price < state.trail_peak:
                state.trail_peak = price

            desired_sl = round(state.trail_peak + TRAIL_PTS, digits)
            cur_sl     = pos.sl
            advance    = cur_sl - desired_sl if cur_sl > 0 else float('inf')

            if (cur_sl == 0.0 or desired_sl < cur_sl) and \
               advance >= TRAIL_STEP_PTS * pt * 100:
                if self._modify(pos, desired_sl, tick, pt, digits, is_buy):
                    print(f"📉 TRAIL ↓           ticket={pos.ticket} | price={price:.{digits}f}  peak={state.trail_peak:.{digits}f} | SL {pos.sl:.{digits}f} → {desired_sl:.{digits}f}")

    # ─────────────────────────────────────────
    # MT5 modification
    # ─────────────────────────────────────────

    @staticmethod
    def _modify(pos, new_sl: float, tick, pt: float,
                digits: int, is_buy: bool) -> bool:
        """Send SL modification to MT5. Returns True on success."""
        # Safety clamp — SL must not cross current price
        if is_buy  and new_sl >= tick.bid:
            new_sl = round(tick.bid - pt, digits)
        if not is_buy and new_sl <= tick.ask:
            new_sl = round(tick.ask + pt, digits)

        # Never worsen existing SL
        if is_buy  and pos.sl > 0 and new_sl <= pos.sl:
            return False
        if not is_buy and pos.sl > 0 and new_sl >= pos.sl:
            return False

        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_SLTP,
            "ticket": pos.ticket,
            "sl":     new_sl,
            "tp":     pos.tp,
        })

        if result is None:
            print(f"⚠️  SL modify failed  ticket={pos.ticket}: order_send()=None — {mt5.last_error()}")
            return False

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"⚠️  SL modify rejected ticket={pos.ticket}: retcode={result.retcode} {result.comment}")
            return False

        return True

    @staticmethod
    def _hit(is_buy: bool, price: float, target: float) -> bool:
        return price >= target if is_buy else price <= target