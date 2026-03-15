from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import Settings

router = Router()


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings) -> None:
    if message.chat.type != "private":
        await message.answer("Эта команда доступна только в ЛС. Напиши боту в личку.")
        return
    if message.chat.type == "private":
        text = (
            "📌 Основное\n"
            "/start — создать профиль\n\n"
            "🎮 Игры\n"
            "/slot <ставка> — 🎰 слот‑автомат\n"
            "/dice <ставка> — 🎲 дуэль (ответом на сообщение, только группы)\n"
            "/basket <ставка> — 🏀 начать баскетбол\n"
            "/basket_continue — 🏀 продолжить\n"
            "/basket_cashout — 💰 забрать банк\n\n"
            "👤 Профиль\n"
            "/profile — твой профиль (только ЛС)\n"
            "/set_title <title_id|none> — выбрать титул\n"
            "Титулы дают бонус к выигрышам в слотах и баскете\n\n"
            "🏷 Титулы\n"
            "/sell_title <цена> — выставить активный титул на продажу (в группе)\n"
            "/gift_title — подарить активный титул (ответом на сообщение)\n\n"
            "💸 Переводы\n"
            "/pay <сумма> — перевести деньги (ответом на сообщение)\n\n"
            "🎁 Бонус\n"
            "/get_cash — ежедневные 200 монет (раз в 24 часа)\n\n"
            "🛍 Магазин\n"
            "/shop — список товаров (только ЛС)\n"
            "/help_shop или /shop_help — справка по магазину\n"
            "/buy <item_id> — купить товар (ответом на сообщение для наказаний)\n\n"
            "🏆 Рейтинги\n"
            "/top_balance — топ по балансу\n"
            "/top_lost — топ по проигрышам\n\n"
            f"ℹ️ Валюта: {settings.currency}\n"
            f"Минимальная ставка: {settings.min_bet}"
        )
    await message.answer(text)
