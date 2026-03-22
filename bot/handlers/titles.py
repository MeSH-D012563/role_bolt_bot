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


def instant_sell_keyboard(
    seller_id: int,
    title_id: str,
    price: int,
    currency: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Продать за {price} {currency}",
                    callback_data=f"title:sellnow:confirm:{seller_id}:{title_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"title:sellnow:cancel:{seller_id}:{title_id}",
                )
            ],
        ]
    )


def private_sell_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть ЛС для продажи",
                    url=url,
                )
            ]
        ]
    )


async def _delete_sale_message(bot, sale) -> None:
    try:
        await bot.delete_message(sale.chat_id, sale.message_id)
    except Exception:
        pass


def get_instant_sell_price(market_price: int) -> int:
    return max((market_price * 90) // 100, 1)


async def get_title_tax_debt_amount(db: Database, user_id: int) -> int:
    state = await db.get_title_tax_state(user_id)
    if state is None or state.debt_amount <= 0:
        return 0
    return state.debt_amount


async def perform_instant_title_sale(
    message: Message,
    *,
    seller_id: int,
    db: Database,
    settings: Settings,
) -> tuple[bool, str]:
    user = await db.get_user(seller_id)
    if user is None or not user.active_title_id:
        return False, "У тебя нет выбранного титула. Сначала выбери его через /set_title."

    title_id = user.active_title_id
    owner = await db.get_title_owner(title_id)
    if owner != seller_id:
        return False, "Этот титул тебе не принадлежит."

    item = get_item(settings, title_id)
    if item is None or item.kind != "title":
        return False, "Не удалось определить рыночную стоимость титула."

    sale = await db.get_title_sale(title_id)
    if sale:
        await _delete_sale_message(message.bot, sale)

    instant_price = get_instant_sell_price(item.price)
    now = utc_now()
    async with db.transaction() as conn:
        if sale:
            await conn.execute("DELETE FROM title_sales WHERE title_id = ?", (title_id,))
        await conn.execute(
            "DELETE FROM title_ownership WHERE title_id = ? AND owner_id = ?",
            (title_id, seller_id),
        )
        await conn.execute(
            """
            UPDATE users
            SET balance = balance + ?, active_title_id = NULL, updated_at = ?
            WHERE user_id = ? AND active_title_id = ?
            """,
            (instant_price, now, seller_id, title_id),
        )

    title_text = get_title_text(settings, title_id) or (item.title_text or item.name)
    return (
        True,
        f"💸 Титул {title_text} мгновенно продан боту.\n"
        f"Рыночная цена: {item.price} {settings.currency}\n"
        f"Выплата: {instant_price} {settings.currency} (90%).",
    )


async def send_instant_sell_confirmation(
    message: Message,
    *,
    seller_id: int,
    db: Database,
    settings: Settings,
) -> None:
    user = await db.get_user(seller_id)
    if user is None or not user.active_title_id:
        await message.answer("У тебя нет выбранного титула. Сначала выбери его через /set_title.")
        return

    title_id = user.active_title_id
    owner = await db.get_title_owner(title_id)
    if owner != seller_id:
        await message.answer("Этот титул тебе не принадлежит.")
        return

    item = get_item(settings, title_id)
    if item is None or item.kind != "title":
        await message.answer("Не удалось определить рыночную стоимость титула.")
        return

    instant_price = get_instant_sell_price(item.price)
    title_text = get_title_text(settings, title_id) or (item.title_text or item.name)
    await message.answer(
        f"Подтвердить мгновенную продажу титула {title_text}?\n"
        f"Рыночная цена: {item.price} {settings.currency}\n"
        f"Ты получишь: {instant_price} {settings.currency} (90%).",
        reply_markup=instant_sell_keyboard(
            seller_id,
            title_id,
            instant_price,
            settings.currency,
        ),
    )


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


@router.message(Command("sell_title_now"))
async def cmd_sell_title_now(message: Message, db: Database, settings: Settings) -> None:
    if message.chat.type != "private":
        bot_user = await message.bot.get_me()
        if not bot_user.username:
            await message.answer("Команда доступна в ЛС. Открой личку с ботом и отправь /sell_title_now.")
            return
        await message.answer(
            "Подтверждение мгновенной продажи доступно только в ЛС.",
            reply_markup=private_sell_keyboard(
                f"https://t.me/{bot_user.username}?start=sell_title_now",
            ),
        )
        return

    await send_instant_sell_confirmation(
        message,
        seller_id=message.from_user.id,
        db=db,
        settings=settings,
    )


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


@router.callback_query(F.data.startswith("title:sellnow:"))
async def title_sell_now_callback(callback, db: Database, settings: Settings) -> None:
    parts = callback.data.split(":")
    if len(parts) != 5:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    action = parts[2]
    try:
        seller_id = int(parts[3])
    except ValueError:
        await callback.answer("Некорректные данные", show_alert=True)
        return
    title_id = parts[4]

    if callback.from_user.id != seller_id:
        await callback.answer("Подтвердить может только владелец титула", show_alert=True)
        return

    if action == "cancel":
        await callback.answer("Продажа отменена")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    if action != "confirm":
        await callback.answer("Некорректное действие", show_alert=True)
        return

    user = await db.get_user(seller_id)
    if user is None or user.active_title_id != title_id:
        await callback.answer("Этот титул уже не активен", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    success, response_text = await perform_instant_title_sale(
        callback.message,
        seller_id=seller_id,
        db=db,
        settings=settings,
    )
    if not success:
        await callback.answer(response_text, show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    await callback.answer("Продажа выполнена")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(response_text)
