import MetaTrader5 as mt5

mt5.initialize()

for s in mt5.symbols_get():
    if "XAU" in s.name.upper() or "GOLD" in s.name.upper():
        print(s.name)

