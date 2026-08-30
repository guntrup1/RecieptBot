"""
Database layer — works with PostgreSQL (asyncpg) on production,
and falls back to SQLite (aiosqlite) if DATABASE_URL is not set (local dev).
"""
from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

# ─── Backend selection ────────────────────────────────────────────────────────

USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import asyncpg
    logger.info("Database: PostgreSQL (Supabase)")
else:
    import aiosqlite
    from bot.config import DB_PATH
    logger.info("Database: SQLite (local)")

# ─── Schema ───────────────────────────────────────────────────────────────────

SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS monthly_budget (
    id           SERIAL PRIMARY KEY,
    month        TEXT    NOT NULL UNIQUE,
    total_budget REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS receipts (
    id            SERIAL PRIMARY KEY,
    date          TEXT,
    store         TEXT,
    total_amount  REAL    DEFAULT 0,
    photo_file_id TEXT,
    report_text   TEXT,
    month         TEXT,
    created_at    TIMESTAMP DEFAULT NOW(),
    receipt_hash  TEXT
);

CREATE TABLE IF NOT EXISTS receipt_items (
    id         SERIAL PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    name       TEXT,
    quantity   REAL    DEFAULT 1,
    price      REAL    DEFAULT 0
);

CREATE TABLE IF NOT EXISTS personal_expenses (
    id          SERIAL PRIMARY KEY,
    receipt_id  INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    person_name TEXT,
    item_name   TEXT,
    amount      REAL    DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS debt_ledger (
    id               SERIAL PRIMARY KEY,
    person_name      TEXT NOT NULL,
    amount           REAL NOT NULL,
    transaction_type TEXT NOT NULL,
    description      TEXT,
    month            TEXT NOT NULL,
    created_at       TIMESTAMP DEFAULT NOW(),
    receipt_id       INTEGER REFERENCES receipts(id) ON DELETE SET NULL
);
"""

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS monthly_budget (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    month        TEXT    NOT NULL UNIQUE,
    total_budget REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS receipts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          TEXT,
    store         TEXT,
    total_amount  REAL    DEFAULT 0,
    photo_file_id TEXT,
    report_text   TEXT,
    month         TEXT,
    created_at    TEXT    DEFAULT (datetime('now')),
    receipt_hash  TEXT
);

CREATE TABLE IF NOT EXISTS receipt_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id INTEGER NOT NULL,
    name       TEXT,
    quantity   REAL    DEFAULT 1,
    price      REAL    DEFAULT 0,
    FOREIGN KEY (receipt_id) REFERENCES receipts (id)
);

CREATE TABLE IF NOT EXISTS personal_expenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id  INTEGER NOT NULL,
    person_name TEXT,
    item_name   TEXT,
    amount      REAL    DEFAULT 0,
    FOREIGN KEY (receipt_id) REFERENCES receipts (id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS debt_ledger (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    person_name      TEXT NOT NULL,
    amount           REAL NOT NULL,
    transaction_type TEXT NOT NULL,
    description      TEXT,
    month            TEXT NOT NULL,
    created_at       TEXT DEFAULT (datetime('now')),
    receipt_id       INTEGER,
    FOREIGN KEY (receipt_id) REFERENCES receipts (id) ON DELETE SET NULL
);
"""

# ─── Connection pool (Postgres) ───────────────────────────────────────────────

_pg_pool = None

async def _get_pool():
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pg_pool

# ─── Init ─────────────────────────────────────────────────────────────────────

async def init_db() -> None:
    if USE_POSTGRES:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(SCHEMA_PG)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.executescript(SCHEMA_SQLITE)
            try:
                await db.execute("ALTER TABLE receipts ADD COLUMN receipt_hash TEXT")
            except Exception:
                pass
            await db.commit()

# ─── Low-level helpers ────────────────────────────────────────────────────────

async def _fetchone(query: str, *args):
    if USE_POSTGRES:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchrow(_pg_query(query), *args)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(query, args) as cur:
                return await cur.fetchone()

async def _fetchall(query: str, *args):
    if USE_POSTGRES:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            return await conn.fetch(_pg_query(query), *args)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(query, args) as cur:
                return await cur.fetchall()

async def _execute(query: str, *args):
    if USE_POSTGRES:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(_pg_query(query), *args)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(query, args)
            await db.commit()

async def _execute_returning_id(query: str, *args) -> int:
    if USE_POSTGRES:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(_pg_query(query) + " RETURNING id", *args)
            return row["id"]
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(query, args)
            await db.commit()
            return cur.lastrowid

def _pg_query(q: str) -> str:
    """Convert SQLite ? placeholders to PostgreSQL $1, $2, ... style."""
    i = 0
    result = []
    for ch in q:
        if ch == "?":
            i += 1
            result.append(f"${i}")
        else:
            result.append(ch)
    return "".join(result)

# ─── Settings ─────────────────────────────────────────────────────────────────

async def get_setting(key: str) -> str | None:
    row = await _fetchone("SELECT value FROM settings WHERE key = ?", key)
    return row[0] if row else None

async def set_setting(key: str, value: str) -> None:
    if USE_POSTGRES:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value",
                key, value,
            )
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            await db.commit()

# ─── Budget ───────────────────────────────────────────────────────────────────

async def get_budget(month: str) -> float:
    row = await _fetchone("SELECT total_budget FROM monthly_budget WHERE month = ?", month)
    return float(row[0]) if row else 0.0

async def set_budget(month: str, amount: float) -> None:
    if USE_POSTGRES:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO monthly_budget (month, total_budget) VALUES ($1, $2) ON CONFLICT(month) DO UPDATE SET total_budget = EXCLUDED.total_budget",
                month, amount,
            )
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO monthly_budget (month, total_budget) VALUES (?, ?) ON CONFLICT(month) DO UPDATE SET total_budget = excluded.total_budget",
                (month, amount),
            )
            await db.commit()

