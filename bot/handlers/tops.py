from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import Settings
from bot.database import Database
from bot.services.formatting import format_username
from bot.services.shop import get_title_text

router = Router()


def format_top(rows, title_map: dict[int, str | None], value_attr: str, settings: Settings) -> str:
    if not rows:
        return "Пока нет данных."
    lines = []
    for idx, user in enumerate(rows, start=1):
        title_text = get_title_text(settings, title_map.get(user.user_id))
        name = format_username(user.username, user.user_id, title_text)
        value = getattr(user, value_attr)
        lines.append(f"{idx}. {name} — {value} {settings.currency}")
    return "\n".join(lines)


@router.message(Command("top_balance"))
async def cmd_top_balance(message: Message, db: Database, settings: Settings) -> None:
    if message.chat.type != "private":
        await message.answer("Топ доступен только в ЛС. Напиши боту в личку.")
        return
    rows = await db.top_by_balance(10)
    title_map = await db.get_active_title_ids([u.user_id for u in rows])
    text = "🏆 Топ по балансу:\n" + format_top(rows, title_map, "balance", settings)
    await message.answer(text)


@router.message(Command("top_lost"))
async def cmd_top_lost(message: Message, db: Database, settings: Settings) -> None:
    if message.chat.type != "private":
        await message.answer("Топ доступен только в ЛС. Напиши боту в личку.")
        return
    rows = await db.top_by_lost(10)
    title_map = await db.get_active_title_ids([u.user_id for u in rows])
    text = "📉 Топ по проигрышам:\n" + format_top(rows, title_map, "total_lost", settings)
    await message.answer(text)
