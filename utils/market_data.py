import MetaTrader5 as mt5

def get_live_price(symbol: str) -> float:
    """
    Returns the current market price for a symbol.
    Uses ASK for buys and BID for sells (parser is direction-aware later).
    """
    tick = mt5.symbol_info_tick(symbol)

    if tick is None:
        raise RuntimeError(f"No market data for {symbol}")

    # Default to mid-price (safe generic)
    return (tick.ask + tick.bid) / 2

