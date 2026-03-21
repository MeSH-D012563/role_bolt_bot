from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import Settings
from bot.database import Database
from bot.services.formatting import format_percent_bp
from bot.services.messages import answer_in_chunks, split_message_text
from bot.services.shop import get_item, get_title_bonus_bp, get_title_text
from bot.services.timefmt import format_duration, seconds_until

router = Router()


@router.message(Command("profile"))
async def cmd_profile(message: Message, db: Database, settings: Settings) -> None:
    user = await db.get_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала создай профиль командой /start")
        return

    active_title_text = get_title_text(settings, user.active_title_id) or "нет"
    active_bonus_bp = get_title_bonus_bp(settings, user.active_title_id)
    owned_titles = await db.get_user_titles(user.user_id)
    title_lines = []
    if owned_titles:
        for tid in owned_titles:
            item = get_item(settings, tid)
            title_name = item.title_text if item and item.title_text else (item.name if item else tid)
            marker = " (активный)" if tid == user.active_title_id else ""
            bonus_bp = get_title_bonus_bp(settings, tid)
            bonus_text = (
                f" (+{format_percent_bp(bonus_bp)} к выигрышам)" if bonus_bp > 0 else ""
            )
            title_lines.append(f"• {tid} — {title_name}{bonus_text}{marker}")
    else:
        title_lines.append("— нет")

    protections = await db.get_protections(user.user_id)
    protection_lines = []
    for p in protections:
        remaining = seconds_until(p.expires_at)
        if remaining <= 0:
            await db.remove_protection(user.user_id, p.protection_id)
            continue
        item = get_item(settings, p.protection_id)
        name = item.name if item else p.protection_id
        protection_lines.append(f"• {name} — {format_duration(remaining)}")
    if not protection_lines:
        protection_lines.append("— нет")

    text = (
        "👤 Профиль\n"
        f"Баланс: {user.balance} {settings.currency}\n"
        f"Выиграно всего: {user.total_won} {settings.currency}\n"
        f"Проиграно всего: {user.total_lost} {settings.currency}\n\n"
        "🏷 Титулы\n"
        f"Активный: {active_title_text}"
    )
    if active_bonus_bp > 0 and active_title_text != "нет":
        text += f" (+{format_percent_bp(active_bonus_bp)} к выигрышам)"
    text += (
        "\n"
        "Список:\n"
        + "\n".join(title_lines)
        + "\n"
        "\n🛡 Защиты\n"
        + "\n".join(protection_lines)
        + "\n"
        "\nКоманда: /set_title <title_id|none>"
    )

    if message.chat.type != "private":
        await message.answer("Профиль доступен только в ЛС. Отправил тебе в личку.")
        try:
            for chunk in split_message_text(text):
                await message.bot.send_message(message.from_user.id, chunk)
        except Exception:
            await message.answer("Не удалось отправить ЛС. Открой личку с ботом.")
        return

    await answer_in_chunks(message, text)
