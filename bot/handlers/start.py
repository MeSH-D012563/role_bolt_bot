from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.config import Settings
from bot.database import Database

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, db: Database, settings: Settings) -> None:
    user_id = message.from_user.id
    username = message.from_user.username
    user = await db.get_user(user_id)
    if user is None:
        await db.create_user(user_id, username, settings.start_balance)
        if message.chat.type == "private":
            text = (
                "✅ Профиль создан!\n"
                f"Стартовый баланс: {settings.start_balance} {settings.currency}\n\n"
                "Что дальше:\n"
                "• /help — список команд\n"
                "• /shop — магазин\n"
                "• /slot <ставка> — быстрый старт\n"
                "• /profile — твой профиль"
            )
        else:
            text = (
                "✅ Профиль создан!\n"
                f"Стартовый баланс: {settings.start_balance} {settings.currency}\n\n"
                "Команды и магазин доступны в ЛС.\n"
                "Открой личку с ботом и напиши /help и /shop."
            )
        await message.answer(text)
        return

    if user.username != username:
        await db.update_username(user_id, username)

    if message.chat.type == "private":
        text = (
            "✅ Профиль уже создан.\n"
            f"Баланс: {user.balance} {settings.currency}\n\n"
            "Быстрые команды:\n"
            "• /help — список команд\n"
            "• /shop — магазин\n"
            "• /profile — профиль"
        )
    else:
        text = (
            "✅ Профиль уже создан.\n"
            f"Баланс: {user.balance} {settings.currency}\n\n"
            "Команды и магазин доступны в ЛС: /help, /shop."
        )
    await message.answer(text)
