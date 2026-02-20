"""
Breakeven & Trailing Stop Manager v5 — Inference-Based
========================================================
Each order is treated as fully independent.

Stage is INFERRED from current SL position relative to entry and TP —
no external state, no comment updates, no database needed.

Comment written at order creation (read-only after that):
    B_TP1|E:5031.00|SL:5028.00|TP:5036.00

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

─────────────────────────────────────────────────────────────────
UNIT CONVENTION — READ THIS FIRST
─────────────────────────────────────────────────────────────────
All distance constants are expressed in PRICE UNITS (i.e. the same
unit as bid/ask prices).  They are NOT in "points" or "pips".

  Gold  (digits=2, point=0.01): 1 price unit = $1.00
  Forex (digits=5, point=0.00001): 1 price unit = 1.00000

Helper: pts_to_price(n, info) converts a constant to price units
using the instrument's point size, so you can still think in
"points" when setting the constants:

    TRAIL_PTS = 300         # 300 points (= $3.00 on Gold)
    pts_to_price(300, gold_info)  → 300 * 0.01 = 3.00  ✓

Sniper strategy calibration (Gold, point=0.01):
    TRAIL_PTS       = 300   → $3.00 trail  (≈ 1× typical SL)
    TRAIL_STEP_PTS  = 100   → $1.00 step   (one clean price increment)
    BE_BUFFER_PTS   = 100   → $1.00 above entry
    BE_TOLERANCE    = 200   → ±$2.00 around entry for stage inference

─────────────────────────────────────────────────────────────────

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

# ── Config — all distances are in POINTS (converted to price units at runtime) ──
#
# Calibrated for a SNIPER strategy on Gold (XAUUSD, point=0.01):
#
#   Typical signal structure:
#     Entry range : 3–5 pts wide   (e.g. 5022–5025)
#     SL          : 3–4 pts from entry
#     TP1         : 5–6 pts from entry
#     TP2–TP4     : 7–12 pts from entry
#
#   These constants are sized relative to that structure.
#   In Gold price terms: 1 pt = $0.01

CHECK_INTERVAL_SECONDS = 1

# How many points behind the current price to place the trailing SL.
# Set to 3pts = 1× the typical SL distance, giving the trade room to breathe
# without giving back more than one full risk unit.
TRAIL_PTS = 300          # 3 pts on Gold ($0.03) — 1× SL distance

# Minimum advance (in points) before the trailing SL is moved.
# 1pt = one clean price increment on Gold. Prevents SL from chasing
# every sub-point tick while still keeping up with fast moves.
TRAIL_STEP_PTS = 100     # 1 pt on Gold ($0.01)

# Buffer above entry for the breakeven SL.
# 1pt above entry avoids broker rejection at exact entry price.
BE_BUFFER_PTS = 100      # 1 pt on Gold ($0.01)

# Tolerance (in points) used when deciding whether pos.sl is "at entry" (Stage 1).
# Must comfortably bracket BE_BUFFER_PTS. Set to 2pts so a SL anywhere
# between entry-2 and entry+2 is treated as "at breakeven".
# This is wider than the buffer to handle rounding at broker side.
BE_TOLERANCE_PTS = 200   # 2 pts on Gold ($0.02)


# ── Unit helpers ──────────────────────────────────────────────────────────────

def pts_to_price(points: float, info) -> float:
    """Convert a distance expressed in broker 'points' to a price-unit distance."""
    return points * info.point


# ─────────────────────────────────────────
# Comment parsing (read-only, creation only)
# ─────────────────────────────────────────

@dataclass
class OrderMeta:
    entry:  float   # original execution price
    sl_ref: float   # original SL (reference only)
    tp:     float   # this order's TP target

# Supports both integer and decimal prices (e.g. 5031, 5031.00, 1.08450)
COMMENT_RE = re.compile(r'E:([\d.]+)\|SL:([\d.]+)\|TP:([\d.]+)')

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

def infer_stage(pos, meta: OrderMeta, is_buy: bool, info) -> int:
    """
    Derive current stage purely from where pos.sl sits relative to entry.

    All comparisons use price-unit distances derived from the instrument's
    point size, so behaviour is identical across Gold, Forex, indices, etc.

    Stage 0 — SL is below entry (BUY) / above entry (SELL)
               i.e. still at or near the original risk level
    Stage 1 — SL is approximately at entry (within BE_TOLERANCE in price units)
    Stage 2 — SL is clearly above entry (BUY) / below entry (SELL)
               i.e. already locked in profit, in trailing territory
    """
    sl    = pos.sl
    entry = meta.entry
    tol   = pts_to_price(BE_TOLERANCE_PTS, info)

    if sl == 0.0:
        return 0    # no SL set yet — treat as watching

    if is_buy:
        if sl >= entry + tol:
            return 2    # SL clearly above entry → trailing
        if sl >= entry - tol:
            return 1    # SL within tolerance of entry → breakeven
        return 0        # SL clearly below entry → watching
    else:
        if sl <= entry - tol:
            return 2    # SL clearly below entry → trailing
        if sl <= entry + tol:
            return 1    # SL within tolerance of entry → breakeven
        return 0        # SL clearly above entry → watching


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
            f"step={TRAIL_STEP_PTS}pts | "
            f"BE buffer={BE_BUFFER_PTS}pts | "
            f"BE tolerance=±{BE_TOLERANCE_PTS}pts"
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
                continue    # not a bot order or unrecognised comment format

            active_tickets.add(pos.ticket)

            tick = mt5.symbol_info_tick(pos.symbol)
            info = mt5.symbol_info(pos.symbol)
            if not tick or not info:
                continue

            is_buy = (pos.type == mt5.ORDER_TYPE_BUY)
            price  = tick.bid if is_buy else tick.ask

            # Infer stage from current SL position (uses instrument info for unit conversion)
            stage = infer_stage(pos, meta, is_buy, info)

            if stage == 0:
                self._handle_watching(pos, meta, price, is_buy, info, tick)
            elif stage == 1:
                self._handle_breakeven(pos, meta, price, is_buy, info, tick)
            elif stage == 2:
                self._handle_trailing(pos, meta, price, is_buy, info, tick)

        # Clean up trail state for closed positions
        for t in set(self._trail) - active_tickets:
            del self._trail[t]

    # ─────────────────────────────────────────
    # Stage 0: Watching — wait for TP hit
    # ─────────────────────────────────────────

    def _handle_watching(self, pos, meta: OrderMeta, price: float,
                         is_buy: bool, info, tick):
        if not self._hit(is_buy, price, meta.tp):
            return

        buf    = pts_to_price(BE_BUFFER_PTS, info)
        new_sl = round(meta.entry + (buf if is_buy else -buf), info.digits)

        if self._modify(pos, new_sl, tick, info, is_buy):
            direction = "BUY" if is_buy else "SELL"
            print(
                f"\n{'─'*45}\n"
                f"🔒 BREAKEVEN SET\n"
                f"   Ticket : {pos.ticket}  {pos.symbol} {direction}\n"
                f"   TP hit : {meta.tp:.{info.digits}f}  (price @ {price:.{info.digits}f})\n"
                f"   SL     : {pos.sl:.{info.digits}f} → {new_sl:.{info.digits}f}  "
                f"(entry + {BE_BUFFER_PTS}pts buffer)\n"
                f"{'─'*45}"
            )

    # ─────────────────────────────────────────
    # Stage 1: Breakeven — transition to trail
    # ─────────────────────────────────────────

    def _handle_breakeven(self, pos, meta: OrderMeta, price: float,
                          is_buy: bool, info, tick):
        """
        SL is at entry — initialise trail state and hand off to trailing.
        This is a one-shot setup; on the next scan infer_stage() will
        return stage 2 (SL above/below entry) and go straight to trailing.
        """
        if pos.ticket not in self._trail:
            self._trail[pos.ticket] = TrailState(trail_peak=price)
            print(
                f"🏃 TRAILING STARTED  ticket={pos.ticket} | "
                f"peak={price:.{info.digits}f} | "
                f"trail={TRAIL_PTS}pts ({pts_to_price(TRAIL_PTS, info):.{info.digits}f}) behind price"
            )
        self._handle_trailing(pos, meta, price, is_buy, info, tick)

    # ─────────────────────────────────────────
    # Stage 2: Trailing
    # ─────────────────────────────────────────

    def _handle_trailing(self, pos, meta: OrderMeta, price: float,
                         is_buy: bool, info, tick):
        """Trail SL behind price by TRAIL_PTS, stepping by TRAIL_STEP_PTS."""

        # Convert point-based constants to price-unit distances for this instrument
        trail_dist = pts_to_price(TRAIL_PTS, info)
        step_dist  = pts_to_price(TRAIL_STEP_PTS, info)

        # Initialise trail state if missing (e.g. after bot restart)
        if pos.ticket not in self._trail:
            self._trail[pos.ticket] = TrailState(trail_peak=price)
            print(
                f"🔄 TRAIL RESUMED     ticket={pos.ticket} | "
                f"peak reset @ {price:.{info.digits}f} (bot restarted)"
            )

        state = self._trail[pos.ticket]

        if is_buy:
            # Advance peak upward only
            if price > state.trail_peak:
                state.trail_peak = price

            desired_sl = round(state.trail_peak - trail_dist, info.digits)
            advance    = desired_sl - pos.sl

            if desired_sl > pos.sl and advance >= step_dist:
                if self._modify(pos, desired_sl, tick, info, is_buy):
                    print(
                        f"📈 TRAIL ↑  ticket={pos.ticket} | "
                        f"price={price:.{info.digits}f}  peak={state.trail_peak:.{info.digits}f} | "
                        f"SL {pos.sl:.{info.digits}f} → {desired_sl:.{info.digits}f}"
                    )
        else:
            # Advance peak downward only
            if state.trail_peak == 0.0 or price < state.trail_peak:
                state.trail_peak = price

            desired_sl = round(state.trail_peak + trail_dist, info.digits)
            cur_sl     = pos.sl
            advance    = (cur_sl - desired_sl) if cur_sl > 0 else float('inf')

            if (cur_sl == 0.0 or desired_sl < cur_sl) and advance >= step_dist:
                if self._modify(pos, desired_sl, tick, info, is_buy):
                    print(
                        f"📉 TRAIL ↓  ticket={pos.ticket} | "
                        f"price={price:.{info.digits}f}  peak={state.trail_peak:.{info.digits}f} | "
                        f"SL {pos.sl:.{info.digits}f} → {desired_sl:.{info.digits}f}"
                    )

    # ─────────────────────────────────────────
    # MT5 modification
    # ─────────────────────────────────────────

    @staticmethod
    def _modify(pos, new_sl: float, tick, info, is_buy: bool) -> bool:
        """Send SL modification to MT5. Returns True on success."""
        pt = info.point

        # Safety clamp — SL must not cross current price
        if is_buy  and new_sl >= tick.bid:
            new_sl = round(tick.bid - pt, info.digits)
        if not is_buy and new_sl <= tick.ask:
            new_sl = round(tick.ask + pt, info.digits)

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