"""
Intent-Aware Trading Signal Parser - AI-Enhanced v2.2
====================================================

Fixes in v2.2:
- Correct Groq model usage
- Removed unsupported OpenAI-only parameters
- Hardened JSON parsing from AI
- Explicit API key handling
- Full regex fallback preserved

License: MIT
"""

import re
import os
import json
from typing import Optional, Dict, List, Callable, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging
from dotenv import load_dotenv
load_dotenv()


# =========================
# Logging Setup
# =========================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# Data Models
# =========================

@dataclass
class SymbolConfig:
    aliases: List[str]
    min_price: float
    max_price: float
    sl_pct: float
    tp_pct: float
    typical_spread_pct: float


# =========================
# Signal Parser
# =========================

class SignalParser:
    """
    Intent-aware Telegram signal parser with AI enhancement.
    """

    BUY_KEYWORDS = {
        "BUY", "LONG", "BULL", "BULLISH",
        "BUY NOW", "BUY MARKET", "GO LONG",
        "OPEN BUY", "ENTRY BUY",
    }

    SELL_KEYWORDS = {
        "SELL", "SHORT", "BEAR", "BEARISH",
        "SELL NOW", "SELL MARKET", "GO SHORT",
        "OPEN SELL", "ENTRY SELL",
    }

    MARKET_KEYWORDS = {"NOW", "MARKET", "IMMEDIATE", "INSTANTLY"}

    SYMBOL_CONFIGS = {
        "XAUUSD": SymbolConfig(
            aliases=["XAUUSD", "XAU", "GOLD"],
            min_price=2000.0,
            max_price=6000.0,
            sl_pct=0.003,
            tp_pct=0.006,
            typical_spread_pct=0.0002
        ),
        "EURUSD": SymbolConfig(
            aliases=["EURUSD", "EU", "EUR"],
            min_price=0.8,
            max_price=1.3,
            sl_pct=0.0015,
            tp_pct=0.003,
            typical_spread_pct=0.00001
        ),
        "GBPUSD": SymbolConfig(
            aliases=["GBPUSD", "GU", "GBP", "CABLE"],
            min_price=1.0,
            max_price=1.5,
            sl_pct=0.0015,
            tp_pct=0.003,
            typical_spread_pct=0.00001
        ),
        "USDJPY": SymbolConfig(
            aliases=["USDJPY", "UJ", "USD/JPY"],
            min_price=100.0,
            max_price=160.0,
            sl_pct=0.002,
            tp_pct=0.004,
            typical_spread_pct=0.00015
        ),
    }

    # =========================
    # Initialization
    # =========================

    def __init__(self, price_provider: Callable[[str], float], groq_api_key: Optional[str] = None):
        self.price_provider = price_provider
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.ai_enabled = bool(self.groq_api_key)

        if self.ai_enabled:
            logger.info("✨ AI-enhanced parsing enabled (Groq)")
            self._init_groq_client()
        else:
            logger.info("📋 Regex-only parsing (no Groq API key found)")

    def _init_groq_client(self):
        try:
            from groq import Groq
            self.groq_client = Groq(api_key=self.groq_api_key)
            logger.info("Groq client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Groq client: {e}")
            self.ai_enabled = False

    # =========================
    # Public API
    # =========================

    def parse(self, message: str, use_ai: bool = True) -> Optional[Dict]:
        if not message or len(message.strip()) < 5:
            return None

        if self.ai_enabled and use_ai:
            logger.info("🤖 Attempting AI parsing...")
            result = self._parse_with_ai(message)
            if result:
                result["metadata"]["parsing_method"] = "ai"
                result["confidence"] = min(1.0, result["confidence"] + 0.1)
                return result
            logger.warning("AI parsing failed, falling back to regex")

        logger.info("📋 Using regex parsing")
        result = self._parse_with_regex(message)
        if result:
            result["metadata"]["parsing_method"] = "regex"
        return result

    # =========================
    # AI Parsing
    # =========================

    def _parse_with_ai(self, message: str) -> Optional[Dict]:
        prompt = self._create_ai_prompt(message)

        try:
            response = self.groq_client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert trading signal parser. "
                            "Return ONLY valid JSON. No markdown. No explanation."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500,
            )

            ai_output = response.choices[0].message.content.strip()

            if not ai_output.startswith("{"):
                logger.error("AI returned non-JSON output")
                return None

            parsed = json.loads(ai_output)
            return self._process_ai_output(parsed, message)

        except Exception as e:
            logger.error(f"AI parsing error: {e}")
            return None

    def _create_ai_prompt(self, message: str) -> str:
        return f"""
Parse the following trading signal and return structured JSON.

Message:
{message}

Supported symbols: {', '.join(self.SYMBOL_CONFIGS.keys())}

JSON format:
{{
  "symbol": "XAUUSD",
  "direction": "buy",
  "entry": 2050.5,
  "stop_loss": 2044.0,
  "take_profit": [2062.0],
  "is_market_order": false
}}
"""

    def _process_ai_output(self, data: Dict, raw: str) -> Optional[Dict]:
        symbol = self._map_symbol_alias(data.get("symbol"))
        direction = (data.get("direction") or "").lower()
        entry = data.get("entry")
        sl = data.get("stop_loss")
        tp = data.get("take_profit", [])
        is_market = data.get("is_market_order", False)

        if not symbol or direction not in {"buy", "sell"}:
            return None

        used_market_price = False
        used_fallback_sl = False

        if is_market and entry is None:
            entry = self.price_provider(symbol)
            used_market_price = True

        if entry and sl is None:
            sl, tp = self._fallback_risk(symbol, direction, entry)
            used_fallback_sl = True

        if entry is None or sl is None:
            return None

        if not self._validate_price_logic(symbol, direction, entry, sl):
            return None

        confidence = self._calculate_confidence(
            has_explicit_entry=not used_market_price,
            has_sl=not used_fallback_sl,
            has_tp=bool(tp) and not used_fallback_sl,
            is_market=is_market
        )

        return {
            "symbol": symbol,
            "direction": direction,
            "entry": round(entry, 5),
            "stop_loss": round(sl, 5),
            "take_profit": [round(x, 5) for x in tp],
            "order_type": "market" if is_market else "limit",
            "confidence": confidence,
            "raw": raw,
            "metadata": {
                "used_market_price": used_market_price,
                "used_fallback_sl": used_fallback_sl,
                "timestamp": datetime.utcnow().isoformat(),
                "risk_reward_ratio": self._calculate_rr_ratio(entry, sl, tp),
            }
        }

    def _map_symbol_alias(self, symbol: Optional[str]) -> Optional[str]:
        if not symbol:
            return None
        symbol = symbol.upper()
        if symbol in self.SYMBOL_CONFIGS:
            return symbol
        for k, cfg in self.SYMBOL_CONFIGS.items():
            if symbol in cfg.aliases:
                return k
        return None

    # =========================
    # Regex Parsing (Fallback)
    # =========================

    def _parse_with_regex(self, message: str) -> Optional[Dict]:
        raw = message
        text = self._normalize(message)

        direction = self._detect_direction(text)
        if not direction:
            return None

        symbol = self._detect_symbol(text)
        if not symbol:
            return None

        is_market = self._is_market_order(text)

        entry = self._extract_entry(text)
        sl = self._extract_stop_loss(text)
        tp = self._extract_take_profits(text)

        used_market_price = False
        used_fallback_sl = False

        if is_market and entry is None:
            entry = self.price_provider(symbol)
            used_market_price = True

        if entry and sl is None:
            sl, tp = self._fallback_risk(symbol, direction, entry)
            used_fallback_sl = True

        if entry is None or sl is None:
            return None

        if not self._validate_price_logic(symbol, direction, entry, sl):
            return None

        confidence = self._calculate_confidence(
            has_explicit_entry=bool(entry),
            has_sl=not used_fallback_sl,
            has_tp=bool(tp) and not used_fallback_sl,
            is_market=is_market
        )

        return {
            "symbol": symbol,
            "direction": direction,
            "entry": round(entry, 5),
            "stop_loss": round(sl, 5),
            "take_profit": [round(x, 5) for x in tp],
            "order_type": "market" if is_market else "limit",
            "confidence": confidence,
            "raw": raw,
            "metadata": {
                "used_market_price": used_market_price,
                "used_fallback_sl": used_fallback_sl,
                "timestamp": datetime.utcnow().isoformat(),
                "risk_reward_ratio": self._calculate_rr_ratio(entry, sl, tp),
            }
        }

    # =========================
    # Regex Helpers
    # =========================

    def _normalize(self, text: str) -> str:
        text = text.upper()
        text = re.sub(r"(\d),(\d)", r"\1\2", text)
        text = re.sub(r"[^\w\s.\-@/()\[\]]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return f" {text.strip()} "

    def _detect_direction(self, text: str) -> Optional[str]:
        buy_hits = sum(kw in text for kw in self.BUY_KEYWORDS)
        sell_hits = sum(kw in text for kw in self.SELL_KEYWORDS)
        if buy_hits > sell_hits:
            return "buy"
        if sell_hits > buy_hits:
            return "sell"
        return None

    def _detect_symbol(self, text: str) -> Optional[str]:
        for symbol, cfg in self.SYMBOL_CONFIGS.items():
            for alias in cfg.aliases:
                if f" {alias} " in text:
                    return symbol
        return None

    def _extract_entry(self, text: str) -> Optional[float]:
        patterns = [
            r"(?:ENTRY|ENTER|PRICE|@)\s*[:=@]?\s*(\d+\.?\d*)",
            r"(?:BUY|SELL)\s+(\d+\.?\d*)"
        ]
        for p in patterns:
            m = re.search(p, text)
            if m:
                return float(m.group(1))
        return None

    def _extract_stop_loss(self, text: str) -> Optional[float]:
        m = re.search(r"(?:SL|STOP\s*LOSS)\s*[:=@]?\s*(\d+\.?\d*)", text)
        return float(m.group(1)) if m else None

    def _extract_take_profits(self, text: str) -> List[float]:
        return [float(x) for x in re.findall(r"(?:TP\d*|TARGET\d*)\s*[:=@]?\s*(\d+\.?\d*)", text)]

    def _is_market_order(self, text: str) -> bool:
        return any(kw in text for kw in self.MARKET_KEYWORDS)

    # =========================
    # Validation & Risk
    # =========================

    def _validate_price_logic(self, symbol: str, direction: str, entry: float, sl: float) -> bool:
        if entry <= 0 or sl <= 0:
            return False
        if direction == "buy" and sl >= entry:
            return False
        if direction == "sell" and sl <= entry:
            return False

        cfg = self.SYMBOL_CONFIGS[symbol]
        return cfg.min_price <= entry <= cfg.max_price

    def _fallback_risk(self, symbol: str, direction: str, entry: float) -> Tuple[float, List[float]]:
        cfg = self.SYMBOL_CONFIGS[symbol]
        sl_dist = entry * cfg.sl_pct
        tp_dist = entry * cfg.tp_pct
        spread = entry * cfg.typical_spread_pct

        if direction == "buy":
            return entry - sl_dist - spread, [entry + tp_dist]
        return entry + sl_dist + spread, [entry - tp_dist]

    def _calculate_confidence(self, has_explicit_entry, has_sl, has_tp, is_market) -> float:
        score = 0.4
        score += 0.2 if has_explicit_entry else 0
        score += 0.2 if has_sl else 0
        score += 0.15 if has_tp else 0
        score -= 0.05 if is_market else 0
        return min(1.0, max(0.0, score))

    def _calculate_rr_ratio(self, entry: float, sl: float, tp: List[float]) -> Optional[float]:
        if not tp:
            return None
        risk = abs(entry - sl)
        reward = abs(entry - tp[0])
        return round(reward / risk, 2) if risk > 0 else None



# =========================
# Example Usage
# =========================

def example_mock_price_provider(symbol: str) -> float:
    """Mock price provider for testing"""
    prices = {
        "XAUUSD": 2050.50,
        "EURUSD": 1.0850,
        "GBPUSD": 1.2650,
        "USDJPY": 148.50,
    }
    price = prices.get(symbol)
    if price is None:
        raise ValueError(f"Unknown symbol: {symbol}")
    return price


if __name__ == "__main__":
    # Example 1: With Groq API key (AI-enhanced)
    print("="*60)
    print("EXAMPLE 1: AI-Enhanced Parsing (with Groq)")
    print("="*60)

    # Set your Groq API key here or in environment
    # os.environ['GROQ_API_KEY'] = 'your-api-key-here'

    parser_ai = SignalParser(
        price_provider=example_mock_price_provider,
        groq_api_key=os.getenv('GROQ_API_KEY')  # Or pass directly
    )

    # test_signal = """
    # 📊 GOLD Signal Alert! 🚀

    # I'm seeing a strong bullish setup on XAUUSD.
    # Looking to enter around 2050-2051 area.
    # Stop below 2044 to manage risk.
    # First target is 2062, second at 2070.
    # """

    # test_signal = """
    # 📊 GOLD Signal Alert! 🚀

    #      Gold buy now 5094 - 5091

    #      SL: 5088
    #      TP: 5096
    #      TP: 5098
    #      TP: 5100
    #      TP: open
    # """

    test_signal = "buy eur now guys"

    result = parser_ai.parse(test_signal)
    print(f'results all are {result}')

    if result:
        print(f"\n✅ PARSED SUCCESSFULLY")
        print(f"Method: {result['metadata']['parsing_method'].upper()}")
        print(f"Symbol: {result['symbol']}")
        print(f"Direction: {result['direction'].upper()}")
        print(f"Entry: {result['entry']}")
        print(f"Stop Loss: {result['stop_loss']}")
        print(f"Take Profit: {result['take_profit']}")
        print(f"Confidence: {result['confidence']:.1%}")
    else:
        print("\n❌ PARSING FAILED")

    # Example 2: Without API key (regex fallback)
    print("\n" + "="*60)
    print("EXAMPLE 2: Regex-Only Parsing (no API key)")
    print("="*60)

    parser_regex = SignalParser(price_provider=example_mock_price_provider)

    result2 = parser_regex.parse("BUY XAUUSD @ 2050 SL 2044 TP 2062")

    if result2:
        print(f"\n✅ PARSED SUCCESSFULLY")
        print(f"Method: {result2['metadata']['parsing_method'].upper()}")
        print(f"Symbol: {result2['symbol']}")
        print(f"Direction: {result2['direction'].upper()}")
        print(f"Confidence: {result2['confidence']:.1%}")

