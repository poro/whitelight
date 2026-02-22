"""SQLite database for tracking discovered strategies and backtest results."""

from __future__ import annotations

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "data/strategies.db"


class StrategyDB:
    """Manage the strategy research database."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,          -- tradingview, reddit, discord
                source_url TEXT,
                name TEXT NOT NULL,
                author TEXT,
                description TEXT,
                category TEXT,
                rating REAL,
                pine_script TEXT,
                python_code TEXT,
                status TEXT DEFAULT 'discovered',  -- discovered, extracted, converted, tested, failed
                error_message TEXT,
                metadata_json TEXT,
                discovered_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS backtest_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id INTEGER NOT NULL,
                ticker TEXT DEFAULT 'TQQQ',
                start_date TEXT,
                end_date TEXT,
                initial_capital REAL DEFAULT 100000,
                final_value REAL,
                total_return REAL,
                annual_return REAL,
                max_drawdown REAL,
                sharpe_ratio REAL,
                sortino_ratio REAL,
                calmar_ratio REAL,
                profit_factor REAL,
                win_rate REAL,
                total_trades INTEGER,
                avg_trade_duration REAL,
                trade_frequency REAL,       -- trades per year
                composite_score REAL,
                ran_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (strategy_id) REFERENCES strategies(id)
            );

            CREATE INDEX IF NOT EXISTS idx_strategies_status ON strategies(status);
            CREATE INDEX IF NOT EXISTS idx_strategies_source ON strategies(source);
            CREATE INDEX IF NOT EXISTS idx_backtest_score ON backtest_results(composite_score DESC);
        """)
        self._conn.commit()

    def add_strategy(
        self,
        source: str,
        name: str,
        author: str = "",
        description: str = "",
        category: str = "",
        rating: float = 0.0,
        source_url: str = "",
        pine_script: str = "",
        metadata: dict | None = None,
    ) -> int:
        """Insert a discovered strategy. Returns the row id."""
        cur = self._conn.execute(
            """INSERT INTO strategies
               (source, source_url, name, author, description, category, rating, pine_script, metadata_json, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (source, source_url, name, author, description, category, rating,
             pine_script, json.dumps(metadata or {}), "discovered" if not pine_script else "extracted"),
        )
        self._conn.commit()
        logger.info("Added strategy #%d: %s (%s)", cur.lastrowid, name, source)
        return cur.lastrowid

    def update_status(self, strategy_id: int, status: str, error: str = "") -> None:
        self._conn.execute(
            "UPDATE strategies SET status=?, error_message=?, updated_at=datetime('now') WHERE id=?",
            (status, error, strategy_id),
        )
        self._conn.commit()

    def update_pine_script(self, strategy_id: int, pine_script: str) -> None:
        self._conn.execute(
            "UPDATE strategies SET pine_script=?, status='extracted', updated_at=datetime('now') WHERE id=?",
            (pine_script, strategy_id),
        )
        self._conn.commit()

    def update_python_code(self, strategy_id: int, python_code: str) -> None:
        self._conn.execute(
            "UPDATE strategies SET python_code=?, status='converted', updated_at=datetime('now') WHERE id=?",
            (python_code, strategy_id),
        )
        self._conn.commit()

    def add_backtest_result(self, strategy_id: int, result: dict) -> int:
        cur = self._conn.execute(
            """INSERT INTO backtest_results
               (strategy_id, ticker, start_date, end_date, initial_capital, final_value,
                total_return, annual_return, max_drawdown, sharpe_ratio, sortino_ratio,
                calmar_ratio, profit_factor, win_rate, total_trades, avg_trade_duration,
                trade_frequency, composite_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (strategy_id, result.get("ticker", "TQQQ"),
             result.get("start_date"), result.get("end_date"),
             result.get("initial_capital", 100000), result.get("final_value"),
             result.get("total_return"), result.get("annual_return"),
             result.get("max_drawdown"), result.get("sharpe_ratio"),
             result.get("sortino_ratio"), result.get("calmar_ratio"),
             result.get("profit_factor"), result.get("win_rate"),
             result.get("total_trades"), result.get("avg_trade_duration"),
             result.get("trade_frequency"), result.get("composite_score")),
        )
        self._conn.execute(
            "UPDATE strategies SET status='tested', updated_at=datetime('now') WHERE id=?",
            (strategy_id,),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_strategies(self, status: str | None = None, limit: int = 100) -> list[dict]:
        query = "SELECT * FROM strategies"
        params = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY discovered_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_top_strategies(self, limit: int = 20) -> list[dict]:
        """Get strategies ranked by composite backtest score."""
        rows = self._conn.execute("""
            SELECT s.*, b.composite_score, b.sharpe_ratio, b.calmar_ratio,
                   b.max_drawdown, b.profit_factor, b.annual_return, b.total_trades
            FROM strategies s
            JOIN backtest_results b ON s.id = b.strategy_id
            WHERE s.status = 'tested'
            ORDER BY b.composite_score DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def strategy_exists(self, source_url: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM strategies WHERE source_url=?", (source_url,)
        ).fetchone()
        return row is not None

    def close(self) -> None:
        self._conn.close()
