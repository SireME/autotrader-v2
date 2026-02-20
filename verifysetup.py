"""
FIX FOR trade_engine.py
========================

The trade_engine.py is calling broker.place_trade() with the signal as-is,
but the signal contains "XAUUSD" while the broker needs "GOLD".

The broker's place_trade() already has symbol mapping, but the error message
suggests it's not being reached. Let's verify the broker is using the 
updated version.

SOLUTION:
---------
Make sure broker/mt5_connector.py has been replaced with the new mt5_broker.py
that includes symbol mapping at the start of place_trade().
"""

# Check if your broker/mt5_connector.py has this at the start of place_trade():

"""
def place_trade(self, trade):
    signal_symbol = trade["symbol"]
    
    # Map signal symbol to broker's actual symbol name
    symbol = get_broker_symbol(signal_symbol)
    
    if symbol != signal_symbol:
        print(f"🔄 Mapped signal symbol '{signal_symbol}' → broker symbol '{symbol}'")
    
    # ... rest of the code
"""

# If NOT, then your broker file wasn't updated. Replace it with:
# cp mt5_broker.py broker/mt5_connector.py

# The error "symbol_info() returned None for XAUUSD" means:
# 1. Either the broker file wasn't replaced
# 2. Or config/symbols.py doesn't exist
# 3. Or the import failed

# Let's add error handling to verify:

import os

def verify_setup():
    """Run this to verify your setup"""
    
    print("=" * 60)
    print("SETUP VERIFICATION")
    print("=" * 60)
    
    # Check 1: config/symbols.py exists
    if os.path.exists("config/symbols.py"):
        print("✅ config/symbols.py exists")
        try:
            from config.symbols import get_broker_symbol
            test_result = get_broker_symbol("XAUUSD")
            print(f"✅ Symbol mapping works: XAUUSD → {test_result}")
        except Exception as e:
            print(f"❌ Symbol mapping failed: {e}")
    else:
        print("❌ config/symbols.py NOT FOUND")
        print("   → Copy symbols.py to config/symbols.py")
    
    # Check 2: broker has symbol mapping
    print("\n" + "=" * 60)
    print("Checking broker/mt5_connector.py...")
    print("=" * 60)
    
    if os.path.exists("broker/mt5_connector.py"):
        with open("broker/mt5_connector.py", "r") as f:
            content = f.read()
            if "get_broker_symbol" in content:
                print("✅ Broker has symbol mapping")
            else:
                print("❌ Broker does NOT have symbol mapping")
                print("   → Replace broker/mt5_connector.py with mt5_broker.py")
            
            if "SYMBOL_FILLING_IOC" in content:
                print("❌ Broker has OLD filling mode constants (will cause error)")
                print("   → Replace broker/mt5_connector.py with mt5_broker.py")
            elif "ORDER_FILLING_FOK" in content or "filling_type & 1" in content:
                print("✅ Broker has correct filling mode constants")
    else:
        print("❌ broker/mt5_connector.py NOT FOUND")
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print("If you see any ❌ above, you need to:")
    print("1. Copy symbols.py → config/symbols.py")
    print("2. Copy mt5_broker.py → broker/mt5_connector.py")
    print("3. Restart your bot")
    print("=" * 60)

if __name__ == "__main__":
    verify_setup()
