from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import Settings
from bot.database import Database
from bot.services.shop import get_title_effect
from bot.services.timefmt import format_duration

router = Router()


@router.message(Command("get_cash"))
async def cmd_get_cash(message: Message, db: Database, settings: Settings) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=settings.daily_cash_cooldown_seconds)
    now_iso = now.isoformat()
    cutoff_iso = cutoff.isoformat()
    user = await db.get_user(message.from_user.id)
    tax_state = await db.get_title_tax_state(message.from_user.id)
    effects_enabled = tax_state is None or tax_state.debt_amount <= 0
    title_effect = get_title_effect(
        settings,
        user.active_title_id if user else None,
        effects_enabled=effects_enabled,
    )
    reward = settings.daily_cash_amount + title_effect.daily_bonus_amount

    claimed = False
    async with db.transaction() as conn:
        cur = await conn.execute(
            """
            UPDATE users
            SET balance = balance + ?, last_cash_claimed_at = ?, updated_at = ?
            WHERE user_id = ?
              AND (last_cash_claimed_at IS NULL OR last_cash_claimed_at <= ?)
            """,
            (
                reward,
                now_iso,
                now_iso,
                message.from_user.id,
                cutoff_iso,
            ),
        )
        if cur.rowcount == 1:
            claimed = True

    if claimed:
        lines = [f"✅ Ты получил {reward} {settings.currency}."]
        if title_effect.daily_bonus_amount > 0:
            lines.append(
                f"Бонус титула: +{title_effect.daily_bonus_amount} {settings.currency}."
            )
        lines.append("Следующий бонус будет доступен через 12 часов.")
        await message.answer("\n".join(lines))
        return

    user = await db.get_user(message.from_user.id)
    if user and user.last_cash_claimed_at:
        try:
            last_dt = datetime.fromisoformat(user.last_cash_claimed_at)
            next_dt = last_dt + timedelta(seconds=settings.daily_cash_cooldown_seconds)
            remaining = max(int((next_dt - now).total_seconds()), 0)
            await message.answer(
                "⏳ Бонус уже был получен.\n"
                f"Попробуй снова через {format_duration(remaining)}."
            )
            return
        except Exception:
            pass

    await message.answer("⏳ Бонус пока недоступен. Попробуй позже.")
