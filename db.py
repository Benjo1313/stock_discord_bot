import os
import json
import aiosqlite
from config import DB_PATH, DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT UNIQUE NOT NULL,
    added_by TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signal_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    strength INTEGER NOT NULL,
    triggers TEXT,
    price REAL,
    volume REAL,
    rsi REAL,
    macd_hist REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    close REAL,
    high REAL,
    low REAL,
    volume REAL,
    change_pct REAL,
    signals_triggered INTEGER DEFAULT 0,
    UNIQUE(ticker, date)
);
"""


_MIGRATIONS = [
    # Add composite score columns (old rows get NULL)
    "ALTER TABLE signal_history ADD COLUMN fundamental_score INTEGER",
    "ALTER TABLE signal_history ADD COLUMN trend_score INTEGER",
    "ALTER TABLE signal_history ADD COLUMN technical_score INTEGER",
]


async def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript(SCHEMA)
        # Apply migrations idempotently
        for sql in _MIGRATIONS:
            try:
                await conn.execute(sql)
            except Exception:
                pass  # column already exists
        await conn.commit()


async def get_db():
    return await aiosqlite.connect(DB_PATH)


async def add_ticker(ticker: str, added_by: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        try:
            await conn.execute(
                "INSERT INTO watchlist (ticker, added_by) VALUES (?, ?)",
                (ticker.upper(), added_by),
            )
            await conn.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_ticker(ticker: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            "DELETE FROM watchlist WHERE ticker = ?", (ticker.upper(),)
        )
        await conn.commit()
        return cursor.rowcount > 0


async def get_watchlist() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        cursor = await conn.execute(
            "SELECT ticker, added_by, added_at FROM watchlist ORDER BY added_at"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def save_signal(
    ticker: str,
    signal_type: str,
    strength: int,
    triggers: list[str],
    price: float,
    volume: float,
    rsi: float | None,
    macd_hist: float | None,
    fundamental_score: int | None = None,
    trend_score: int | None = None,
    technical_score: int | None = None,
):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """INSERT INTO signal_history
               (ticker, signal_type, strength, triggers, price, volume, rsi, macd_hist,
                fundamental_score, trend_score, technical_score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ticker.upper(),
                signal_type,
                strength,
                json.dumps(triggers),
                price,
                volume,
                rsi,
                macd_hist,
                fundamental_score,
                trend_score,
                technical_score,
            ),
        )
        await conn.commit()


async def get_signals(ticker: str | None = None, limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        if ticker:
            cursor = await conn.execute(
                "SELECT * FROM signal_history WHERE ticker = ? ORDER BY created_at DESC LIMIT ?",
                (ticker.upper(), limit),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM signal_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def get_recent_signal(ticker: str, signal_type: str, hours: int = 2) -> bool:
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute(
            """SELECT id FROM signal_history
               WHERE ticker = ? AND signal_type = ?
               AND created_at > datetime('now', ?)""",
            (ticker.upper(), signal_type, f"-{hours} hours"),
        )
        row = await cursor.fetchone()
        return row is not None


async def save_daily_summary(
    ticker: str,
    date: str,
    open_: float,
    close: float,
    high: float,
    low: float,
    volume: float,
    change_pct: float,
    signals_triggered: int,
):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            """INSERT OR REPLACE INTO daily_summary
               (ticker, date, open, close, high, low, volume, change_pct, signals_triggered)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticker.upper(), date, open_, close, high, low, volume, change_pct, signals_triggered),
        )
        await conn.commit()
