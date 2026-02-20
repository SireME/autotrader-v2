"""
Simple Trading Signal Parser v3.0
===================================
Strict regex-only parser. No AI. No hallucinations.

Accepted trigger phrases (case-insensitive):
  BUY:  "Gold buy now"  |  "Buy gold now"  |  "Buy gold 4982"
  SELL: "Gold sell now" |  "Sell gold now" |  "Sell gold 4982"

Any other message is ignored entirely — no AI call, no regex fallback,
no ambiguity.

Optional structured signal body after the trigger:
  Gold buy now 5010 - 5007
  SL: 5004
  TP: 5012
  TP: 5014
  TP: 5016
  TP: open          ← ignored (not a price)

Config:
  USE_AI_PARSER = False   (default — recommended)
  USE_AI_PARSER = True    (re-enables Groq AI — not recommended)
"""

import re
import os
import logging
from typing import Optional, Dict, List, Tuple, Callable
from dataclasses import dataclass, field
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Config flag — change here to enable AI
# ─────────────────────────────────────────────

USE_AI_PARSER = False


# ─────────────────────────────────────────────
# Data Models
# ─────────────────────────────────────────────

@dataclass
class SymbolConfig:
    aliases: List[str]
    min_price: float
    max_price: float
    sl_pct: float
    tp_pct: float
    typical_spread_pct: float
    fixed_sl_points: float = 0.0
    fixed_tp_points: List[float] = field(default_factory=list)


# ─────────────────────────────────────────────
# Parser
# ─────────────────────────────────────────────

