"""
Intent-Aware Trading Signal Parser - Production Ready v2.0
===========================================================

Enhancements over v1:
- Price validation with symbol-specific bounds
- Comprehensive error handling for price provider
- Enhanced regex patterns to avoid false positives
- Confidence scoring system
- Spread-aware fallback logic
- ATR-ready architecture
- Rich metadata for debugging

Author: Upgraded based on code review
License: MIT
"""

import re
from typing import Optional, Dict, List, Callable, Tuple
from dataclasses import dataclass
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class SymbolConfig:
    """Configuration for each trading symbol"""
    aliases: List[str]
    min_price: float
    max_price: float
    sl_pct: float  # Stop loss percentage
    tp_pct: float  # Take profit percentage
    typical_spread_pct: float  # Typical spread as percentage


class SignalParser:
    """
    Intent-aware Telegram signal parser.
    Handles market orders, missing entries, and fallback risk logic.
    
    Features:
    - Market order detection with live price fetching
    - Automatic SL/TP calculation when missing
    - Price validation and sanity checks
    - Confidence scoring
    - Comprehensive error handling
    - Spread-aware risk management
    """

    # Direction keywords
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

    # Symbol configurations with bounds and risk parameters
    SYMBOL_CONFIGS = {
        "XAUUSD": SymbolConfig(
            aliases=["XAUUSD", "XAU", "GOLD"],
            min_price=1000.0,
            max_price=3500.0,
            sl_pct=0.003,  # 0.3% (~$6-7 on $2000 gold)
            tp_pct=0.006,  # 0.6% (1:2 R:R)
            typical_spread_pct=0.0002  # ~2 pips
        ),
        "EURUSD": SymbolConfig(
            aliases=["EURUSD", "EU", "EUR"],
            min_price=0.8,
            max_price=1.3,
            sl_pct=0.0015,  # 15 pips
            tp_pct=0.003,   # 30 pips (1:2 R:R)
            typical_spread_pct=0.00001  # ~1 pip
        ),
        "GBPUSD": SymbolConfig(
            aliases=["GBPUSD", "GU", "GBP", "CABLE"],
            min_price=1.0,
            max_price=1.5,
            sl_pct=0.0015,  # 15 pips
            tp_pct=0.003,   # 30 pips (1:2 R:R)
            typical_spread_pct=0.00001  # ~1 pip
        ),
        "USDJPY": SymbolConfig(
            aliases=["USDJPY", "UJ", "USD/JPY"],
            min_price=100.0,
            max_price=160.0,
            sl_pct=0.002,   # ~20 pips
            tp_pct=0.004,   # ~40 pips (1:2 R:R)
            typical_spread_pct=0.00015  # ~1.5 pips
        ),
    }

    def __init__(self, price_provider: Callable[[str], float]):
        """
        Initialize parser with price provider function.
        
        Args:
            price_provider: Function that takes symbol (str) and returns current price (float)
                          Should raise exception or return None on failure
        """
        self.price_provider = price_provider

    # =========================
    # Public API
    # =========================

    def parse(self, message: str) -> Optional[Dict]:
        """
        Parse a trading signal message.
        
        Args:
            message: Raw message text from Telegram or other source
            
        Returns:
            Dictionary with signal details or None if parsing failed
            
        Example:
            {
                "symbol": "XAUUSD",
                "direction": "buy",
                "entry": 2050.50,
                "stop_loss": 2044.35,
                "take_profit": [2062.80],
                "order_type": "limit",
                "confidence": 0.8,
                "raw": "...",
                "metadata": {...}
            }
        """
        if not message or len(message.strip()) < 5:
            logger.debug("Message too short or empty")
            return None

        raw = message
        text = self._normalize(message)

        # Extract components
        direction = self._detect_direction(text)
        if not direction:
            logger.debug("Could not detect direction")
            return None

        symbol = self._detect_symbol(text)
        if not symbol:
            logger.debug("Could not detect symbol")
            return None

        is_market = self._is_market_order(text)

        entry = self._extract_entry(text)
        stop_loss = self._extract_stop_loss(text)
        take_profit = self._extract_take_profits(text)

        # Track what was auto-generated for metadata
        used_market_price = False
        used_fallback_sl = False

        # =========================
        # Market order handling
        # =========================

        if is_market and entry is None:
            try:
                live_price = self.price_provider(symbol)
                if live_price is None or live_price <= 0:
                    logger.error(f"Price provider returned invalid price: {live_price}")
                    return None
                entry = live_price
                used_market_price = True
                logger.info(f"Using live market price for {symbol}: {entry}")
            except Exception as e:
                logger.error(f"Failed to get live price for {symbol}: {e}")
                return None

        # =========================
        # Fallback strategy
        # =========================

        if entry and stop_loss is None:
            stop_loss, take_profit = self._fallback_risk(
                symbol=symbol,
                direction=direction,
                entry=entry
            )
            used_fallback_sl = True
            logger.info(f"Applied fallback SL/TP: SL={stop_loss}, TP={take_profit}")

        # =========================
        # Validation gate
        # =========================

        if entry is None or stop_loss is None:
            logger.warning("Missing entry or stop loss after all attempts")
            return None

        # Validate price logic
        if not self._validate_price_logic(symbol, direction, entry, stop_loss):
            logger.error("Price validation failed")
            return None

        # Calculate confidence score
        confidence = self._calculate_confidence(
            has_explicit_entry=bool(re.search(r"(ENTRY|ENTER|@|PRICE)", text)),
            has_sl=not used_fallback_sl,
            has_tp=bool(take_profit) and not used_fallback_sl,
            is_market=is_market
        )

        return {
            "symbol": symbol,
            "direction": direction,
            "entry": round(entry, 5),
            "stop_loss": round(stop_loss, 5),
            "take_profit": [round(tp, 5) for tp in take_profit],
            "order_type": "market" if is_market else "limit",
            "confidence": confidence,
            "raw": raw,
            "metadata": {
                "used_market_price": used_market_price,
                "used_fallback_sl": used_fallback_sl,
                "timestamp": datetime.utcnow().isoformat(),
                "risk_reward_ratio": self._calculate_rr_ratio(entry, stop_loss, take_profit),
            }
        }

    # =========================
    # Normalization
    # =========================

    def _normalize(self, text: str) -> str:
        """
        Normalize text while preserving important characters.
        
        Note: Commas are removed after upper-casing to avoid breaking number parsing
        """
        text = text.upper()
        # First remove commas from numbers (1,850.50 -> 1850.50)
        text = re.sub(r"(\d),(\d)", r"\1\2", text)
        # Keep: alphanumeric, whitespace, dots, dashes, @, slashes, parens
        text = re.sub(r"[^\w\s.\-@/()\[\]]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return f" {text.strip()} "

    # =========================
    # Direction Detection
    # =========================

    def _detect_direction(self, text: str) -> Optional[str]:
        """Detect trade direction from keywords"""
        buy_hits = sum(1 for kw in self.BUY_KEYWORDS if re.search(rf"\b{kw}\b", text))
        sell_hits = sum(1 for kw in self.SELL_KEYWORDS if re.search(rf"\b{kw}\b", text))

        if buy_hits and sell_hits:
            # If both present, use the one with more hits
            return "buy" if buy_hits > sell_hits else "sell"
        if buy_hits:
            return "buy"
        if sell_hits:
            return "sell"
        return None

    # =========================
    # Symbol Detection
    # =========================

    def _detect_symbol(self, text: str) -> Optional[str]:
        """Detect trading symbol from aliases"""
        for symbol, config in self.SYMBOL_CONFIGS.items():
            for alias in config.aliases:
                if re.search(rf"\b{alias}\b", text):
                    return symbol
        return None

    # =========================
    # Entry Extraction
    # =========================

    def _extract_entry(self, text: str) -> Optional[float]:
        """
        Extract entry price with improved pattern matching.
        
        Improvements:
        - Prioritize explicit entry markers
        - Validate price ranges are reasonable
        - Support both large (XAUUSD: 2050) and small (EURUSD: 1.0850) prices
        """
        # Priority 1: Explicit entry markers with colon or @
        entry_patterns = [
            r"(?:ENTRY|ENTER|PRICE)\s*[:=@]\s*(\d+\.?\d*)",
            r"@\s*(\d+\.?\d*)",
        ]
        
        for pattern in entry_patterns:
            match = re.search(pattern, text)
            if match:
                price = float(match.group(1))
                if price > 0:  # Basic sanity
                    return price

        # Priority 2: Entry zones (range) with context
        range_pattern = r"(?:ENTRY|ZONE|PRICE|@)?\s*(\d+\.?\d*)\s*[-–TO]\s*(\d+\.?\d*)"
        range_match = re.search(range_pattern, text)
        
        if range_match:
            low = float(range_match.group(1))
            high = float(range_match.group(2))
            
            # Validate it's a reasonable price range (not phone number, date, etc.)
            if low > 0 and high > low and (high - low) / low < 0.1:  # Less than 10% difference
                return (low + high) / 2
        
        # Priority 3: Entry word followed by price (looser match)
        loose_entry = re.search(r"(?:ENTRY|ENTER)\s+(\d+\.?\d*)", text)
        if loose_entry:
            price = float(loose_entry.group(1))
            if price > 0:
                return price
        
        # Priority 4: Price after direction but before SL/TP (context-aware)
        # Look for pattern: DIRECTION PRICE (must be reasonable and before SL/TP)
        context_pattern = r"(?:BUY|SELL|LONG|SHORT)\s+(\d+\.?\d*)"
        context_match = re.search(context_pattern, text)
        if context_match:
            price = float(context_match.group(1))
            if price > 0:
                # Validate it's not a TP/SL by checking it comes before those keywords
                tp_sl_pattern = r"(?:SL|TP|STOP|TARGET)"
                if re.search(tp_sl_pattern, text):
                    # Make sure price comes before SL/TP in text
                    price_pos = text.find(context_match.group(1))
                    sl_tp_match = re.search(tp_sl_pattern, text)
                    if sl_tp_match and price_pos < sl_tp_match.start():
                        return price
                else:
                    # No SL/TP mentioned, so this might be entry
                    return price

        return None

    # =========================
    # Stop Loss Extraction
    # =========================

    def _extract_stop_loss(self, text: str) -> Optional[float]:
        """Extract stop loss price"""
        sl_patterns = [
            r"(?:SL|STOP\s*LOSS|STOPLOSS)\s*[:=@]?\s*(\d+\.?\d*)",
            r"STOP\s*[:=@]?\s*(\d+\.?\d*)",
        ]
        
        for pattern in sl_patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        
        return None

    # =========================
    # Take Profit Extraction
    # =========================

    def _extract_take_profits(self, text: str) -> List[float]:
        """Extract all take profit levels"""
        # Pattern handles: TP1 1.0800, TP: 2062, TARGET 2060, etc.
        matches = re.findall(r"(?:TP\d*|TARGET\d*|TAKE\s*PROFIT\d*)\s*[:=@]?\s*(\d+\.?\d*)", text)
        tps = [float(m) for m in matches if m]
        return tps

    # =========================
    # Market Order Detection
    # =========================

    def _is_market_order(self, text: str) -> bool:
        """Check if message indicates market order intent"""
        return any(kw in text for kw in self.MARKET_KEYWORDS)

    # =========================
    # Price Validation
    # =========================

    def _validate_price_logic(self, symbol: str, direction: str, entry: float, sl: float) -> bool:
        """
        Validate that prices make logical sense.
        
        Checks:
        - Prices are positive
        - SL is on correct side of entry
        - Prices are within symbol bounds
        """
        # Basic sanity
        if entry <= 0 or sl <= 0:
            logger.error(f"Invalid prices: entry={entry}, sl={sl}")
            return False

        # Check SL is on correct side
        if direction == "buy" and sl >= entry:
            logger.error(f"BUY order has SL ({sl}) >= entry ({entry})")
            return False
        if direction == "sell" and sl <= entry:
            logger.error(f"SELL order has SL ({sl}) <= entry ({entry})")
            return False

        # Symbol-specific bounds
        config = self.SYMBOL_CONFIGS.get(symbol)
        if config:
            if not (config.min_price <= entry <= config.max_price):
                logger.error(f"{symbol} entry {entry} outside bounds [{config.min_price}, {config.max_price}]")
                return False
            if not (config.min_price <= sl <= config.max_price):
                logger.error(f"{symbol} SL {sl} outside bounds [{config.min_price}, {config.max_price}]")
                return False

        return True

    # =========================
    # Fallback Risk Logic
    # =========================

    def _fallback_risk(self, symbol: str, direction: str, entry: float) -> Tuple[Optional[float], List[float]]:
        """
        Calculate conservative SL/TP when not provided.
        
        Uses percentage-based risk with spread buffer.
        Ready for ATR upgrade (commented out).
        """
        config = self.SYMBOL_CONFIGS.get(symbol)
        if not config:
            logger.warning(f"No config found for {symbol}, cannot calculate fallback")
            return None, []

        # Future: ATR-based calculation
        # atr = self.get_atr(symbol)  # Not implemented yet
        # if atr:
        #     sl_dist = atr * 1.5
        #     tp_dist = atr * 3.0

        # Current: Percentage-based
        sl_dist = entry * config.sl_pct
        tp_dist = entry * config.tp_pct
        
        # Add spread buffer to SL (prevent immediate stop-out)
        spread_buffer = entry * config.typical_spread_pct

        if direction == "buy":
            sl = entry - sl_dist - spread_buffer
            tp = entry + tp_dist
        else:  # sell
            sl = entry + sl_dist + spread_buffer
            tp = entry - tp_dist

        return sl, [tp]

    # =========================
    # Confidence Scoring
    # =========================

    def _calculate_confidence(self, has_explicit_entry: bool, has_sl: bool, 
                             has_tp: bool, is_market: bool) -> float:
        """
        Calculate confidence score (0.0 to 1.0).
        
        Higher confidence = more explicit signal information
        Lower confidence = more assumptions made
        """
        score = 0.4  # Base confidence

        if has_explicit_entry:
            score += 0.2  # Explicit entry is good
        if has_sl:
            score += 0.2  # User-provided SL is better than fallback
        if has_tp:
            score += 0.15  # User-provided TP
        if is_market:
            score -= 0.05  # Market orders slightly riskier

        return min(1.0, max(0.0, score))

    # =========================
    # Risk/Reward Calculation
    # =========================

    def _calculate_rr_ratio(self, entry: float, sl: float, tp_list: List[float]) -> Optional[float]:
        """Calculate risk:reward ratio if TP provided"""
        if not tp_list:
            return None

        risk = abs(entry - sl)
        reward = abs(entry - tp_list[0])  # Use first TP
        
        if risk <= 0:
            return None
            
        return round(reward / risk, 2)


# =========================
# Example Integration
# =========================

def example_mt5_price_provider(symbol: str) -> float:
    """
    Example price provider for MT5.
    Replace this with your actual MT5 integration.
    """
    try:
        import MetaTrader5 as mt5
        
        if not mt5.initialize():
            raise Exception("MT5 initialization failed")
        
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise Exception(f"No tick data for {symbol}")
        
        # Use ask for buy, bid for sell (but parser doesn't know direction yet)
        # So we use mid-price or ask as default
        return tick.ask
        
    except Exception as e:
        logger.error(f"MT5 price provider error: {e}")
        raise


def example_mock_price_provider(symbol: str) -> float:
    """Mock price provider for testing without MT5"""
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


# =========================
# Usage Example
# =========================

if __name__ == "__main__":
    # Initialize parser with mock provider
    parser = SignalParser(price_provider=example_mock_price_provider)
    
    # Test cases
    test_messages = [
        "BUY XAUUSD @ 2050.50, SL: 2044.00, TP: 2062.00",
        "SELL NOW EURUSD",  # Market order, no SL/TP
        "GOLD LONG 2045-2050 SL 2040 TP1 2060 TP2 2070",
        "SHORT GBPUSD MARKET SL 1.2700",
    ]
    
    for msg in test_messages:
        print(f"\n{'='*60}")
        print(f"Input: {msg}")
        print(f"{'='*60}")
        
        result = parser.parse(msg)
        
        if result:
            print(f"✅ PARSED SUCCESSFULLY")
            print(f"Symbol:     {result['symbol']}")
            print(f"Direction:  {result['direction'].upper()}")
            print(f"Entry:      {result['entry']}")
            print(f"Stop Loss:  {result['stop_loss']}")
            print(f"Take Profit: {result['take_profit']}")
            print(f"Order Type: {result['order_type'].upper()}")
            print(f"Confidence: {result['confidence']:.1%}")
            print(f"R:R Ratio:  {result['metadata']['risk_reward_ratio']}")
            print(f"\nMetadata:")
            for key, val in result['metadata'].items():
                print(f"  {key}: {val}")
        else:
            print(f"❌ PARSING FAILED")
