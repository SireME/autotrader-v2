import asyncio
import nest_asyncio
from broker.mt5_connector import MT5Broker
from config.settings import DEBUG, RISK_SETTINGS, TRADES_DB_PATH
from config.symbols import get_broker_symbol
from core.risk_manager import RiskManager
from core.signal_parser import SignalParser
from core.telegram_client import TelegramSignalClient
from core.trade_engine import TradeEngine
from utils.trade_repository import TradeRepository
from breakeven_manager import BreakevenManager
import MetaTrader5 as mt5

nest_asyncio.apply()


def get_live_price(symbol: str) -> float:
    """Fetch live price from MT5 with symbol mapping."""
    broker_symbol = get_broker_symbol(symbol)
    if broker_symbol != symbol:
        print(f"🔄 Price mapping: '{symbol}' → '{broker_symbol}'")
    if not mt5.initialize():
        raise RuntimeError("MT5 not initialized")
    if not mt5.symbol_select(broker_symbol, True):
        raise RuntimeError(f"Symbol not available: {broker_symbol}")
    tick = mt5.symbol_info_tick(broker_symbol)
    if tick is None:
        raise RuntimeError(f"No market data for {broker_symbol}")
    return tick.ask


print("🔄 Connecting to MT5 …")
broker = MT5Broker()
broker.connect()

risk_manager = RiskManager(
    balance=224,
    risk_per_trade=RISK_SETTINGS["max_risk_per_trade"],
    max_daily_loss=RISK_SETTINGS["max_daily_loss"],
    max_open_trades=RISK_SETTINGS["max_open_trades"],
)

trade_repository = TradeRepository(TRADES_DB_PATH)
engine = TradeEngine(broker, risk_manager, trade_repository=trade_repository)
parser = SignalParser(price_provider=get_live_price)


async def on_signal(raw_text: str):
    try:
        signal = parser.parse(raw_text)
        if signal is None:
            if DEBUG:
                print("🔍 Message didn't match signal format — skipped.")
            return
        if DEBUG:
            print(f"📊 Parsed signal: {signal}")
        engine.process_signal(signal)
    except Exception as exc:
        print(f"⚠️  Signal processing error: {exc}")


async def async_main():
    bm = BreakevenManager()
    # Hold a reference to the task so it isn't silently garbage collected.
    bm_task = asyncio.create_task(bm.run())

    try:
        client = TelegramSignalClient(on_signal)
        await client.start()
    finally:
        # Graceful shutdown: stop the manager loop and await task completion.
        bm.stop()
        await bm_task


if __name__ == "__main__":
    asyncio.run(async_main())