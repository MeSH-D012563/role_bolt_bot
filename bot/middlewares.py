from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import monotonic

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from bot.config import Settings
from bot.database import Database, calc_expiry


class DbMiddleware(BaseMiddleware):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def __call__(self, handler, event, data):
        data["db"] = self._db
        return await handler(event, data)


class SettingsMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(self, handler, event, data):
        data["settings"] = self._settings
        return await handler(event, data)


class StartGateMiddleware(BaseMiddleware):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def __call__(self, handler, event, data):
        user = None
        if hasattr(event, "from_user") and event.from_user:
            user = event.from_user
        if user is None:
            return await handler(event, data)

        if isinstance(event, Message):
            text = (event.text or "").strip()
            if text.startswith("/start"):
                return await handler(event, data)

        db_user = await self._db.get_user(user.id)
        if db_user is None:
            text = "Сначала создай профиль командой /start. После этого станут доступны игры и магазин."
            if isinstance(event, Message):
                await event.answer(text)
                return
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
                return
            return

        # Keep username fresh
        username = user.username
        if db_user.username != username:
            await self._db.update_username(user.id, username)

        data["db_user"] = db_user
        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._last: dict[tuple[int, str], float] = {}
        self._lock = asyncio.Lock()

    async def __call__(self, handler, event, data):
        if self._interval <= 0:
            return await handler(event, data)

        if "db_user" not in data:
            return await handler(event, data)

        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        key = None
        if isinstance(event, Message):
            text = (event.text or "").strip()
            if not text.startswith("/"):
                return await handler(event, data)
            cmd = text.split()[0]
            if cmd == "/start":
                return await handler(event, data)
            key = f"msg:{cmd}"
        elif isinstance(event, CallbackQuery):
            data_key = event.data or ""
            if not (data_key.startswith("basket:") or data_key.startswith("duel:")):
                return await handler(event, data)
            key = f"cb:{data_key.split(':')[0]}"
        else:
            return await handler(event, data)

        now = monotonic()
        async with self._lock:
            last = self._last.get((user.id, key))
            if last is not None and (now - last) < self._interval:
                if isinstance(event, Message):
                    await event.answer("Слишком часто. Подожди пару секунд и попробуй снова.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Слишком часто. Подожди пару секунд.", show_alert=False)
                return
            self._last[(user.id, key)] = now

        return await handler(event, data)


class MuteMiddleware(BaseMiddleware):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def __call__(self, handler, event, data):
        if not isinstance(event, Message):
            return await handler(event, data)

        if event.chat.type == "private":
            return await handler(event, data)

        user = event.from_user
        if user is None:
            return await handler(event, data)

        mute = await self._db.get_mute(event.chat.id, user.id)
        if mute is None:
            return await handler(event, data)

        expires_at = calc_expiry(mute.started_at, mute.duration_seconds, mute.expires_at)
        if expires_at is None:
            await self._db.remove_mute(event.chat.id, user.id)
            return await handler(event, data)

        if expires_at <= datetime.now(timezone.utc):
            await self._db.remove_mute(event.chat.id, user.id)
            return await handler(event, data)

        return await handler(event, data)
