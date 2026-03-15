from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def duel_accept_keyboard(duel_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(
            text="✅ Принять дуэль",
            callback_data=f"duel:accept:{duel_id}",
        )
    )
    return builder.as_markup()


def basket_actions_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="Продолжить 🏀", callback_data="basket:continue"),
        InlineKeyboardButton(text="Забрать банк 💰", callback_data="basket:cashout"),
    )
    builder.adjust(2)
    return builder.as_markup()


def shop_keyboard(items: list, category: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="Все", callback_data="shop:cat:all"),
        InlineKeyboardButton(text="Наказания", callback_data="shop:cat:punish"),
    )
    builder.row(
        InlineKeyboardButton(text="Защиты", callback_data="shop:cat:protect"),
        InlineKeyboardButton(text="Титулы", callback_data="shop:cat:title"),
    )

    for item in items:
        if item.kind in ("ban", "mute"):
            builder.row(
                InlineKeyboardButton(
                    text=f"Как применить: {item.id}",
                    callback_data=f"shop:info:{item.id}",
                )
            )
    return builder.as_markup()
