from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from bot.config import Settings
from bot.database import Database, Duel, utc_now
from bot.keyboards import basket_actions_keyboard, duel_accept_keyboard
from bot.services.formatting import format_percent_bp, format_user, format_username
from bot.services.games import basket_is_success, calc_payout, evaluate_slot
from bot.services.shop import get_title_bonus_bp, get_title_text

router = Router()


def parse_bet(args: Optional[str], settings: Settings) -> Optional[int]:
    if not args:
        return None
    parts = args.split()
    if not parts:
        return None
    try:
        bet = int(parts[0])
    except ValueError:
        return None
    if bet < settings.min_bet or bet > settings.max_bet:
        return None
    return bet


def duel_is_expired(duel: Duel, settings: Settings) -> bool:
    try:
        created = datetime.fromisoformat(duel.created_at)
    except ValueError:
        return False
    now = datetime.now(timezone.utc)
    return (now - created).total_seconds() > settings.duel_ttl_seconds


def bet_range_text(settings: Settings) -> str:
    return f"{settings.min_bet}–{settings.max_bet} {settings.currency}"


async def get_title_context(db: Database, settings: Settings, user_id: int) -> tuple[str | None, int]:
    user = await db.get_user(user_id)
    if user is None:
        return None, 0
    title_id = user.active_title_id
    return get_title_text(settings, title_id), get_title_bonus_bp(settings, title_id)


def reply_kwargs(reply_to_message_id: int | None) -> dict:
    if reply_to_message_id:
        return {
            "reply_to_message_id": reply_to_message_id,
            "allow_sending_without_reply": True,
        }
    return {}


async def resolve_target_user(message: Message, args: Optional[str]):
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user

    return None


