"""
Symbol Configuration for XM Broker
"""

SYMBOL_ALIASES = {
    # GOLD - XM uses "GOLD" not "XAUUSD"
    "XAUUSD": "XAUUSD",
    "XAU": "XAUUSD",
    "GOLD": "XAUUSD",
    
    # SILVER
    "XAGUSD": "SILVER",
    "XAG": "SILVER",
    "SILVER": "SILVER",
    
    # Forex pairs (XM uses standard names)
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
    """Convert signal symbol to XM's actual symbol name"""
    signal_symbol = signal_symbol.upper().strip()
    return SYMBOL_ALIASES.get(signal_symbol, signal_symbol)
