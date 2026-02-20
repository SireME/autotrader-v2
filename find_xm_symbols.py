"""
MT5 Symbol Finder - Find the correct symbol names for your broker
"""
import MetaTrader5 as mt5

def find_symbols():
    """Find and display all available symbols in MT5"""
    
    # Initialize MT5
    if not mt5.initialize():
        print(f"MT5 initialization failed: {mt5.last_error()}")
        return
    
    print("=" * 60)
    print("MT5 Symbol Finder for XM Broker")
    print("=" * 60)
    
    # Get all symbols
    all_symbols = mt5.symbols_get()
    
    if not all_symbols:
        print("No symbols found!")
        mt5.shutdown()
        return
    
    print(f"\n✅ Found {len(all_symbols)} symbols\n")
    
    # Search for Gold/XAUUSD
    print("🔍 GOLD/XAUUSD SYMBOLS:")
    print("-" * 60)
    gold_symbols = [s for s in all_symbols if 'XAU' in s.name or 'GOLD' in s.name.upper()]
    if gold_symbols:
        for symbol in gold_symbols:
            print(f"  ✓ {symbol.name:<20} - {symbol.description}")
    else:
        print("  ❌ No gold symbols found")
    
    # Search for common forex pairs
    print("\n🔍 FOREX PAIRS:")
    print("-" * 60)
    forex_pairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD']
    for pair in forex_pairs:
        matching = [s for s in all_symbols if pair in s.name]
        if matching:
            for symbol in matching:
                print(f"  ✓ {symbol.name:<20} - {symbol.description}")
    
    # Search for indices
    print("\n🔍 INDICES:")
    print("-" * 60)
    indices_keywords = ['US30', 'SPX', 'NAS', 'DOW', 'SP500']
    index_symbols = []
    for s in all_symbols:
        if any(keyword in s.name.upper() for keyword in indices_keywords):
            index_symbols.append(s)
    
    if index_symbols:
        for symbol in index_symbols[:10]:  # Show first 10
            print(f"  ✓ {symbol.name:<20} - {symbol.description}")
    else:
        print("  ❌ No index symbols found")
    
    # Print all symbols to a file for reference
    print("\n📝 Saving complete symbol list to 'xm_symbols.txt'...")
    with open('xm_symbols.txt', 'w', encoding='utf-8') as f:
        f.write("Complete Symbol List for XM Broker\n")
        f.write("=" * 60 + "\n\n")
        for symbol in all_symbols:
            # Get more details
            info = mt5.symbol_info(symbol.name)
            if info:
                f.write(f"Symbol: {symbol.name:<20}\n")
                f.write(f"  Description: {symbol.description}\n")
                f.write(f"  Digits: {info.digits}\n")
                f.write(f"  Point: {info.point}\n")
                f.write(f"  Min Lot: {info.volume_min}\n")
                f.write(f"  Max Lot: {info.volume_max}\n")
                f.write(f"  Lot Step: {info.volume_step}\n")
                f.write(f"  Trade Mode: {info.trade_mode}\n")
                f.write("-" * 60 + "\n")
    
    print("✅ Complete list saved to 'xm_symbols.txt'")
    
    # Recommendations
    print("\n" + "=" * 60)
    print("📋 NEXT STEPS:")
    print("=" * 60)
    print("1. Look for your desired symbol in the output above")
    print("2. Note the EXACT symbol name (case-sensitive)")
    print("3. Update config/symbols.py with the correct mapping")
    print("\nExample:")
    print("  SYMBOL_ALIASES = {")
    print("      'XAUUSD': 'GOLD',      # If XM uses 'GOLD'")
    print("      'XAUUSD': 'XAUUSDm',   # Or if they use 'XAUUSDm'")
    print("  }")
    print("=" * 60)
    
    mt5.shutdown()

if __name__ == "__main__":
    find_symbols()
