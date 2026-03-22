from __future__ import annotations

from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import Settings
from bot.database import Database, utc_now
from bot.services.formatting import format_user
from bot.services.shop import get_item, get_title_text

router = Router()


def parse_price(args: Optional[str]) -> Optional[int]:
    if not args:
        return None
    parts = args.split()
    if not parts:
        return None
    try:
        price = int(parts[0])
    except ValueError:
        return None
    if price <= 0:
        return None
    return price


def sale_keyboard(title_id: str, price: int, currency: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Купить за {price} {currency}",
                    callback_data=f"title:buy:{title_id}",
                )
            ]
        ]
    )


async def _delete_sale_message(bot, sale) -> None:
    try:
        await bot.delete_message(sale.chat_id, sale.message_id)
    except Exception:
        pass


async def get_title_tax_debt_amount(db: Database, user_id: int) -> int:
    state = await db.get_title_tax_state(user_id)
    if state is None or state.debt_amount <= 0:
        return 0
    return state.debt_amount


@router.message(Command("sell_title"))
async def cmd_sell_title(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    if message.chat.type == "private":
        await message.answer("Команда доступна только в группах.")
        return

    price = parse_price(command.args)
    if price is None:
        await message.answer("Формат: /sell_title <цена>")
        return

    user = await db.get_user(message.from_user.id)
    if user is None or not user.active_title_id:
        await message.answer("У тебя нет выбранного титула. Сначала выбери его через /set_title.")
        return

    title_id = user.active_title_id
    owner = await db.get_title_owner(title_id)
    if owner != message.from_user.id:
        await message.answer("Этот титул тебе не принадлежит.")
        return

    existing = await db.get_title_sale(title_id)
    if existing:
        if existing.seller_id != message.from_user.id:
            await message.answer("Титул уже выставлен на продажу.")
            return
        await _delete_sale_message(message.bot, existing)
        await db.remove_title_sale(title_id)

    item = get_item(settings, title_id)
    title_text = get_title_text(settings, title_id) or (item.name if item else title_id)
    seller_title = get_title_text(settings, user.active_title_id)
    text = (
        "🏷 Продажа титула\n"
        f"Продавец: {format_user(message.from_user, seller_title)}\n"
        f"Титул: {title_text}\n"
        f"Цена: {price} {settings.currency}\n"
        "Нажми кнопку ниже, чтобы купить."
    )

    sent = await message.answer(text, reply_markup=sale_keyboard(title_id, price, settings.currency))
    await db.upsert_title_sale(title_id, sent.chat.id, sent.message_id, message.from_user.id, price)


@router.message(Command("gift_title"))
async def cmd_gift_title(message: Message, db: Database, settings: Settings) -> None:
    if message.chat.type == "private":
        await message.answer("Команда доступна только в группах.")
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.answer("Нужно ответить на сообщение получателя: /gift_title")
        return

    target = message.reply_to_message.from_user
    if getattr(target, "is_bot", False):
        await message.answer("Нельзя подарить титул боту")
        return
    if target.id == message.from_user.id:
        await message.answer("Нельзя подарить титул самому себе")
        return
    if not await db.user_exists(target.id):
        await message.answer("У получателя нет профиля. Ему нужно написать /start")
        return

    sender_debt = await get_title_tax_debt_amount(db, message.from_user.id)
    if sender_debt > 0:
        await message.answer(
            f"Сначала погаси долг по титульному налогу: {sender_debt} {settings.currency}."
        )
        return
    target_debt = await get_title_tax_debt_amount(db, target.id)
    if target_debt > 0:
        await message.answer("Получатель не может принять титул, пока у него есть долг по титульному налогу.")
        return

    user = await db.get_user(message.from_user.id)
    if user is None or not user.active_title_id:
        await message.answer("У тебя нет выбранного титула. Сначала выбери его через /set_title.")
        return

    title_id = user.active_title_id
    owner = await db.get_title_owner(title_id)
    if owner != message.from_user.id:
        await message.answer("Этот титул тебе не принадлежит.")
        return

    existing = await db.get_title_sale(title_id)
    if existing:
        await _delete_sale_message(message.bot, existing)
        await db.remove_title_sale(title_id)

    async with db.transaction() as conn:
        now = utc_now()
        await conn.execute(
            """
            INSERT INTO title_ownership (title_id, owner_id, purchased_at)
            VALUES (?, ?, ?)
            ON CONFLICT(title_id)
            DO UPDATE SET owner_id = excluded.owner_id, purchased_at = excluded.purchased_at
            """,
            (title_id, target.id, now),
        )
        await conn.execute(
            """
            UPDATE users SET active_title_id = NULL, updated_at = ?
            WHERE user_id = ? AND active_title_id = ?
            """,
            (now, message.from_user.id, title_id),
        )
        await conn.execute(
            "UPDATE users SET active_title_id = ?, updated_at = ? WHERE user_id = ?",
            (title_id, now, target.id),
        )

    item = get_item(settings, title_id)
    title_text = get_title_text(settings, title_id) or (item.name if item else title_id)
    sender_title_text = get_title_text(settings, user.active_title_id)
    await message.answer(
        f"🎁 {format_user(message.from_user, sender_title_text)} "
        f"подарил титул {title_text} пользователю {format_user(target, title_text)}"
    )


@router.callback_query(F.data.startswith("title:buy:"))
async def title_buy_callback(callback, db: Database, settings: Settings) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    title_id = parts[2]

    sale = await db.get_title_sale(title_id)
    if sale is None:
        await callback.answer("Объявление больше не актуально", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    if callback.message and callback.message.message_id != sale.message_id:
        await callback.answer("Объявление устарело", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    if callback.from_user.id == sale.seller_id:
        await callback.answer("Нельзя купить у самого себя", show_alert=True)
        return

    if not await db.user_exists(callback.from_user.id):
        await callback.answer("Сначала создай профиль через /start", show_alert=True)
        return

    buyer_debt = await get_title_tax_debt_amount(db, callback.from_user.id)
    if buyer_debt > 0:
        await callback.answer(
            f"Сначала погаси долг по титульному налогу: {buyer_debt} {settings.currency}.",
            show_alert=True,
        )
        return

    owner = await db.get_title_owner(title_id)
    if owner != sale.seller_id:
        await db.remove_title_sale(title_id)
        await callback.answer("Титул уже недоступен", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            pass
        return

    ok = False
    async with db.transaction() as conn:
        now = utc_now()
        cur = await conn.execute(
            "UPDATE users SET balance = balance - ?, updated_at = ? WHERE user_id = ? AND balance >= ?",
            (sale.price, now, callback.from_user.id, sale.price),
        )
        if cur.rowcount == 1:
            await conn.execute(
                "UPDATE users SET balance = balance + ?, updated_at = ? WHERE user_id = ?",
                (sale.price, now, sale.seller_id),
            )
            await conn.execute(
                """
                INSERT INTO title_ownership (title_id, owner_id, purchased_at)
                VALUES (?, ?, ?)
                ON CONFLICT(title_id)
                DO UPDATE SET owner_id = excluded.owner_id, purchased_at = excluded.purchased_at
                """,
                (title_id, callback.from_user.id, now),
            )
            await conn.execute(
                """
                UPDATE users SET active_title_id = NULL, updated_at = ?
                WHERE user_id = ? AND active_title_id = ?
                """,
                (now, sale.seller_id, title_id),
            )
            await conn.execute(
                "UPDATE users SET active_title_id = ?, updated_at = ? WHERE user_id = ?",
                (title_id, now, callback.from_user.id),
            )
            await conn.execute("DELETE FROM title_sales WHERE title_id = ?", (title_id,))
            ok = True

    if not ok:
        await callback.answer("Недостаточно средств", show_alert=True)
        return

    await callback.answer("Покупка успешна", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