async def get_month_spent(month: str) -> float:
    row = await _fetchone("SELECT COALESCE(SUM(total_amount), 0) FROM receipts WHERE month = ?", month)
    return float(row[0]) if row else 0.0

# ─── Receipts ─────────────────────────────────────────────────────────────────

async def receipt_exists(receipt_hash: str) -> bool:
    if not receipt_hash or receipt_hash in ("unknown", ""):
        return False
    row = await _fetchone("SELECT 1 FROM receipts WHERE receipt_hash = ?", receipt_hash)
    return row is not None

async def save_receipt(
    date: str | None,
    store: str | None,
    total_amount: float,
    photo_file_id: str,
    report_text: str,
    month: str,
    receipt_hash: str = "",
) -> int:
    return await _execute_returning_id(
        "INSERT INTO receipts (date, store, total_amount, photo_file_id, report_text, month, receipt_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
        date, store, total_amount, photo_file_id, report_text, month, receipt_hash,
    )

async def save_receipt_items(receipt_id: int, items: list[dict]) -> None:
    if USE_POSTGRES:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            for item in items:
                await conn.execute(
                    "INSERT INTO receipt_items (receipt_id, name, quantity, price) VALUES ($1, $2, $3, $4)",
                    receipt_id, item.get("name", ""), item.get("quantity", 1), item.get("price", 0),
                )
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            for item in items:
                await db.execute(
                    "INSERT INTO receipt_items (receipt_id, name, quantity, price) VALUES (?, ?, ?, ?)",
                    (receipt_id, item.get("name", ""), item.get("quantity", 1), item.get("price", 0)),
                )
            await db.commit()

async def save_personal_expenses(receipt_id: int, expenses: list[dict], month: str) -> None:
    if USE_POSTGRES:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            for exp in expenses:
                person = exp.get("person", "")
                item_name = exp.get("item", "")
                amount = float(exp.get("amount", 0))
                # 1. Save to personal_expenses
                await conn.execute(
                    "INSERT INTO personal_expenses (receipt_id, person_name, item_name, amount) VALUES ($1, $2, $3, $4)",
                    receipt_id, person, item_name, amount,
                )
                # 2. Add to debt_ledger
                await conn.execute(
                    "INSERT INTO debt_ledger (person_name, amount, transaction_type, description, month, receipt_id) VALUES ($1, $2, $3, $4, $5, $6)",
                    person, amount, "expense", f"Покупка: {item_name}", month, receipt_id
                )
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            for exp in expenses:
                person = exp.get("person", "")
                item_name = exp.get("item", "")
                amount = float(exp.get("amount", 0))
                await db.execute(
                    "INSERT INTO personal_expenses (receipt_id, person_name, item_name, amount) VALUES (?, ?, ?, ?)",
                    (receipt_id, person, item_name, amount),
                )
                await db.execute(
                    "INSERT INTO debt_ledger (person_name, amount, transaction_type, description, month, receipt_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (person, amount, "expense", f"Покупка: {item_name}", month, receipt_id),
                )
            await db.commit()

