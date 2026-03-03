"""
Symbol Configuration for XM Broker
Now supports environment-based overrides for GOLD and SILVER.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Load optional overrides from .env
ENV_GOLD_SYMBOL = os.getenv("GOLD_SYMBOL", "").strip()
ENV_SILVER_SYMBOL = os.getenv("SILVER_SYMBOL", "").strip()

# Fallback defaults (current behavior)
DEFAULT_GOLD_SYMBOL = "XAUUSD"
DEFAULT_SILVER_SYMBOL = "SILVER"

# Final resolved symbols (env override if provided, else default)
RESOLVED_GOLD_SYMBOL = ENV_GOLD_SYMBOL or DEFAULT_GOLD_SYMBOL
RESOLVED_SILVER_SYMBOL = ENV_SILVER_SYMBOL or DEFAULT_SILVER_SYMBOL


SYMBOL_ALIASES = {
    # GOLD
    "XAUUSD": RESOLVED_GOLD_SYMBOL,
    "XAU": RESOLVED_GOLD_SYMBOL,
    "GOLD": RESOLVED_GOLD_SYMBOL,
    
    # SILVER
    "XAGUSD": RESOLVED_SILVER_SYMBOL,
    "XAG": RESOLVED_SILVER_SYMBOL,
    "SILVER": RESOLVED_SILVER_SYMBOL,
    
    # Forex pairs
    "EURUSD": "EURUSD",
    "EU": "EURUSD",
    
    "GBPUSD": "GBPUSD",
    "GU": "GBPUSD",
    "CABLE": "GBPUSD",
    
    "USDJPY": "USDJPY",
    "UJ": "USDJPY",
    
    "AUDUSD": "AUDUSD",
    "AU": "AUDUSD",
    
    # Indices
    "US30": "US30Cash",
}


def get_broker_symbol(signal_symbol: str) -> str:
    """Convert signal symbol to broker's actual symbol name"""
    signal_symbol = signal_symbol.upper().strip()
    return SYMBOL_ALIASES.get(signal_symbol, signal_symbol)