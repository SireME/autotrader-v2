"""
Intent-Aware Trading Signal Parser - AI-Enhanced v2.1
======================================================

New in v2.1:
- Groq AI integration for intelligent signal parsing
- Automatic fallback to regex parser on AI failure
- Structured JSON output from AI
- Confidence boosting for AI-parsed signals
- Environment variable support for API key

AI is used when GROQ_API_KEY is detected in environment.
If AI fails, automatically falls back to regex-based parsing.

Author: Enhanced with AI capabilities
License: MIT
"""

import re
import os
import json
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
    Intent-aware Telegram signal parser with AI enhancement.
    
    Features:
    - Groq AI parsing for complex/ambiguous signals
    - Automatic fallback to regex parser
    - Market order detection with live price fetching
    - Automatic SL/TP calculation when missing
    - Price validation and sanity checks
    - Confidence scoring
    - Comprehensive error handling
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

    def __init__(self, price_provider: Callable[[str], float], groq_api_key: Optional[str] = None):
        """
        Initialize parser with price provider and optional Groq API key.
        
        Args:
            price_provider: Function that takes symbol (str) and returns current price (float)
            groq_api_key: Optional Groq API key. If None, checks GROQ_API_KEY env var.
                         If no key found, AI parsing is disabled.
        """
        self.price_provider = price_provider
        
        # AI Configuration
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY")
        self.ai_enabled = bool(self.groq_api_key)
        
        if self.ai_enabled:
            logger.info("✨ AI-enhanced parsing enabled (Groq)")
            self._init_groq_client()
        else:
            logger.info("📋 Regex-only parsing (no Groq API key found)")

    def _init_groq_client(self):
        """Initialize Groq client"""
        try:
            from groq import Groq
            self.groq_client = Groq(api_key=self.groq_api_key)
            logger.info("Groq client initialized successfully")
        except ImportError:
            logger.error("Groq package not installed. Run: pip install groq")
            self.ai_enabled = False
        except Exception as e:
            logger.error(f"Failed to initialize Groq client: {e}")
            self.ai_enabled = False

    # =========================
    # Public API
    # =========================

    def parse(self, message: str, use_ai: bool = True) -> Optional[Dict]:
        """
        Parse a trading signal message.
        
        Args:
            message: Raw message text from Telegram or other source
            use_ai: Whether to attempt AI parsing first (default: True)
            
        Returns:
            Dictionary with signal details or None if parsing failed
        """
        if not message or len(message.strip()) < 5:
            logger.debug("Message too short or empty")
            return None

        # Try AI parsing first if enabled
        if self.ai_enabled and use_ai:
            try:
                logger.info("🤖 Attempting AI parsing...")
                result = self._parse_with_ai(message)
                if result:
                    logger.info("✅ AI parsing successful")
                    result['metadata']['parsing_method'] = 'ai'
                    # Boost confidence for AI-parsed signals
                    result['confidence'] = min(1.0, result['confidence'] + 0.1)
                    return result
                else:
                    logger.warning("AI parsing returned None, falling back to regex")
            except Exception as e:
                logger.warning(f"AI parsing failed: {e}, falling back to regex")
        
        # Fallback to regex parsing
        logger.info("📋 Using regex parsing")
        result = self._parse_with_regex(message)
        if result:
            result['metadata']['parsing_method'] = 'regex'
        return result

    # =========================
    # AI Parsing
    # =========================

    def _parse_with_ai(self, message: str) -> Optional[Dict]:
        """
        Use Groq AI to parse trading signal.
        Returns structured data or None on failure.
        """
        
        # Create prompt for AI
        prompt = self._create_ai_prompt(message)
        
        try:
            # Call Groq API
            response = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",  # Fast and accurate
                messages=[
                    {
                        "role": "system",
                        "content": """You are an expert trading signal parser. Extract trading information from messages and return ONLY valid JSON.

Your task:
1. Extract: symbol, direction (buy/sell), entry price, stop loss, take profit(s), order type
2. Return as JSON object
3. If information is missing, use null
4. Validate prices are reasonable
5. Return ONLY the JSON, no other text

JSON format:
{
    "symbol": "XAUUSD",
    "direction": "buy",
    "entry": 2050.50,
    "stop_loss": 2044.00,
    "take_profit": [2062.00],
    "order_type": "limit",
    "is_market_order": false
}"""
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.1,  # Low temperature for consistency
                max_tokens=500,
                response_format={"type": "json_object"}  # Ensure JSON output
            )
            
            # Extract JSON from response
            ai_output = response.choices[0].message.content
            logger.debug(f"AI output: {ai_output}")
            
            # Parse AI response
            parsed_data = json.loads(ai_output)
            
            # Convert AI output to parser format
            return self._process_ai_output(parsed_data, message)
            
        except Exception as e:
            logger.error(f"AI parsing error: {e}")
            return None

    def _create_ai_prompt(self, message: str) -> str:
        """Create prompt for AI parsing"""
        return f"""Parse this trading signal and extract the trading information:

Message:
{message}

Supported symbols: {', '.join(self.SYMBOL_CONFIGS.keys())}

Return JSON with:
- symbol: trading symbol (must be one of the supported symbols)
- direction: "buy" or "sell"
- entry: entry price (number or null if market order)
- stop_loss: stop loss price (number or null)
- take_profit: array of take profit prices (can be empty)
- order_type: "market" or "limit"
- is_market_order: true/false

If the message contains "NOW" or "MARKET", it's a market order (entry can be null).
If symbol is not in supported list, try to match aliases (e.g., GOLD->XAUUSD, EU->EURUSD).
"""

    def _process_ai_output(self, ai_data: Dict, original_message: str) -> Optional[Dict]:
        """
        Process AI output and apply validation/fallback logic.
        """
        try:
            # Extract fields
            symbol = ai_data.get('symbol')
            direction = ai_data.get('direction', '').lower()
            entry = ai_data.get('entry')
            stop_loss = ai_data.get('stop_loss')
            take_profit = ai_data.get('take_profit', [])
            is_market = ai_data.get('is_market_order', False)
            
            # Validate symbol
            if symbol not in self.SYMBOL_CONFIGS:
                # Try to map aliases
                symbol = self._map_symbol_alias(symbol)
                if not symbol:
                    logger.warning(f"AI returned unsupported symbol: {ai_data.get('symbol')}")
                    return None
            
            # Validate direction
            if direction not in ['buy', 'sell']:
                logger.warning(f"AI returned invalid direction: {direction}")
                return None
            
            # Track what was auto-generated
            used_market_price = False
            used_fallback_sl = False
            
            # Handle market orders
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
            
            # Apply fallback SL/TP if needed
            if entry and stop_loss is None:
                stop_loss, take_profit = self._fallback_risk(
                    symbol=symbol,
                    direction=direction,
                    entry=entry
                )
                used_fallback_sl = True
                logger.info(f"Applied fallback SL/TP: SL={stop_loss}, TP={take_profit}")
            
            # Validate we have minimum required data
            if entry is None or stop_loss is None:
                logger.warning("Missing entry or stop loss after AI processing")
                return None
            
            # Validate price logic
            if not self._validate_price_logic(symbol, direction, entry, stop_loss):
                logger.error("AI output failed price validation")
                return None
            
            # Calculate confidence
            confidence = self._calculate_confidence(
                has_explicit_entry=not used_market_price,
                has_sl=not used_fallback_sl,
                has_tp=bool(take_profit) and not used_fallback_sl,
                is_market=is_market
            )
            
            return {
                "symbol": symbol,
                "direction": direction,
                "entry": round(entry, 5),
                "stop_loss": round(stop_loss, 5),
                "take_profit": [round(tp, 5) for tp in (take_profit if isinstance(take_profit, list) else [take_profit])] if take_profit else [],
                "order_type": "market" if is_market else "limit",
                "confidence": confidence,
                "raw": original_message,
                "metadata": {
                    "used_market_price": used_market_price,
                    "used_fallback_sl": used_fallback_sl,
                    "timestamp": datetime.utcnow().isoformat(),
                    "risk_reward_ratio": self._calculate_rr_ratio(entry, stop_loss, take_profit if isinstance(take_profit, list) else [take_profit] if take_profit else []),
                    "ai_confidence": ai_data.get('confidence', 'N/A')
                }
            }
            
        except Exception as e:
            logger.error(f"Error processing AI output: {e}")
            return None

    def _map_symbol_alias(self, symbol: str) -> Optional[str]:
        """Map AI-returned symbol to canonical symbol"""
        if not symbol:
            return None
        
        symbol = symbol.upper()
        
        # Direct match
        if symbol in self.SYMBOL_CONFIGS:
            return symbol
        
        # Check aliases
        for canonical_symbol, config in self.SYMBOL_CONFIGS.items():
            if symbol in config.aliases:
                return canonical_symbol
        
        return None

    # =========================
    # Regex Parsing (Fallback)
    # =========================

    def _parse_with_regex(self, message: str) -> Optional[Dict]:
        """
        Original regex-based parsing logic.
        This is the fallback when AI fails or is disabled.
        """
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

        # Market order handling
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

        # Fallback strategy
        if entry and stop_loss is None:
            stop_loss, take_profit = self._fallback_risk(
                symbol=symbol,
                direction=direction,
                entry=entry
            )
            used_fallback_sl = True
            logger.info(f"Applied fallback SL/TP: SL={stop_loss}, TP={take_profit}")

        # Validation gate
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
    # Regex Helper Methods
    # =========================

    def _normalize(self, text: str) -> str:
        """Normalize text while preserving important characters"""
        text = text.upper()
        # First remove commas from numbers (1,850.50 -> 1850.50)
        text = re.sub(r"(\d),(\d)", r"\1\2", text)
        # Keep: alphanumeric, whitespace, dots, dashes, @, slashes, parens
        text = re.sub(r"[^\w\s.\-@/()\[\]]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return f" {text.strip()} "

    def _detect_direction(self, text: str) -> Optional[str]:
        """Detect trade direction from keywords"""
        buy_hits = sum(1 for kw in self.BUY_KEYWORDS if re.search(rf"\b{kw}\b", text))
        sell_hits = sum(1 for kw in self.SELL_KEYWORDS if re.search(rf"\b{kw}\b", text))

        if buy_hits and sell_hits:
            return "buy" if buy_hits > sell_hits else "sell"
        if buy_hits:
            return "buy"
        if sell_hits:
            return "sell"
        return None

    def _detect_symbol(self, text: str) -> Optional[str]:
        """Detect trading symbol from aliases"""
        for symbol, config in self.SYMBOL_CONFIGS.items():
            for alias in config.aliases:
                if re.search(rf"\b{alias}\b", text):
                    return symbol
        return None

    def _extract_entry(self, text: str) -> Optional[float]:
        """Extract entry price with improved pattern matching"""
        # Priority 1: Explicit entry markers with colon or @
        entry_patterns = [
            r"(?:ENTRY|ENTER|PRICE)\s*[:=@]\s*(\d+\.?\d*)",
            r"@\s*(\d+\.?\d*)",
        ]
        
        for pattern in entry_patterns:
            match = re.search(pattern, text)
            if match:
                price = float(match.group(1))
                if price > 0:
                    return price

        # Priority 2: Entry zones (range)
        range_pattern = r"(?:ENTRY|ZONE|PRICE|@)?\s*(\d+\.?\d*)\s*[-–TO]\s*(\d+\.?\d*)"
        range_match = re.search(range_pattern, text)
        
        if range_match:
            low = float(range_match.group(1))
            high = float(range_match.group(2))
            if low > 0 and high > low and (high - low) / low < 0.1:
                return (low + high) / 2
        
        # Priority 3: Entry word followed by price
        loose_entry = re.search(r"(?:ENTRY|ENTER)\s+(\d+\.?\d*)", text)
        if loose_entry:
            price = float(loose_entry.group(1))
            if price > 0:
                return price
        
        # Priority 4: Price after direction
        context_pattern = r"(?:BUY|SELL|LONG|SHORT)\s+(\d+\.?\d*)"
        context_match = re.search(context_pattern, text)
        if context_match:
            price = float(context_match.group(1))
            if price > 0:
                tp_sl_pattern = r"(?:SL|TP|STOP|TARGET)"
                if re.search(tp_sl_pattern, text):
                    price_pos = text.find(context_match.group(1))
                    sl_tp_match = re.search(tp_sl_pattern, text)
                    if sl_tp_match and price_pos < sl_tp_match.start():
                        return price
                else:
                    return price

        return None

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

    def _extract_take_profits(self, text: str) -> List[float]:
        """Extract all take profit levels"""
        matches = re.findall(r"(?:TP\d*|TARGET\d*|TAKE\s*PROFIT\d*)\s*[:=@]?\s*(\d+\.?\d*)", text)
        tps = [float(m) for m in matches if m]
        return tps

    def _is_market_order(self, text: str) -> bool:
        """Check if message indicates market order intent"""
        return any(kw in text for kw in self.MARKET_KEYWORDS)

    # =========================
    # Validation
    # =========================

    def _validate_price_logic(self, symbol: str, direction: str, entry: float, sl: float) -> bool:
        """Validate that prices make logical sense"""
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

    def _fallback_risk(self, symbol: str, direction: str, entry: float) -> Tuple[Optional[float], List[float]]:
        """Calculate conservative SL/TP when not provided"""
        config = self.SYMBOL_CONFIGS.get(symbol)
        if not config:
            logger.warning(f"No config found for {symbol}, cannot calculate fallback")
            return None, []

        sl_dist = entry * config.sl_pct
        tp_dist = entry * config.tp_pct
        spread_buffer = entry * config.typical_spread_pct

        if direction == "buy":
            sl = entry - sl_dist - spread_buffer
            tp = entry + tp_dist
        else:
            sl = entry + sl_dist + spread_buffer
            tp = entry - tp_dist

        return sl, [tp]

    def _calculate_confidence(self, has_explicit_entry: bool, has_sl: bool, 
                             has_tp: bool, is_market: bool) -> float:
        """Calculate confidence score (0.0 to 1.0)"""
        score = 0.4
        if has_explicit_entry:
            score += 0.2
        if has_sl:
            score += 0.2
        if has_tp:
            score += 0.15
        if is_market:
            score -= 0.05
        return min(1.0, max(0.0, score))

    def _calculate_rr_ratio(self, entry: float, sl: float, tp_list: List[float]) -> Optional[float]:
        """Calculate risk:reward ratio if TP provided"""
        if not tp_list:
            return None
        risk = abs(entry - sl)
        reward = abs(entry - tp_list[0])
        if risk <= 0:
            return None
        return round(reward / risk, 2)


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
    
    test_signal = """
    📊 GOLD Signal Alert! 🚀
    
    I'm seeing a strong bullish setup on XAUUSD.
    Looking to enter around 2050-2051 area.
    Stop below 2044 to manage risk.
    First target is 2062, second at 2070.
    """
    
    result = parser_ai.parse(test_signal)
    
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
