from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import Settings
from bot.database import Database, parse_datetime
from bot.services.formatting import format_percent_bp
from bot.services.messages import answer_in_chunks, split_message_text
from bot.services.shop import calculate_title_tax, format_title_effects, get_item, get_title_text
from bot.services.timefmt import format_duration, seconds_until

router = Router()


@router.message(Command("profile"))
async def cmd_profile(message: Message, db: Database, settings: Settings) -> None:
    user = await db.get_user(message.from_user.id)
    if user is None:
        await message.answer("Сначала создай профиль командой /start")
        return

    active_title_text = get_title_text(settings, user.active_title_id) or "нет"
    owned_titles = await db.get_user_titles(user.user_id)
    title_lines = []
    if owned_titles:
        for tid in owned_titles:
            item = get_item(settings, tid)
            title_name = item.title_text if item and item.title_text else (item.name if item else tid)
            marker = " (активный)" if tid == user.active_title_id else ""
            effect_text = format_title_effects(settings, tid)
            title_lines.append(f"• {tid} — {title_name} — {effect_text}{marker}")
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

    title_tax_state = await db.get_title_tax_state(user.user_id)
    current_tax = calculate_title_tax(settings, owned_titles)
    title_tax_lines = [
        f"Ставка: {format_percent_bp(settings.title_tax_rate_bp)} от суммарной стоимости титулов при 2+ титулах.",
        "Первый титул бесплатный.",
    ]
    if current_tax > 0:
        title_tax_lines.append(f"Текущий налог: {current_tax} {settings.currency} / 24ч.")
    else:
        title_tax_lines.append("Текущий налог: нет.")
    if title_tax_state and title_tax_state.debt_amount > 0:
        title_tax_lines.append(f"Долг: {title_tax_state.debt_amount} {settings.currency}.")
        if title_tax_state.debt_started_at:
            debt_started_dt = parse_datetime(title_tax_state.debt_started_at)
            if debt_started_dt is not None:
                remaining = max(
                    int(
                        settings.title_tax_grace_seconds
                        - (datetime.now(timezone.utc) - debt_started_dt).total_seconds()
                    ),
                    0,
                )
            else:
                remaining = 0
            title_tax_lines.append(f"До конфискации неактивного титула: {format_duration(remaining)}.")
        title_tax_lines.append("Эффекты титулов отключены до погашения долга.")

    text = (
        "👤 Профиль\n"
        f"Баланс: {user.balance} {settings.currency}\n"
        f"Выиграно всего: {user.total_won} {settings.currency}\n"
        f"Проиграно всего: {user.total_lost} {settings.currency}\n\n"
        "🏷 Титулы\n"
        f"Активный: {active_title_text}"
    )
    if user.active_title_id:
        text += f"\nЭффекты: {format_title_effects(settings, user.active_title_id)}"
    text += (
        "\n"
        "Список:\n"
        + "\n".join(title_lines)
        + "\n"
        "\n🛡 Защиты\n"
        + "\n".join(protection_lines)
        + "\n"
        "\n💸 Налог на титулы\n"
        + "\n".join(title_tax_lines)
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