@router.message(Command("slot"))
async def cmd_slot(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    reply_to = message.message_id
    bet = parse_bet(command.args, settings)
    if bet is None:
        await message.answer(
            f"Нужна ставка. Формат: /slot {settings.min_bet}\n"
            f"Диапазон: {bet_range_text(settings)}"
        )
        return

    if not await db.try_withdraw(message.from_user.id, bet):
        await message.answer("Недостаточно средств для ставки. Баланс — /profile.")
        return

    title_text, bonus_bp = await get_title_context(db, settings, message.from_user.id)
    player_label = "Ты" if message.chat.type == "private" else format_user(message.from_user, title_text)

    dice_msg = await message.answer_dice(emoji="🎰")
    await asyncio.sleep(settings.animation_delay)

    value = dice_msg.dice.value
    multiplier_bp, label = evaluate_slot(value, settings)
    if multiplier_bp <= 0:
        async with db.transaction() as conn:
            now = utc_now()
            await conn.execute(
                "UPDATE users SET total_lost = total_lost + ?, updated_at = ? WHERE user_id = ?",
                (bet, now, message.from_user.id),
            )
        await message.answer(
            f"🎰 {label}\n"
            f"{player_label} проиграл {bet} {settings.currency}.",
            **reply_kwargs(reply_to),
        )
        return

    base_payout = calc_payout(bet, multiplier_bp)
    bonus_amount = 0
    if bonus_bp > 0:
        bonus_amount = (base_payout * bonus_bp) // 10000
    payout = base_payout + bonus_amount
    profit = max(payout - bet, 0)
    async with db.transaction() as conn:
        now = utc_now()
        await conn.execute(
            "UPDATE users SET balance = balance + ?, total_won = total_won + ?, updated_at = ? WHERE user_id = ?",
            (payout, profit, now, message.from_user.id),
        )

    lines = [
        f"🎰 {label}",
        f"{player_label} выиграл.",
    ]
    if bonus_bp > 0 and bonus_amount > 0:
        lines.append(
            f"Бонус титула: +{format_percent_bp(bonus_bp)} (+{bonus_amount} {settings.currency})"
        )
    lines.append(f"Выплата: {payout} {settings.currency}")
    lines.append(f"Прибыль: {profit} {settings.currency}.")
    await message.answer("\n".join(lines), **reply_kwargs(reply_to))


@router.message(Command("dice"))
async def cmd_dice(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    if message.chat.type == "private":
        await message.answer("Дуэли доступны только в группах. Используй команду в чате.")
        return

    bet = parse_bet(command.args, settings)
    if bet is None:
        await message.answer(
            f"Формат: /dice {settings.min_bet} (ответом на сообщение)\n"
            f"Диапазон: {bet_range_text(settings)}"
        )
        return

    target = await resolve_target_user(message, command.args)
    if target is None:
        await message.answer("Нужно ответить на сообщение соперника: /dice <ставка>")
        return

    if target.id == message.from_user.id:
        await message.answer("Нельзя вызвать самого себя")
        return

    if getattr(target, "is_bot", False):
        await message.answer("Нельзя играть с ботом")
        return

    if not await db.user_exists(target.id):
        await message.answer("У соперника нет профиля. Ему нужно написать /start в личку.")
        return

    duel_id: int | None = None
    try:
        async with db.transaction() as conn:
            now = utc_now()
            cur = await conn.execute(
                "UPDATE users SET balance = balance - ?, updated_at = ? WHERE user_id = ? AND balance >= ?",
                (bet, now, message.from_user.id, bet),
            )
            if cur.rowcount == 1:
                cur = await conn.execute(
                    """
                    INSERT INTO duels (chat_id, message_id, initiator_id, target_id, bet, status, created_at)
                    VALUES (?, NULL, ?, ?, ?, 'pending', ?)
                    """,
                    (message.chat.id, message.from_user.id, target.id, bet, now),
                )
                duel_id = int(cur.lastrowid)
    except Exception:
        await message.answer("Не удалось создать дуэль. Попробуй еще раз.")
        return

    if duel_id is None:
        await message.answer("Недостаточно средств для ставки. Баланс — /profile.")
        return
    initiator_db = await db.get_user(message.from_user.id)
    target_db = await db.get_user(target.id)
    initiator_title = get_title_text(settings, initiator_db.active_title_id) if initiator_db else None
    target_title = get_title_text(settings, target_db.active_title_id) if target_db else None

    text = (
        "🎲 Дуэль\n"
        f"Инициатор: {format_user(message.from_user, initiator_title)}\n"
        f"Оппонент: {format_user(target, target_title)}\n"
        f"Ставка: {bet} {settings.currency}\n"
        "Оппоненту нужно нажать кнопку ниже, чтобы принять."
    )
    sent = await message.answer(
        text,
        reply_markup=duel_accept_keyboard(duel_id),
        **reply_kwargs(message.message_id),
    )
    await db.set_duel_message(duel_id, message.message_id)

    async def cancel_if_expired() -> None:
        await asyncio.sleep(settings.duel_ttl_seconds)
        duel = await db.get_duel(duel_id)
        if duel is None or duel.status != "pending":
            return
        refunded = False
        async with db.transaction() as conn:
            now = utc_now()
            cur = await conn.execute(
                "UPDATE duels SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
                (duel_id,),
            )
            if cur.rowcount == 1:
                await conn.execute(
                    "UPDATE users SET balance = balance + ?, updated_at = ? WHERE user_id = ?",
                    (duel.bet, now, duel.initiator_id),
                )
                refunded = True
        if not refunded:
            return
        try:
            await message.bot.send_message(
                duel.chat_id,
                "⌛ Дуэль не была принята вовремя. Ставка возвращена инициатору.",
                **reply_kwargs(duel.message_id),
            )
        except Exception:
            pass

    asyncio.create_task(cancel_if_expired())


@router.callback_query(F.data.startswith("duel:accept:"))
async def duel_accept(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Некорректный запрос", show_alert=True)
        return

    try:
        duel_id = int(parts[2])
    except ValueError:
        await callback.answer("Некорректный запрос", show_alert=True)
        return
    duel = await db.get_duel(duel_id)
    if duel is None:
        await callback.answer("Дуэль не найдена", show_alert=True)
        return

    if callback.from_user.id != duel.target_id:
        await callback.answer("Принять может только приглашённый игрок", show_alert=True)
        return

    if duel.status != "pending":
        await callback.answer("Дуэль уже обработана", show_alert=True)
        return

    if duel_is_expired(duel, settings):
        refunded = False
        async with db.transaction() as conn:
            now = utc_now()
            cur = await conn.execute(
                "UPDATE duels SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
                (duel_id,),
            )
            if cur.rowcount == 1:
                await conn.execute(
                    "UPDATE users SET balance = balance + ?, updated_at = ? WHERE user_id = ?",
                    (duel.bet, now, duel.initiator_id),
                )
                refunded = True
        if not refunded:
            await callback.answer("Дуэль уже обработана", show_alert=True)
            return
        await callback.answer("Дуэль истекла, ставка возвращена", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    accept_result = "ok"
    async with db.transaction() as conn:
        cur = await conn.execute(
            "UPDATE duels SET status = 'accepted' WHERE id = ? AND status = 'pending'",
            (duel_id,),
        )
        if cur.rowcount != 1:
            accept_result = "not_pending"
        else:
            now = utc_now()
            cur2 = await conn.execute(
                "UPDATE users SET balance = balance - ?, updated_at = ? WHERE user_id = ? AND balance >= ?",
                (duel.bet, now, duel.target_id, duel.bet),
            )
            if cur2.rowcount != 1:
                await conn.execute(
                    "UPDATE duels SET status = 'cancelled' WHERE id = ?",
                    (duel_id,),
                )
                await conn.execute(
                    "UPDATE users SET balance = balance + ?, updated_at = ? WHERE user_id = ?",
                    (duel.bet, now, duel.initiator_id),
                )
                accept_result = "no_funds"

    if accept_result == "not_pending":
        await callback.answer("Дуэль уже обработана", show_alert=True)
        return
    if accept_result == "no_funds":
        await callback.answer("Недостаточно средств", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer(
            "❌ Дуэль отменена, ставка возвращена инициатору.",
            **reply_kwargs(duel.message_id),
        )
        return

    await callback.answer("Дуэль принята")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    msg1 = await callback.message.answer_dice(emoji="🎲")
    msg2 = await callback.message.answer_dice(emoji="🎲")
    await asyncio.sleep(settings.animation_delay)

    v1 = msg1.dice.value
    v2 = msg2.dice.value

    initiator_db = await db.get_user(duel.initiator_id)
    target_db = await db.get_user(duel.target_id)
    initiator_title = get_title_text(settings, initiator_db.active_title_id) if initiator_db else None
    target_title = get_title_text(settings, target_db.active_title_id) if target_db else None
    initiator_name = format_username(
        initiator_db.username if initiator_db else None,
        duel.initiator_id,
        initiator_title,
    )
    target_name = format_username(
        target_db.username if target_db else None,
        duel.target_id,
        target_title,
    )

    if v1 == v2:
        async with db.transaction() as conn:
            now = utc_now()
            await conn.execute(
                "UPDATE users SET balance = balance + ?, updated_at = ? WHERE user_id = ?",
                (duel.bet, now, duel.initiator_id),
            )
            await conn.execute(
                "UPDATE users SET balance = balance + ?, updated_at = ? WHERE user_id = ?",
                (duel.bet, now, duel.target_id),
            )
            await conn.execute(
                "UPDATE duels SET status = 'draw' WHERE id = ?",
                (duel_id,),
            )
        await callback.message.answer(
            f"🤝 Ничья между {initiator_name} и {target_name}. Ставки возвращены.",
            **reply_kwargs(duel.message_id),
        )
        return

    if v1 > v2:
        winner_id = duel.initiator_id
        loser_id = duel.target_id
        winner_name = initiator_name
        loser_name = target_name
    else:
        winner_id = duel.target_id
        loser_id = duel.initiator_id
        winner_name = target_name
        loser_name = initiator_name

    pot = duel.bet * 2
    async with db.transaction() as conn:
        now = utc_now()
        await conn.execute(
            "UPDATE users SET balance = balance + ?, total_won = total_won + ?, updated_at = ? WHERE user_id = ?",
            (pot, duel.bet, now, winner_id),
        )
        await conn.execute(
            "UPDATE users SET total_lost = total_lost + ?, updated_at = ? WHERE user_id = ?",
            (duel.bet, now, loser_id),
        )
        await conn.execute(
            "UPDATE duels SET status = 'finished' WHERE id = ?",
            (duel_id,),
        )

    await callback.message.answer(
        f"🏆 Победитель: {winner_name}\n"
        f"Проиграл: {loser_name}\n"
        f"Выигрыш: {pot} {settings.currency}.",
        **reply_kwargs(duel.message_id),
    )


@router.message(Command("basket"))
async def cmd_basket(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    bet = parse_bet(command.args, settings)
    if bet is None:
        await message.answer(
            f"Нужна ставка. Формат: /basket {settings.min_bet}\n"
            f"Диапазон: {bet_range_text(settings)}"
        )
        return

    result = "ok"
    async with db.transaction() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM basket_games WHERE user_id = ?",
            (message.from_user.id,),
        )
        if await cur.fetchone():
            result = "exists"
        else:
            now = utc_now()
            cur2 = await conn.execute(
                "UPDATE users SET balance = balance - ?, updated_at = ? WHERE user_id = ? AND balance >= ?",
                (bet, now, message.from_user.id, bet),
            )
            if cur2.rowcount != 1:
                result = "no_funds"
            else:
                await conn.execute(
                    """
                    INSERT INTO basket_games (user_id, bank, bet, in_play, created_at, updated_at)
                    VALUES (?, ?, ?, 0, ?, ?)
                    """,
                    (message.from_user.id, bet, bet, now, now),
                )

    if result == "exists":
        await message.answer(
            "У тебя уже есть активный банк. Используй /basket_continue или /basket_cashout.",
            **reply_kwargs(message.message_id),
        )
        return
    if result == "no_funds":
        await message.answer(
            "Недостаточно средств для ставки. Баланс — /profile.",
            **reply_kwargs(message.message_id),
        )
        return
    await play_basket_turn(message, message.from_user.id, db, settings, reply_to_message_id=message.message_id)


@router.message(Command("basket_continue"))
async def cmd_basket_continue(message: Message, db: Database, settings: Settings) -> None:
    await play_basket_turn(message, message.from_user.id, db, settings, reply_to_message_id=message.message_id)


@router.message(Command("basket_cashout"))
async def cmd_basket_cashout(message: Message, db: Database, settings: Settings) -> None:
    await cashout_basket(message, message.from_user.id, db, settings, reply_to_message_id=message.message_id)


@router.callback_query(F.data == "basket:continue")
async def basket_continue_callback(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    await callback.answer()
    await play_basket_turn(callback.message, callback.from_user.id, db, settings, reply_to_message_id=None)


@router.callback_query(F.data == "basket:cashout")
async def basket_cashout_callback(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    await callback.answer()
    await cashout_basket(callback.message, callback.from_user.id, db, settings, reply_to_message_id=None)


async def play_basket_turn(
    message: Message,
    user_id: int,
    db: Database,
    settings: Settings,
    reply_to_message_id: int | None,
) -> None:
    game = await db.get_basket(user_id)
    if not game:
        await message.answer(
            f"Нет активной игры. Начни с /basket {settings.min_bet}",
            **reply_kwargs(reply_to_message_id),
        )
        return

    if not await db.try_lock_basket(user_id):
        await message.answer("Подожди завершения предыдущего броска", **reply_kwargs(reply_to_message_id))
        return

    title_text, bonus_bp = await get_title_context(db, settings, user_id)
    player_label = "Ты" if message.chat.type == "private" else format_user(message.from_user, title_text)

    try:
        dice_msg = await message.answer_dice(emoji="🏀")
        await asyncio.sleep(settings.animation_delay)

        value = dice_msg.dice.value
        if basket_is_success(value, settings):
            base_bank = calc_payout(game.bank, settings.basket_multiplier_bp)
            bonus_amount = 0
            if bonus_bp > 0:
                bonus_amount = (base_bank * bonus_bp) // 10000
            new_bank = base_bank + bonus_amount
            await db.update_basket_bank(user_id, new_bank)
            header = "🏀 Попадание!" if message.chat.type == "private" else f"🏀 {player_label} — попадание!"
            lines = [header, f"Банк: {new_bank} {settings.currency}."]
            if bonus_bp > 0 and bonus_amount > 0:
                lines.append(
                    f"Бонус титула: +{format_percent_bp(bonus_bp)} (+{bonus_amount} {settings.currency})"
                )
            await message.answer(
                "\n".join(lines),
                reply_markup=basket_actions_keyboard(),
                **reply_kwargs(reply_to_message_id),
            )
            return

        async with db.transaction() as conn:
            now = utc_now()
            await conn.execute(
                "DELETE FROM basket_games WHERE user_id = ?",
                (user_id,),
            )
            await conn.execute(
                "UPDATE users SET total_lost = total_lost + ?, updated_at = ? WHERE user_id = ?",
                (game.bet, now, user_id),
            )
        if message.chat.type == "private":
            await message.answer("❌ Промах. Банк сгорел.", **reply_kwargs(reply_to_message_id))
        else:
            await message.answer(
                f"❌ {player_label} — промах. Банк сгорел.",
                **reply_kwargs(reply_to_message_id),
            )
    finally:
        await db.unlock_basket(user_id)


async def cashout_basket(
    message: Message,
    user_id: int,
    db: Database,
    settings: Settings,
    reply_to_message_id: int | None,
) -> None:
    game = await db.get_basket(user_id)
    if not game:
        await message.answer("Нет активного банка для вывода", **reply_kwargs(reply_to_message_id))
        return
    if game.in_play:
        await message.answer("Подожди завершения броска", **reply_kwargs(reply_to_message_id))
        return
    if not await db.try_lock_basket(user_id):
        await message.answer("Подожди завершения броска", **reply_kwargs(reply_to_message_id))
        return

    bank: int | None = None
    profit: int | None = None
    try:
        async with db.transaction() as conn:
            cur = await conn.execute(
                "SELECT bank, bet FROM basket_games WHERE user_id = ?",
                (user_id,),
            )
            row = await cur.fetchone()
            if row is None:
                bank = None
                profit = None
            else:
                bank = int(row["bank"])
                bet = int(row["bet"])
                profit = max(bank - bet, 0)
                now = utc_now()
                await conn.execute(
                    "DELETE FROM basket_games WHERE user_id = ?",
                    (user_id,),
                )
                await conn.execute(
                    "UPDATE users SET balance = balance + ?, total_won = total_won + ?, updated_at = ? WHERE user_id = ?",
                    (bank, profit, now, user_id),
                )
    finally:
        await db.unlock_basket(user_id)

    if bank is None or profit is None:
        await message.answer("Нет активного банка для вывода", **reply_kwargs(reply_to_message_id))
        return

    title_text, _ = await get_title_context(db, settings, user_id)
    player_label = "Ты" if message.chat.type == "private" else format_user(message.from_user, title_text)
    await message.answer(
        f"💰 {player_label} забрал {bank} {settings.currency}.\n"
        f"Прибыль: {profit} {settings.currency}.",
        **reply_kwargs(reply_to_message_id),
    )
