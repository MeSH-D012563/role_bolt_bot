from __future__ import annotations

import asyncio
from dataclasses import dataclass
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiosqlite


@dataclass
class User:
    user_id: int
    username: str | None
    balance: int
    total_lost: int
    total_won: int
    active_title_id: str | None = None
    last_cash_claimed_at: str | None = None


@dataclass
class Duel:
    id: int
    chat_id: int
    message_id: int | None
    initiator_id: int
    target_id: int
    bet: int
    status: str
    created_at: str


@dataclass
class BasketGame:
    user_id: int
    bank: int
    bet: int
    in_play: int
    created_at: str
    updated_at: str


@dataclass
class Protection:
    user_id: int
    protection_id: str
    expires_at: str
    created_at: str


@dataclass
class Mute:
    chat_id: int
    user_id: int
    expires_at: str | None
    created_at: str
    started_at: str | None = None
    duration_seconds: int | None = None


@dataclass
class Ban:
    chat_id: int
    user_id: int
    expires_at: str | None
    created_at: str
    started_at: str | None = None
    duration_seconds: int | None = None


@dataclass
class TitleSale:
    title_id: str
    chat_id: int
    message_id: int
    seller_id: int
    price: int
    created_at: str


@dataclass
class TitleTaxState:
    user_id: int
    last_charged_at: str | None
    debt_amount: int
    debt_started_at: str | None
    created_at: str
    updated_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def calc_expiry(started_at: str | None, duration_seconds: int | None, fallback_expires_at: str | None) -> datetime | None:
    if started_at and duration_seconds is not None:
        start_dt = parse_datetime(started_at)
        if start_dt is not None:
            return start_dt + timedelta(seconds=int(duration_seconds))
    return parse_datetime(fallback_expires_at)


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")
        await self._conn.execute("PRAGMA busy_timeout=3000;")
        await self._conn.commit()

    @asynccontextmanager
    async def transaction(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        async with self._lock:
            try:
                await self._conn.execute("BEGIN")
                yield self._conn
                await self._conn.execute("COMMIT")
            except Exception:
                await self._conn.execute("ROLLBACK")
                raise

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()

    async def init(self) -> None:
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER NOT NULL,
                total_lost INTEGER NOT NULL DEFAULT 0,
                total_won INTEGER NOT NULL DEFAULT 0,
                active_title_id TEXT,
                last_cash_claimed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        try:
            await self.execute("ALTER TABLE users ADD COLUMN active_title_id TEXT")
        except Exception:
            pass
        try:
            await self.execute("ALTER TABLE users ADD COLUMN last_cash_claimed_at TEXT")
        except Exception:
            pass
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS duels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER,
                initiator_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                bet INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS basket_games (
                user_id INTEGER PRIMARY KEY,
                bank INTEGER NOT NULL,
                bet INTEGER NOT NULL,
                in_play INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
            """
        )
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS title_ownership (
                title_id TEXT PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                purchased_at TEXT NOT NULL,
                FOREIGN KEY(owner_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
            """
        )
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS title_sales (
                title_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                seller_id INTEGER NOT NULL,
                price INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS protections (
                user_id INTEGER NOT NULL,
                protection_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(user_id, protection_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
            """
        )
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS title_tax_state (
                user_id INTEGER PRIMARY KEY,
                last_charged_at TEXT,
                debt_amount INTEGER NOT NULL DEFAULT 0,
                debt_started_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
            """
        )
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS mutes (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                started_at TEXT,
                duration_seconds INTEGER,
                created_at TEXT NOT NULL,
                PRIMARY KEY(chat_id, user_id)
            )
            """
        )
        for stmt in (
            "ALTER TABLE mutes ADD COLUMN started_at TEXT",
            "ALTER TABLE mutes ADD COLUMN duration_seconds INTEGER",
        ):
            try:
                await self.execute(stmt)
            except Exception:
                pass
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS bans (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                started_at TEXT,
                duration_seconds INTEGER,
                created_at TEXT NOT NULL,
                PRIMARY KEY(chat_id, user_id)
            )
            """
        )
        for stmt in (
            "ALTER TABLE bans ADD COLUMN started_at TEXT",
            "ALTER TABLE bans ADD COLUMN duration_seconds INTEGER",
        ):
            try:
                await self.execute(stmt)
            except Exception:
                pass

    async def execute(self, query: str, params: tuple = ()) -> aiosqlite.Cursor:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        async with self._lock:
            cursor = await self._conn.execute(query, params)
            await self._conn.commit()
            return cursor

    async def fetchone(self, query: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        async with self._lock:
            cursor = await self._conn.execute(query, params)
            row = await cursor.fetchone()
            return row

    async def fetchall(self, query: str, params: tuple = ()) -> list[aiosqlite.Row]:
        if self._conn is None:
            raise RuntimeError("Database is not connected")
        async with self._lock:
            cursor = await self._conn.execute(query, params)
            rows = await cursor.fetchall()
            return list(rows)

    # Users
    async def get_user(self, user_id: int) -> User | None:
        row = await self.fetchone(
            """
            SELECT user_id, username, balance, total_lost, total_won, active_title_id, last_cash_claimed_at
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        )
        if row is None:
            return None
        return User(**dict(row))

    async def user_exists(self, user_id: int) -> bool:
        row = await self.fetchone("SELECT 1 FROM users WHERE user_id = ?", (user_id,))
        return row is not None

    async def create_user(self, user_id: int, username: str | None, start_balance: int) -> None:
        now = utc_now()
        await self.execute(
            """
            INSERT INTO users (
                user_id,
                username,
                balance,
                total_lost,
                total_won,
                active_title_id,
                last_cash_claimed_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, 0, 0, NULL, NULL, ?, ?)
            """,
            (user_id, username, start_balance, now, now),
        )

    async def update_username(self, user_id: int, username: str | None) -> None:
        await self.execute(
            "UPDATE users SET username = ?, updated_at = ? WHERE user_id = ?",
            (username, utc_now(), user_id),
        )

    async def try_withdraw(self, user_id: int, amount: int) -> bool:
        now = utc_now()
        cursor = await self.execute(
            """
            UPDATE users
            SET balance = balance - ?, updated_at = ?
            WHERE user_id = ? AND balance >= ?
            """,
            (amount, now, user_id, amount),
        )
        return cursor.rowcount == 1

    async def deposit(self, user_id: int, amount: int) -> None:
        await self.execute(
            "UPDATE users SET balance = balance + ?, updated_at = ? WHERE user_id = ?",
            (amount, utc_now(), user_id),
        )

    async def add_loss(self, user_id: int, amount: int) -> None:
        await self.execute(
            "UPDATE users SET total_lost = total_lost + ?, updated_at = ? WHERE user_id = ?",
            (amount, utc_now(), user_id),
        )

    async def add_win(self, user_id: int, amount: int) -> None:
        await self.execute(
            "UPDATE users SET total_won = total_won + ?, updated_at = ? WHERE user_id = ?",
            (amount, utc_now(), user_id),
        )

    async def top_by_balance(self, limit: int) -> list[User]:
        rows = await self.fetchall(
            """
            SELECT user_id, username, balance, total_lost, total_won
            FROM users
            ORDER BY balance DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [User(**dict(r)) for r in rows]

    async def top_by_lost(self, limit: int) -> list[User]:
        rows = await self.fetchall(
            """
            SELECT user_id, username, balance, total_lost, total_won
            FROM users
            ORDER BY total_lost DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [User(**dict(r)) for r in rows]

    async def set_active_title(self, user_id: int, title_id: str | None) -> None:
        await self.execute(
            "UPDATE users SET active_title_id = ?, updated_at = ? WHERE user_id = ?",
            (title_id, utc_now(), user_id),
        )

    async def get_active_title_id(self, user_id: int) -> str | None:
        row = await self.fetchone(
            "SELECT active_title_id FROM users WHERE user_id = ?",
            (user_id,),
        )
        if row is None:
            return None
        return row["active_title_id"]

    async def get_active_title_ids(self, user_ids: list[int]) -> dict[int, str | None]:
        if not user_ids:
            return {}
        placeholders = ",".join(["?"] * len(user_ids))
        rows = await self.fetchall(
            f"SELECT user_id, active_title_id FROM users WHERE user_id IN ({placeholders})",
            tuple(user_ids),
        )
        return {int(r["user_id"]): r["active_title_id"] for r in rows}

    # Titles
    async def get_title_owner(self, title_id: str) -> int | None:
        row = await self.fetchone(
            "SELECT owner_id FROM title_ownership WHERE title_id = ?",
            (title_id,),
        )
        if row is None:
            return None
        return int(row["owner_id"])

    async def get_user_titles(self, user_id: int) -> list[str]:
        rows = await self.fetchall(
            "SELECT title_id FROM title_ownership WHERE owner_id = ?",
            (user_id,),
        )
        return [r["title_id"] for r in rows]

    async def add_title_ownership(self, title_id: str, owner_id: int) -> None:
        await self.execute(
            "INSERT INTO title_ownership (title_id, owner_id, purchased_at) VALUES (?, ?, ?)",
            (title_id, owner_id, utc_now()),
        )

    async def upsert_title_ownership(self, title_id: str, owner_id: int) -> None:
        await self.execute(
            """
            INSERT INTO title_ownership (title_id, owner_id, purchased_at)
            VALUES (?, ?, ?)
            ON CONFLICT(title_id)
            DO UPDATE SET owner_id = excluded.owner_id, purchased_at = excluded.purchased_at
            """,
            (title_id, owner_id, utc_now()),
        )

    async def remove_title_ownership(self, title_id: str, owner_id: int) -> None:
        await self.execute(
            "DELETE FROM title_ownership WHERE title_id = ? AND owner_id = ?",
            (title_id, owner_id),
        )

    async def get_title_sale(self, title_id: str) -> TitleSale | None:
        row = await self.fetchone(
            """
            SELECT title_id, chat_id, message_id, seller_id, price, created_at
            FROM title_sales
            WHERE title_id = ?
            """,
            (title_id,),
        )
        if row is None:
            return None
        return TitleSale(**dict(row))

    async def upsert_title_sale(
        self,
        title_id: str,
        chat_id: int,
        message_id: int,
        seller_id: int,
        price: int,
    ) -> None:
        await self.execute(
            """
            INSERT INTO title_sales (title_id, chat_id, message_id, seller_id, price, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(title_id)
            DO UPDATE SET
                chat_id = excluded.chat_id,
                message_id = excluded.message_id,
                seller_id = excluded.seller_id,
                price = excluded.price,
                created_at = excluded.created_at
            """,
            (title_id, chat_id, message_id, seller_id, price, utc_now()),
        )

    async def remove_title_sale(self, title_id: str) -> None:
        await self.execute("DELETE FROM title_sales WHERE title_id = ?", (title_id,))

    async def get_all_title_ownerships(self) -> list[tuple[int, str]]:
        rows = await self.fetchall(
            """
            SELECT owner_id, title_id
            FROM title_ownership
            ORDER BY owner_id, purchased_at
            """
        )
        return [(int(row["owner_id"]), row["title_id"]) for row in rows]

    async def get_title_tax_state(self, user_id: int) -> TitleTaxState | None:
        row = await self.fetchone(
            """
            SELECT user_id, last_charged_at, debt_amount, debt_started_at, created_at, updated_at
            FROM title_tax_state
            WHERE user_id = ?
            """,
            (user_id,),
        )
        if row is None:
            return None
        return TitleTaxState(**dict(row))

    async def get_all_title_tax_states(self) -> list[TitleTaxState]:
        rows = await self.fetchall(
            """
            SELECT user_id, last_charged_at, debt_amount, debt_started_at, created_at, updated_at
            FROM title_tax_state
            """
        )
        return [TitleTaxState(**dict(row)) for row in rows]

    async def upsert_title_tax_state(
        self,
        user_id: int,
        *,
        last_charged_at: str | None,
        debt_amount: int,
        debt_started_at: str | None,
    ) -> None:
        now = utc_now()
        await self.execute(
            """
            INSERT INTO title_tax_state (
                user_id,
                last_charged_at,
                debt_amount,
                debt_started_at,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                last_charged_at = excluded.last_charged_at,
                debt_amount = excluded.debt_amount,
                debt_started_at = excluded.debt_started_at,
                updated_at = excluded.updated_at
            """,
            (user_id, last_charged_at, debt_amount, debt_started_at, now, now),
        )

    async def clear_title_tax_debt(self, user_id: int, *, last_charged_at: str | None = None) -> None:
        current = await self.get_title_tax_state(user_id)
        effective_last_charged_at = last_charged_at
        if effective_last_charged_at is None:
            effective_last_charged_at = current.last_charged_at if current else None
        await self.upsert_title_tax_state(
            user_id,
            last_charged_at=effective_last_charged_at,
            debt_amount=0,
            debt_started_at=None,
        )

    async def get_users_for_title_tax(self) -> list[User]:
        rows = await self.fetchall(
            """
            SELECT user_id, username, balance, total_lost, total_won, active_title_id, last_cash_claimed_at
            FROM users
            WHERE user_id IN (
                SELECT owner_id FROM title_ownership
                UNION
                SELECT user_id FROM title_tax_state
            )
            """
        )
        return [User(**dict(row)) for row in rows]

    # Protections
    async def get_protections(self, user_id: int) -> list[Protection]:
        rows = await self.fetchall(
            "SELECT user_id, protection_id, expires_at, created_at FROM protections WHERE user_id = ?",
            (user_id,),
        )
        return [Protection(**dict(r)) for r in rows]

    async def upsert_protection(self, user_id: int, protection_id: str, expires_at: str) -> None:
        await self.execute(
            """
            INSERT INTO protections (user_id, protection_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, protection_id)
            DO UPDATE SET expires_at = excluded.expires_at
            """,
            (user_id, protection_id, expires_at, utc_now()),
        )

    async def remove_protection(self, user_id: int, protection_id: str) -> None:
        await self.execute(
            "DELETE FROM protections WHERE user_id = ? AND protection_id = ?",
            (user_id, protection_id),
        )

    # Mutes
    async def get_mute(self, chat_id: int, user_id: int) -> Mute | None:
        row = await self.fetchone(
            """
            SELECT chat_id, user_id, expires_at, created_at, started_at, duration_seconds
            FROM mutes
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat_id, user_id),
        )
        if row is None:
            return None
        return Mute(**dict(row))

    async def add_mute(
        self,
        chat_id: int,
        user_id: int,
        expires_at: str,
        started_at: str | None = None,
        duration_seconds: int | None = None,
    ) -> None:
        await self.execute(
            """
            INSERT INTO mutes (chat_id, user_id, expires_at, started_at, duration_seconds, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id)
            DO UPDATE SET
                expires_at = excluded.expires_at,
                started_at = excluded.started_at,
                duration_seconds = excluded.duration_seconds
            """,
            (chat_id, user_id, expires_at, started_at, duration_seconds, utc_now()),
        )

    async def remove_mute(self, chat_id: int, user_id: int) -> None:
        await self.execute(
            "DELETE FROM mutes WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )

    # Bans
    async def get_ban(self, chat_id: int, user_id: int) -> Ban | None:
        row = await self.fetchone(
            """
            SELECT chat_id, user_id, expires_at, created_at, started_at, duration_seconds
            FROM bans
            WHERE chat_id = ? AND user_id = ?
            """,
            (chat_id, user_id),
        )
        if row is None:
            return None
        return Ban(**dict(row))

    async def add_ban(
        self,
        chat_id: int,
        user_id: int,
        expires_at: str,
        started_at: str | None = None,
        duration_seconds: int | None = None,
    ) -> None:
        await self.execute(
            """
            INSERT INTO bans (chat_id, user_id, expires_at, started_at, duration_seconds, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, user_id)
            DO UPDATE SET
                expires_at = excluded.expires_at,
                started_at = excluded.started_at,
                duration_seconds = excluded.duration_seconds
            """,
            (chat_id, user_id, expires_at, started_at, duration_seconds, utc_now()),
        )

    async def remove_ban(self, chat_id: int, user_id: int) -> None:
        await self.execute(
            "DELETE FROM bans WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id),
        )

    async def get_expired_bans(self, now_iso: str) -> list[Ban]:
        rows = await self.fetchall(
            "SELECT chat_id, user_id, expires_at, created_at, started_at, duration_seconds FROM bans",
        )
        now_dt = parse_datetime(now_iso) or datetime.now(timezone.utc)
        expired: list[Ban] = []
        for r in rows:
            data = dict(r)
            expiry = calc_expiry(
                data.get("started_at"),
                data.get("duration_seconds"),
                data.get("expires_at"),
            )
            if expiry is not None and expiry <= now_dt:
                expired.append(Ban(**data))
        return expired

    async def get_expired_mutes(self, now_iso: str) -> list[Mute]:
        rows = await self.fetchall(
            "SELECT chat_id, user_id, expires_at, created_at, started_at, duration_seconds FROM mutes",
        )
        now_dt = parse_datetime(now_iso) or datetime.now(timezone.utc)
        expired: list[Mute] = []
        for r in rows:
            data = dict(r)
            expiry = calc_expiry(
                data.get("started_at"),
                data.get("duration_seconds"),
                data.get("expires_at"),
            )
            if expiry is not None and expiry <= now_dt:
                expired.append(Mute(**data))
        return expired

    # Duels
    async def create_duel(self, chat_id: int, initiator_id: int, target_id: int, bet: int) -> int:
        now = utc_now()
        cursor = await self.execute(
            """
            INSERT INTO duels (chat_id, message_id, initiator_id, target_id, bet, status, created_at)
            VALUES (?, NULL, ?, ?, ?, 'pending', ?)
            """,
            (chat_id, initiator_id, target_id, bet, now),
        )
        return int(cursor.lastrowid)

    async def set_duel_message(self, duel_id: int, message_id: int) -> None:
        await self.execute(
            "UPDATE duels SET message_id = ? WHERE id = ?",
            (message_id, duel_id),
        )

    async def get_duel(self, duel_id: int) -> Duel | None:
        row = await self.fetchone(
            """
            SELECT id, chat_id, message_id, initiator_id, target_id, bet, status, created_at
            FROM duels WHERE id = ?
            """,
            (duel_id,),
        )
        if row is None:
            return None
        return Duel(**dict(row))

    async def get_pending_duels_before(self, cutoff_iso: str) -> list[Duel]:
        rows = await self.fetchall(
            """
            SELECT id, chat_id, message_id, initiator_id, target_id, bet, status, created_at
            FROM duels
            WHERE status = 'pending' AND created_at <= ?
            """,
            (cutoff_iso,),
        )
        return [Duel(**dict(r)) for r in rows]

    async def accept_duel(self, duel_id: int) -> bool:
        cursor = await self.execute(
            "UPDATE duels SET status = 'accepted' WHERE id = ? AND status = 'pending'",
            (duel_id,),
        )
        return cursor.rowcount == 1

    async def finish_duel(self, duel_id: int, status: str) -> None:
        await self.execute(
            "UPDATE duels SET status = ? WHERE id = ?",
            (status, duel_id),
        )

    # Basketball
    async def get_basket(self, user_id: int) -> BasketGame | None:
        row = await self.fetchone(
            """
            SELECT user_id, bank, bet, in_play, created_at, updated_at
            FROM basket_games WHERE user_id = ?
            """,
            (user_id,),
        )
        if row is None:
            return None
        return BasketGame(**dict(row))

    async def create_basket(self, user_id: int, bank: int, bet: int) -> None:
        now = utc_now()
        await self.execute(
            """
            INSERT INTO basket_games (user_id, bank, bet, in_play, created_at, updated_at)
            VALUES (?, ?, ?, 0, ?, ?)
            """,
            (user_id, bank, bet, now, now),
        )

    async def update_basket_bank(self, user_id: int, bank: int) -> None:
        await self.execute(
            """
            UPDATE basket_games
            SET bank = ?, in_play = 0, updated_at = ?
            WHERE user_id = ?
            """,
            (bank, utc_now(), user_id),
        )

    async def delete_basket(self, user_id: int) -> None:
        await self.execute("DELETE FROM basket_games WHERE user_id = ?", (user_id,))

    async def try_lock_basket(self, user_id: int) -> bool:
        cursor = await self.execute(
            """
            UPDATE basket_games
            SET in_play = 1, updated_at = ?
            WHERE user_id = ? AND in_play = 0
            """,
            (utc_now(), user_id),
        )
        return cursor.rowcount == 1

    async def unlock_basket(self, user_id: int) -> None:
        await self.execute(
            "UPDATE basket_games SET in_play = 0, updated_at = ? WHERE user_id = ?",
            (utc_now(), user_id),
        )
