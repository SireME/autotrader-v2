# Forex Auto-Trader Bot 🤖📈

A production-grade Telegram-to-MT5 auto-trading engine that parses
structured Gold signals, validates execution rules, enforces strict risk
management, and executes trades on MetaTrader 5 with configurable split
or single-order logic.

------------------------------------------------------------------------

## 🚀 Core Features

### 📡 Telegram Integration

-   Multi-channel listener support
-   Strict trigger-based signal detection (e.g., "Gold buy now")
-   Regex-only parser (AI optional but disabled by default)
-   Rejects ambiguous or non-trigger messages entirely

### 🧠 Signal Parsing Engine

-   Explicit BUY / SELL trigger gating
-   Entry range extraction (e.g., `5010 - 5007`)
-   SL/TP extraction with multiple formats supported
-   Automatic fallback SL/TP generation (3pt SL, 5/7/9pt TPs)
-   Confidence scoring
-   Anti-hallucination protections

### 📊 Execution Engine (MT5)

-   Market execution only (no pending orders)
-   Broker stop-distance enforcement
-   SL/TP staleness validation
-   Symbol mapping support
-   Automatic TP filtering if already passed
-   Filling mode auto-detection
-   Floating-point safe lot rounding

### ⚙️ Risk & Position Management

-   Configurable fixed lot sizing
-   Max lot safety cap
-   Max daily loss guard
-   Max open trades limit
-   Confidence threshold enforcement
-   Fallback signal blocking logic

### 🔀 TP Execution Modes (NEW)

Controlled via environment variable:

    SPLIT_TP_ORDERS=true   → Split position across all TP levels
    SPLIT_TP_ORDERS=false  → Single position using first TP only

-   In split mode: LOT_SIZE is total exposure split across TPs
-   In single mode: LOT_SIZE becomes full volume of one trade

### 🧮 Precision Handling

-   Step-safe lot rounding
-   Float precision protection (no 0.06 leakage from 0.07)
-   Broker volume_min and volume_step compliance

### 💾 Persistence

-   SQLite trade storage
-   Full metadata logging
-   Ticket tracking

------------------------------------------------------------------------

## 📦 Project Structure

    autotrader/
    ├── broker/
    │   ├── broker_interface.py
    │   └── mt5_connector.py
    ├── config/
    │   ├── settings.py
    │   └── symbols.py
    ├── core/
    │   ├── risk_manager.py
    │   ├── signal_parser.py
    │   ├── telegram_client.py
    │   └── trade_engine.py
    ├── utils/
    │   ├── market_data.py
    │   └── trade_repository.py
    ├── data/
    │   └── trades.db
    ├── main.py
    └── requirements.txt

------------------------------------------------------------------------

## 🛠 Installation

``` bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

------------------------------------------------------------------------

## ⚙️ Environment Configuration (.env)

Example production configuration:

``` env
# Telegram
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890
TELEGRAM_CHANNELS=@ChannelOne,@ChannelTwo

# Optional AI Parsing (disabled by default)
GROQ_API_KEY=gsk_xxx

# Risk & Execution
MAX_RISK_PER_TRADE=0.01
MAX_DAILY_LOSS=0.21
MAX_OPEN_TRADES=1
MIN_CONFIDENCE=0.6

LOT_SIZE=0.07
MAX_LOT_SIZE=0.21

# Anti-hallucination rules
MAX_PRICE_DEVIATION=0.05
MAX_ENTRY_DEVIATION_FOR_FALLBACK=0.10

# Execution mode
SPLIT_TP_ORDERS=false

# Symbol overrides
GOLD_SYMBOL=XAUUSD
SILVER_SYMBOL=SILVER

# Database
TRADES_DB_PATH=data/trades.db
```

------------------------------------------------------------------------

## ▶️ Running the Bot

Make sure: - MT5 terminal is open and logged in - Telegram session is
authenticated (first run requires OTP)

Then:

``` bash
python main.py
```

------------------------------------------------------------------------

## 🧠 Execution Philosophy

This engine enforces strict structural separation:

-   Parser defines signal structure.
-   Broker defines execution behavior.
-   Environment defines risk philosophy.

No AI hallucinations. No implicit assumptions. No silent lot leakage. No
invalid SL/TP execution.

------------------------------------------------------------------------

## ⚠️ Important Notes

-   Always test on demo before live deployment.
-   Verify broker volume_min and volume_step settings.
-   Ensure MT5 terminal remains running during execution.
-   Risk model depends on SPLIT_TP_ORDERS mode.

------------------------------------------------------------------------

## 📌 Summary

This bot is designed for deterministic execution with strict validation,
precision lot control, and configurable trade distribution logic.

It is not a signal guesser --- it is a structured execution engine.