# ─── Debts & Ledger ───────────────────────────────────────────────────────────

async def add_debt_repayment(person_name: str, amount: float, month: str, description: str = "Погашение долга") -> None:
    """Adds a repayment entry (negative amount) to the ledger."""
    await _execute(
        "INSERT INTO debt_ledger (person_name, amount, transaction_type, description, month) VALUES (?, ?, ?, ?, ?)",
        person_name, -amount, "repayment", description, month
    )

async def delete_ledger_entry(entry_id: int) -> None:
    await _execute("DELETE FROM debt_ledger WHERE id = ?", entry_id)

async def get_debts_for_month(month: str) -> dict[str, float]:
    """Returns a dict of {person_name: total_debt} for the given month."""
    rows = await _fetchall(
        "SELECT person_name, SUM(amount) FROM debt_ledger WHERE month = ? GROUP BY person_name",
        month
    )
    return {row[0]: float(row[1]) for row in rows}

async def get_debt_history(month: str, limit: int = 15) -> list[tuple]:
    """Returns recent ledger entries for the month."""
    rows = await _fetchall(
        "SELECT id, person_name, amount, transaction_type, description, created_at FROM debt_ledger WHERE month = ? ORDER BY created_at DESC LIMIT ?",
        month, limit
    )
    return [tuple(r) for r in rows]

# ─── Cleanup ──────────────────────────────────────────────────────────────────

async def cleanup_old_data() -> int:
    """Clears photo_file_id from receipts older than 2 months, keeping the text data."""
    if USE_POSTGRES:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            res = await conn.execute("UPDATE receipts SET photo_file_id = NULL WHERE created_at < NOW() - INTERVAL '2 months' AND photo_file_id IS NOT NULL")
            return int(res.split()[1]) if res.startswith("UPDATE") else 0
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("UPDATE receipts SET photo_file_id = NULL WHERE created_at < date('now', '-2 months') AND photo_file_id IS NOT NULL")
            updated = cur.rowcount
            await db.commit()
            return updated

# ─── Receipt Fetching ─────────────────────────────────────────────────────────

async def get_month_receipts(month: str) -> list[tuple]:
    rows = await _fetchall(
        "SELECT id, date, store, total_amount FROM receipts WHERE month = ? ORDER BY date DESC, created_at DESC",
        month,
    )
    return [tuple(r) for r in rows]

async def get_receipt_by_id(receipt_id: int):
    if USE_POSTGRES:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            receipt = await conn.fetchrow("SELECT * FROM receipts WHERE id = $1", receipt_id)
            items    = await conn.fetch("SELECT * FROM receipt_items WHERE receipt_id = $1", receipt_id)
            expenses = await conn.fetch("SELECT * FROM personal_expenses WHERE receipt_id = $1", receipt_id)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)) as cur:
                receipt = await cur.fetchone()
            async with db.execute("SELECT * FROM receipt_items WHERE receipt_id = ?", (receipt_id,)) as cur:
                items = await cur.fetchall()
            async with db.execute("SELECT * FROM personal_expenses WHERE receipt_id = ?", (receipt_id,)) as cur:
                expenses = await cur.fetchall()
    return receipt, items, expenses

async def delete_receipt(receipt_id: int) -> None:
    if USE_POSTGRES:
        pool = await _get_pool()
        async with pool.acquire() as conn:
            # CASCADE handles child rows automatically
            await conn.execute("DELETE FROM receipts WHERE id = $1", receipt_id)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM personal_expenses WHERE receipt_id = ?", (receipt_id,))
            await db.execute("DELETE FROM receipt_items WHERE receipt_id = ?", (receipt_id,))
            await db.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
            await db.commit()