class SignalParser:
    """
    Accepts only explicit 'Gold buy/sell now' triggers.
    Everything else is rejected at the door — before any parsing occurs.
    """

    # ── Accepted triggers ─────────────────────────────────────────
    BUY_TRIGGERS = [
        re.compile(r'\bgold\s+buy\s+now\b',  re.IGNORECASE),
        re.compile(r'\bbuy\s+gold\s+now\b',  re.IGNORECASE),
        re.compile(r'\bbuy\s+gold\b',         re.IGNORECASE),
    ]
    SELL_TRIGGERS = [
        re.compile(r'\bgold\s+sell\s+now\b', re.IGNORECASE),
        re.compile(r'\bsell\s+gold\s+now\b', re.IGNORECASE),
        re.compile(r'\bsell\s+gold\b',        re.IGNORECASE),
    ]

    # ── Provider Gold config ──────────────────────────────────────
    # SL = 3pts from entry, TPs at +5, +7, +9 pts (provider pattern)
    XAUUSD_CONFIG = SymbolConfig(
        aliases=["XAUUSD", "XAU", "GOLD"],
        min_price=2000.0,
        max_price=6000.0,
        sl_pct=0.003,
        tp_pct=0.006,
        typical_spread_pct=0.0002,
        fixed_sl_points=3.0,
        fixed_tp_points=[5.0, 7.0, 9.0],
    )

    def __init__(self, price_provider: Callable[[str], float],
                 groq_api_key: Optional[str] = None):
        self.price_provider = price_provider
        self.ai_enabled = False

        if USE_AI_PARSER:
            if groq_api_key or os.getenv("GROQ_API_KEY"):
                self._init_groq(groq_api_key or os.getenv("GROQ_API_KEY"))
            else:
                logger.warning("USE_AI_PARSER=True but no GROQ_API_KEY — AI disabled")
        else:
            logger.info("✅ Simple regex parser active (USE_AI_PARSER=False) — AI disabled")

    def _init_groq(self, api_key: str):
        try:
            from groq import Groq
            self.groq_client = Groq(api_key=api_key)
            self.ai_enabled = True
            logger.info("✨ AI-enhanced parsing enabled (Groq)")
        except Exception as e:
            logger.error(f"Groq init failed: {e} — using regex only")

    # ─────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────

    def parse(self, message: str, use_ai: bool = True) -> Optional[Dict]:
        """
        Parse a Telegram message into a trade signal.

        Returns None for anything that isn't an explicit Gold buy/sell trigger.
        No AI is called unless USE_AI_PARSER=True AND message passed trigger check.
        """
        if not message or len(message.strip()) < 5:
            logger.info("❌ Message too short")
            return None

        # ── Gate 1: Trigger check — must match accepted phrase ────
        direction = self._detect_trigger(message)
        if direction is None:
            logger.info("❌ No accepted trigger phrase — skipped")
            return None

        logger.info(f"✅ Trigger: {direction.upper()} GOLD")

        # ── Optional: AI parsing (only if enabled) ────────────────
        if self.ai_enabled and use_ai and USE_AI_PARSER:
            result = self._parse_with_ai(message, direction)
            if result:
                return result
            logger.warning("AI parsing failed — falling back to regex")

        # ── Regex extraction ──────────────────────────────────────
        return self._parse_with_regex(message, direction)

    # ─────────────────────────────────────────
    # Trigger Detection
    # ─────────────────────────────────────────

    def _detect_trigger(self, message: str) -> Optional[str]:
        """Return 'buy', 'sell', or None."""
        for pat in self.BUY_TRIGGERS:
            if pat.search(message):
                return "buy"
        for pat in self.SELL_TRIGGERS:
            if pat.search(message):
                return "sell"
        return None

    # ─────────────────────────────────────────
    # Regex Parsing
    # ─────────────────────────────────────────

    def _parse_with_regex(self, message: str, direction: str) -> Optional[Dict]:
        entry, entry_high = self._extract_entry_range(message, direction)
        sl   = self._extract_sl(message)
        tps  = self._extract_tps(message)

        used_market_price = False
        used_fallback_sl  = False

        # No explicit entry → use live price
        if entry is None:
            try:
                entry      = self.price_provider("XAUUSD")
                entry_high = entry
                used_market_price = True
                logger.info(f"✅ Using live market price for XAUUSD: {entry}")
            except Exception as e:
                logger.error(f"❌ Failed to get live price: {e}")
                return None

        # No SL or TPs → use provider-pattern fallback
        if sl is None or not tps:
            sl, tps = self._fallback_risk(direction, entry)
            used_fallback_sl = True

        if not self._validate(direction, entry, sl):
            logger.warning(f"❌ Invalid prices: entry={entry}, sl={sl}")
            return None

        entry_range_width = round(abs((entry_high or entry) - entry), 2)
        confidence = 1.0 if not used_fallback_sl else 0.65

        return {
            "symbol":      "XAUUSD",
            "direction":   direction,
            "entry":       round(entry, 2),
            "stop_loss":   round(sl, 2),
            "take_profit": [round(t, 2) for t in tps],
            "order_type":  "market" if used_market_price else "limit",
            "confidence":  confidence,
            "raw":         message,
            "metadata": {
                "used_market_price": used_market_price,
                "used_fallback_sl":  used_fallback_sl,
                "entry_range_width": entry_range_width,
                "risk_reward_ratio": self._rr(entry, sl, tps),
                "parsing_method":    "regex",
                "timestamp":         datetime.utcnow().isoformat(),
            }
        }

    # ─────────────────────────────────────────
    # Price Extraction
    # ─────────────────────────────────────────

    def _extract_entry_range(self, text: str, direction: str
                              ) -> Tuple[Optional[float], Optional[float]]:
        """
        Find entry price or range, ignoring SL/TP lines.
        BUY  → returns (lower_bound, upper_bound)
        SELL → returns (upper_bound, lower_bound)
        """
        # Remove SL and TP lines so their numbers don't pollute entry search
        clean = re.sub(
            r'(?:SL|S\.?L|STOP(?:\s+LOSS)?|TP|T\.?P|TAKE\s*PROFIT|S/L|T/P)[^\n]*',
            '', text, flags=re.IGNORECASE
        )

        # Range: two 3-6 digit prices separated by dash or en-dash
        m = re.search(
            r'(\d{3,6}(?:\.\d+)?)\s*[-–]\s*(\d{3,6}(?:\.\d+)?)',
            clean
        )
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            if direction == "buy":
                return min(a, b), max(a, b)    # enter at lower bound
            else:
                return max(a, b), min(a, b)    # enter at upper bound

        # Single price
        m = re.search(r'\b(\d{3,6}(?:\.\d+)?)\b', clean)
        if m:
            v = float(m.group(1))
            return v, v

        return None, None

    def _extract_sl(self, text: str) -> Optional[float]:
        """
        Recognise stop loss in any of these formats:
          SL: 1234  |  S.L 1234  |  Sl 1234  |  Stop Loss 1234  |  S/L 1234
        """
        m = re.search(
            r'(?:S\.?/?L\.?|STOP\s*LOSS)\s*[:=.]?\s*(\d{3,6}(?:\.\d+)?)',
            text, re.IGNORECASE
        )
        return float(m.group(1)) if m else None

    def _extract_tps(self, text: str) -> List[float]:
        """
        Extract all numeric take profits.
        Ignores 'TP: open' and similar non-numeric values.
        """
        tps = []
        for m in re.finditer(
            r'(?:T\.?P\.?|TAKE\s*PROFIT|T/P)\s*[:=.]?\s*(\d{3,6}(?:\.\d+)?)',
            text, re.IGNORECASE
        ):
            tps.append(float(m.group(1)))
        return tps

    # ─────────────────────────────────────────
    # Fallback Risk (provider pattern)
    # ─────────────────────────────────────────

    def _fallback_risk(self, direction: str, entry: float
                        ) -> Tuple[float, List[float]]:
        """
        Provider-matched levels:
          BUY:  SL = entry - 3,  TPs = [entry+5, entry+7, entry+9]
          SELL: SL = entry + 3,  TPs = [entry-5, entry-7, entry-9]
        """
        cfg = self.XAUUSD_CONFIG
        sl_d = cfg.fixed_sl_points

        if direction == "buy":
            sl  = round(entry - sl_d, 2)
            tps = [round(entry + d, 2) for d in cfg.fixed_tp_points]
        else:
            sl  = round(entry + sl_d, 2)
            tps = [round(entry - d, 2) for d in cfg.fixed_tp_points]

        logger.info(
            f"✅ Point-based fallback SL/TP for XAUUSD: "
            f"SL={sl} ({sl_d}pts), TPs={tps} ({cfg.fixed_tp_points}pts)"
        )
        return sl, tps

    # ─────────────────────────────────────────
    # Validation & Helpers
    # ─────────────────────────────────────────

    def _validate(self, direction: str, entry: float, sl: float) -> bool:
        if entry <= 0 or sl <= 0:
            return False
        if direction == "buy"  and sl >= entry:
            return False
        if direction == "sell" and sl <= entry:
            return False
        # Gold price sanity check
        cfg = self.XAUUSD_CONFIG
        if not (cfg.min_price <= entry <= cfg.max_price):
            logger.warning(f"⚠️  Entry {entry} outside Gold price range "
                           f"({cfg.min_price}–{cfg.max_price})")
            return False
        return True

    def _rr(self, entry: float, sl: float, tps: List[float]) -> float:
        if not tps or sl == entry:
            return 0.0
        risk   = abs(entry - sl)
        reward = abs(tps[0] - entry)
        return round(reward / risk, 2) if risk else 0.0

    # ─────────────────────────────────────────
    # AI Parsing (optional, USE_AI_PARSER=True)
    # ─────────────────────────────────────────

    def _parse_with_ai(self, message: str, direction: str) -> Optional[Dict]:
        """
        AI parsing path — only reached if USE_AI_PARSER=True.
        Trigger already validated before this is called.
        """
        if not self.ai_enabled:
            return None

        prompt = f"""
The following message has already been identified as a Gold {direction.upper()} signal.
Extract the price levels ONLY from explicit numbers in the message.
Do NOT invent or assume any prices.

Message: {message}

Return JSON only:
{{
  "entry": <number or null>,
  "entry_high": <second range bound or null>,
  "stop_loss": <number or null>,
  "take_profit": [<numbers only, no "open">]
}}
"""
        try:
            resp = self.groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content":
                        "You extract price numbers from trading signals. "
                        "Return only valid JSON. Never invent prices."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,
                max_tokens=200,
            )
            raw = resp.choices[0].message.content.strip()
            import json
            data = json.loads(raw.replace("```json", "").replace("```", ""))

            entry      = data.get("entry") or None
            entry_high = data.get("entry_high") or entry
            sl         = data.get("stop_loss") or None
            tps        = data.get("take_profit") or []

            # Treat 0 as null
            if entry == 0:   entry = None
            if entry_high == 0: entry_high = None

            used_market_price = False
            used_fallback_sl  = False

            if entry is None:
                entry = self.price_provider("XAUUSD")
                entry_high = entry
                used_market_price = True

            if sl is None or not tps:
                sl, tps = self._fallback_risk(direction, entry)
                used_fallback_sl = True

            if not self._validate(direction, entry, sl):
                return None

            entry_range_width = round(abs((entry_high or entry) - entry), 2)

            return {
                "symbol":      "XAUUSD",
                "direction":   direction,
                "entry":       round(entry, 2),
                "stop_loss":   round(sl, 2),
                "take_profit": [round(t, 2) for t in tps],
                "order_type":  "market" if used_market_price else "limit",
                "confidence":  1.0 if not used_fallback_sl else 0.65,
                "raw":         message,
                "metadata": {
                    "used_market_price": used_market_price,
                    "used_fallback_sl":  used_fallback_sl,
                    "entry_range_width": entry_range_width,
                    "risk_reward_ratio": self._rr(entry, sl, tps),
                    "parsing_method":    "ai",
                    "timestamp":         datetime.utcnow().isoformat(),
                }
            }
        except Exception as e:
            logger.error(f"AI parsing error: {e}")
            return None