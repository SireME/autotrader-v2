import os
from dotenv import load_dotenv

load_dotenv()


def _to_float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


TELEGRAM_API_ID = _to_int(os.getenv("TELEGRAM_API_ID"), 0)
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")

TELEGRAM_CHANNELS = [
    c.strip()
    for c in os.getenv("TELEGRAM_CHANNELS", "").split(",")
    if c.strip()
]

BROKER = os.getenv("BROKER", "mt5")
MT5_LOGIN = _to_int(os.getenv("MT5_LOGIN"), 0)
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")

RISK_SETTINGS = {
    "max_risk_per_trade": _to_float(os.getenv("MAX_RISK_PER_TRADE"), 0.07),
    "max_daily_loss": _to_float(os.getenv("MAX_DAILY_LOSS"), 0.2),
    "max_open_trades": _to_int(os.getenv("MAX_OPEN_TRADES"), 1),
}

MIN_CONFIDENCE = _to_float(os.getenv("MIN_CONFIDENCE"), 0.6)
LOT_SIZE = os.getenv("LOT_SIZE")
LOT_SIZE = _to_float(LOT_SIZE, 0.0) if LOT_SIZE else None
MAX_LOT_SIZE = _to_float(os.getenv("MAX_LOT_SIZE"), 0.07)

DATA_DIR = os.getenv("DATA_DIR", "data")
TRADES_DB_PATH = os.getenv("TRADES_DB_PATH", os.path.join(DATA_DIR, "trades.db"))

DEBUG = os.getenv("DEBUG", "true").lower() == "true"
