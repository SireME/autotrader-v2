import os
import sqlite3
from datetime import datetime


class TradeRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT,
                    symbol TEXT,
                    direction TEXT,
                    entry_price REAL,
                    lot_size REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    ticket INTEGER,
                    status TEXT,
                    profit REAL
                )
                """
            )
            conn.commit()

    def insert_trade(self, signal: dict, ticket: int, status: str = "executed"):
        tp = signal["take_profit"][0] if signal.get("take_profit") else None
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO trades (
                    timestamp, symbol, direction, entry_price, lot_size,
                    stop_loss, take_profit, ticket, status, profit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.utcnow().isoformat(),
                    signal.get("symbol"),
                    signal.get("direction"),
                    signal.get("entry"),
                    signal.get("lot_size"),
                    signal.get("stop_loss"),
                    tp,
                    ticket,
                    status,
                    None,
                ),
            )
            conn.commit()
