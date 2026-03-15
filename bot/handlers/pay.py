from __future__ import annotations

from typing import Optional

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.config import Settings
from bot.database import Database, utc_now
from bot.services.formatting import format_user
from bot.services.shop import get_title_text

router = Router()


def parse_amount(args: Optional[str]) -> Optional[int]:
    if not args:
        return None
    parts = args.split()
    if not parts:
        return None
    try:
        amount = int(parts[0])
    except ValueError:
        return None
    if amount <= 0:
        return None
    return amount


async def resolve_target_user(message: Message, args: Optional[str]):
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user

    return None


@router.message(Command("pay"))
async def cmd_pay(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    amount = parse_amount(command.args)
    if amount is None:
        await message.answer("Формат: /pay <сумма> (ответом на сообщение)")
        return

    target = await resolve_target_user(message, command.args)
    if target is None:
        await message.answer("Нужно ответить на сообщение получателя: /pay <сумма>")
        return

    if getattr(target, "is_bot", False):
        await message.answer("Нельзя переводить боту")
        return

    if target.id == message.from_user.id:
        await message.answer("Нельзя переводить самому себе")
        return

    if not await db.user_exists(target.id):
        await message.answer("У получателя нет профиля. Ему нужно написать /start")
        return

    success = False
    async with db.transaction() as conn:
        now = utc_now()
        cur = await conn.execute(
            "UPDATE users SET balance = balance - ?, updated_at = ? WHERE user_id = ? AND balance >= ?",
            (amount, now, message.from_user.id, amount),
        )
        if cur.rowcount == 1:
            await conn.execute(
                "UPDATE users SET balance = balance + ?, updated_at = ? WHERE user_id = ?",
                (amount, now, target.id),
            )
            success = True

    if not success:
        await message.answer("Недостаточно средств для перевода. Баланс — /profile.")
        return

    target_db = await db.get_user(target.id)
    target_title = get_title_text(settings, target_db.active_title_id) if target_db else None
    await message.answer(
        f"✅ Перевод выполнен: {amount} {settings.currency} → {format_user(target, target_title)}"
    )
