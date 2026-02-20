# Forex Auto-Trader Bot 🤖📈

Telegram-to-MT5 auto-trader that parses incoming signal messages, validates risk limits, and executes orders on MetaTrader 5.

## What is implemented

- Telegram listener with support for **multiple channels**.
- Signal parsing with regex + optional Groq AI parsing fallback.
- MT5 order execution with SL/TP sanity checks.
- Risk controls:
  - minimum confidence threshold,
  - max open trades,
  - max daily loss guard,
  - configurable risk-per-trade lot sizing,
  - lot caps (`LOT_SIZE`, `MAX_LOT_SIZE`).
- SQLite trade persistence in `data/trades.db`.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create `.env` in the project root:

```env
# Telegram
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890
TELEGRAM_CHANNELS=@ChannelOne,@ChannelTwo

# Optional AI parsing
GROQ_API_KEY=gsk_xxx

# Risk + execution
MAX_RISK_PER_TRADE=0.01
MAX_DAILY_LOSS=0.05
MAX_OPEN_TRADES=3
MIN_CONFIDENCE=0.6
LOT_SIZE=
MAX_LOT_SIZE=0.02

# Data
TRADES_DB_PATH=data/trades.db
DEBUG=true
```

Then run:

```bash
python main.py
```

## Project structure

```
autotrader/
├── broker/
│   ├── broker_interface.py
│   └── mt5_connector.py
├── config/
│   └── settings.py
├── core/
│   ├── risk_manager.py
│   ├── signal_parser.py
│   ├── telegram_client.py
│   └── trade_engine.py
├── data/
│   └── trades.db
├── utils/
│   ├── market_data.py
│   └── trade_repository.py
├── main.py
└── requirements.txt
```

## Notes

- Run MT5 terminal and keep it logged in before starting the bot.
- For first Telegram run, Telethon will prompt for OTP / 2FA.
- Start on demo first.
