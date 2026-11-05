from __future__ import annotations

import aiosqlite
from typing import Optional, Iterable, Any
import logging

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (guild_id, key)
);

CREATE TABLE IF NOT EXISTS staff_roles (
    guild_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    role_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, scope, role_id)
);

CREATE INDEX IF NOT EXISTS idx_staff_roles_guild_scope
ON staff_roles (guild_id, scope);

CREATE TABLE IF NOT EXISTS ticket_categories (
    guild_id TEXT NOT NULL,
    server_key TEXT NOT NULL,
    ticket_type TEXT NOT NULL,
    category_id TEXT NOT NULL,
    PRIMARY KEY (guild_id, server_key, ticket_type)
);

CREATE TABLE IF NOT EXISTS ticket_staff_roles (
    guild_id TEXT NOT NULL,
    ticket_type TEXT NOT NULL,
    role_id TEXT NOT NULL,
    PRIMARY KEY (guild_id, ticket_type, role_id)
);

CREATE TABLE IF NOT EXISTS tickets (
    guild_id TEXT NOT NULL,
    ticket_id INTEGER NOT NULL,
    channel_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    server_key TEXT NOT NULL,
    ticket_type TEXT NOT NULL,
    opened_by TEXT,
    closed_by TEXT,
    claimed_by TEXT,
    close_requested_by TEXT,
    close_requested_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_closed INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, ticket_id)
);

CREATE TABLE IF NOT EXISTS ticket_panel_state (
    guild_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS giveaways (
    guild_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    host_id TEXT NOT NULL,
    server_key TEXT NOT NULL,
    prize TEXT NOT NULL,
    winner_count INTEGER NOT NULL,
    required_role_id TEXT,
    min_account_age_days INTEGER NOT NULL DEFAULT 7,
    ends_at TIMESTAMP NOT NULL,
    ended INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, message_id)
);

CREATE TABLE IF NOT EXISTS giveaway_entries (
    guild_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    entered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, message_id, user_id)
);

CREATE TABLE IF NOT EXISTS giveaway_blacklist (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    reason TEXT,
    added_by TEXT NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS polls (
    guild_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    host_id TEXT NOT NULL,
    title TEXT NOT NULL,
    choices TEXT NOT NULL,
    ends_at TIMESTAMP NOT NULL,
    ended INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, message_id)
);

CREATE TABLE IF NOT EXISTS poll_votes (
    guild_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    choice_index INTEGER NOT NULL,
    voted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (guild_id, message_id, user_id)
);
"""


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        if self._conn:
            return
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA_SQL)
        await self._conn.commit()

        # --- guild_settings schema migration ---
        try:
            cur = await self._conn.execute("PRAGMA table_info('guild_settings');")
            rows = await cur.fetchall()
            await cur.close()
            cols = [r['name'] for r in rows]
        except Exception:
            cols = []

        expected = {'guild_id', 'key', 'value'}
        existing = set(cols)
        if not expected.issubset(existing):
            logging.warning("Detected old guild_settings schema, attempting migration: %s", existing)
            await self._conn.execute("ALTER TABLE guild_settings RENAME TO guild_settings_old;")
            await self._conn.execute(
                "CREATE TABLE IF NOT EXISTS guild_settings (guild_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (guild_id, key));"
            )
            if 'value' in existing:
                try:
                    await self._conn.execute(
                        "INSERT INTO guild_settings (guild_id, key, value) SELECT guild_id, 'default', value FROM guild_settings_old;"
                    )
                except Exception:
                    logging.exception("Failed to migrate guild_settings_old -> guild_settings")
            await self._conn.commit()

        # --- tickets column migrations ---
        try:
            cur = await self._conn.execute("PRAGMA table_info('tickets');")
            ticket_rows = await cur.fetchall()
            await cur.close()
            ticket_cols = {r['name'] for r in ticket_rows}
        except Exception:
            ticket_cols = set()

        if ticket_cols:
            if 'close_requested_at' not in ticket_cols:
                try:
                    await self._conn.execute("ALTER TABLE tickets ADD COLUMN close_requested_at TIMESTAMP;")
                    await self._conn.commit()
                except Exception:
                    pass

            if 'claimed_by' not in ticket_cols:
                try:
                    await self._conn.execute("ALTER TABLE tickets ADD COLUMN claimed_by TEXT;")
                    await self._conn.commit()
                    logging.info("Migrated tickets table: added claimed_by column")
                except Exception:
                    logging.exception("Failed to add claimed_by column to tickets")

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if not self._conn:
            raise RuntimeError("Database not connected")
        return self._conn

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        await self.conn.execute(sql, params)
        await self.conn.commit()

    async def executemany(self, sql: str, params_seq: Iterable[tuple[Any, ...]]) -> None:
        params_list = list(params_seq)
        if not params_list:
            return
        await self.conn.executemany(sql, params_list)
        await self.conn.commit()

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return rows

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> Optional[aiosqlite.Row]:
        cur = await self.conn.execute(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return row
