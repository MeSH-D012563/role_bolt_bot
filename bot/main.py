from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BotCommand, ChatPermissions

from bot.config import load_settings
from bot.database import Database, parse_datetime, utc_now
from bot.middlewares import DbMiddleware, MuteMiddleware, RateLimitMiddleware, SettingsMiddleware, StartGateMiddleware
from bot.handlers import start, games, profile, tops, help, shop, pay, daily, titles
from bot.services.shop import calculate_title_tax, get_title_text, pick_confiscation_title
from bot.services.timefmt import format_duration


async def on_startup(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Создать профиль"),
        BotCommand(command="help", description="Справка по командам"),
        BotCommand(command="help_shop", description="Справка по магазину"),
        BotCommand(command="shop_help", description="Справка по магазину"),
        BotCommand(command="shop", description="Магазин товаров"),
        BotCommand(command="buy", description="Купить товар: /buy <item_id> (ответом)"),
        BotCommand(command="pay", description="Перевести: /pay <сумма> (ответом)"),
        BotCommand(command="get_cash", description="Получить ежедневный бонус"),
        BotCommand(command="sell_title", description="Продать титул: /sell_title <цена>"),
        BotCommand(command="gift_title", description="Подарить титул (ответом)"),
        BotCommand(command="set_title", description="Выбрать титул"),
        BotCommand(command="slot", description="🎰 Слот-автомат: /slot <ставка>"),
        BotCommand(command="dice", description="🎲 Дуэль: /dice <ставка> (ответом)"),
        BotCommand(command="basket", description="🏀 Баскетбол: /basket <ставка>"),
        BotCommand(command="basket_continue", description="🏀 Продолжить баскетбол"),
        BotCommand(command="basket_cashout", description="💰 Забрать банк"),
        BotCommand(command="profile", description="Профиль (только ЛС)"),
        BotCommand(command="top_balance", description="Топ по балансу"),
        BotCommand(command="top_lost", description="Топ по проигрышам"),
    ]
    await bot.set_my_commands(commands)


def _is_safe_unban_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "not banned" in lowered
        or "not a member" in lowered
        or "not participant" in lowered
        or "user not found" in lowered
    )


def _is_safe_restrict_error(message: str) -> bool:
    lowered = message.lower()
    return (
        "not a member" in lowered
        or "not participant" in lowered
        or "user not found" in lowered
    )


def _full_chat_permissions() -> ChatPermissions:
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
        can_change_info=True,
        can_invite_users=True,
        can_pin_messages=True,
        can_manage_topics=True,
    )


def _resolve_unmute_permissions(chat_permissions: ChatPermissions | None) -> ChatPermissions:
    return chat_permissions or _full_chat_permissions()


async def _send_unban_invite(bot: Bot, chat_id: int, user_id: int, ttl_seconds: int) -> None:
    if ttl_seconds <= 0:
        return
    try:
        link = await bot.create_chat_invite_link(
            chat_id,
            expire_date=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
            member_limit=1,
        )
        await bot.send_message(
            user_id,
            "✅ Срок бана истёк. Вот ссылка, чтобы вернуться в чат:\n"
            f"{link.invite_link}",
        )
    except Exception:
        pass


async def ban_cleanup_loop(bot: Bot, db: Database, interval: int, invite_ttl_seconds: int) -> None:
    while True:
        try:
            expired = await db.get_expired_bans(utc_now())
            for ban in expired:
                success = True
                try:
                    await bot.unban_chat_member(ban.chat_id, ban.user_id, only_if_banned=True)
                except TelegramBadRequest as exc:
                    if not _is_safe_unban_error(str(exc)):
                        success = False
                except Exception:
                    success = False
                if success:
                    await db.remove_ban(ban.chat_id, ban.user_id)
                    await _send_unban_invite(
                        bot,
                        ban.chat_id,
                        ban.user_id,
                        invite_ttl_seconds,
                    )
        except Exception:
            pass
        await asyncio.sleep(interval)


async def mute_cleanup_loop(bot: Bot, db: Database, interval: int) -> None:
    while True:
        try:
            expired = await db.get_expired_mutes(utc_now())
            for mute in expired:
                success = True
                try:
                    chat = await bot.get_chat(mute.chat_id)
                    permissions = _resolve_unmute_permissions(getattr(chat, "permissions", None))
                    await bot.restrict_chat_member(
                        mute.chat_id,
                        mute.user_id,
                        permissions=permissions,
                    )
                except TelegramBadRequest as exc:
                    if not _is_safe_restrict_error(str(exc)):
                        success = False
                except Exception:
                    success = False
                if success:
                    await db.remove_mute(mute.chat_id, mute.user_id)
        except Exception:
            pass
        await asyncio.sleep(interval)


async def duel_cleanup_loop(bot: Bot, db: Database, interval: int, ttl_seconds: int) -> None:
    while True:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)
            expired = await db.get_pending_duels_before(cutoff.isoformat())
            for duel in expired:
                refunded = False
                async with db.transaction() as conn:
                    now = utc_now()
                    cur = await conn.execute(
                        "UPDATE duels SET status = 'cancelled' WHERE id = ? AND status = 'pending'",
                        (duel.id,),
                    )
                    if cur.rowcount == 1:
                        await conn.execute(
                            "UPDATE users SET balance = balance + ?, updated_at = ? WHERE user_id = ?",
                            (duel.bet, now, duel.initiator_id),
                        )
                        refunded = True
                if refunded:
                    try:
                        await bot.send_message(
                            duel.chat_id,
                            "⌛ Дуэль не была принята вовремя. Ставка возвращена инициатору.",
                        )
                    except Exception:
                        pass
        except Exception:
            pass
        await asyncio.sleep(interval)


async def _safe_notify_title_tax(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except Exception:
        pass


async def title_tax_loop(bot: Bot, db: Database, settings, interval: int) -> None:
    while True:
        try:
            users = {user.user_id: user for user in await db.get_users_for_title_tax()}
            ownerships = await db.get_all_title_ownerships()
            states = {state.user_id: state for state in await db.get_all_title_tax_states()}
            titles_by_user: dict[int, list[str]] = defaultdict(list)
            for owner_id, title_id in ownerships:
                titles_by_user[owner_id].append(title_id)

            now_dt = datetime.now(timezone.utc)
            now_iso = now_dt.isoformat()
            all_user_ids = set(users) | set(titles_by_user) | set(states)

            for user_id in all_user_ids:
                user = users.get(user_id)
                if user is None:
                    continue
                title_ids = titles_by_user.get(user_id, [])
                state = states.get(user_id)

                if state and state.debt_amount > 0:
                    if not title_ids:
                        await db.clear_title_tax_debt(user_id, last_charged_at=now_iso)
                        continue

                    if await db.try_withdraw(user_id, state.debt_amount):
                        await db.clear_title_tax_debt(user_id, last_charged_at=now_iso)
                        await _safe_notify_title_tax(
                            bot,
                            user_id,
                            "✅ Долг по титульному налогу погашен автоматически.\n"
                            "Эффекты титулов снова активны.",
                        )
                        continue

                    debt_started_dt = parse_datetime(state.debt_started_at)
                    if debt_started_dt is None:
                        await db.upsert_title_tax_state(
                            user_id,
                            last_charged_at=state.last_charged_at,
                            debt_amount=state.debt_amount,
                            debt_started_at=now_iso,
                        )
                        continue

                    if (now_dt - debt_started_dt).total_seconds() < settings.title_tax_grace_seconds:
                        continue

                    if len(title_ids) <= 1:
                        continue

                    confiscated_title_id = pick_confiscation_title(
                        settings,
                        title_ids,
                        user.active_title_id,
                    )
                    if confiscated_title_id is None:
                        continue

                    sale = await db.get_title_sale(confiscated_title_id)
                    if sale is not None:
                        try:
                            await bot.delete_message(sale.chat_id, sale.message_id)
                        except Exception:
                            pass

                    async with db.transaction() as conn:
                        await conn.execute(
                            "DELETE FROM title_sales WHERE title_id = ?",
                            (confiscated_title_id,),
                        )
                        await conn.execute(
                            "DELETE FROM title_ownership WHERE title_id = ? AND owner_id = ?",
                            (confiscated_title_id, user_id),
                        )
                        await conn.execute(
                            """
                            UPDATE users SET active_title_id = NULL, updated_at = ?
                            WHERE user_id = ? AND active_title_id = ?
                            """,
                            (now_iso, user_id, confiscated_title_id),
                        )
                        await conn.execute(
                            """
                            INSERT INTO title_tax_state (
                                user_id, last_charged_at, debt_amount, debt_started_at, created_at, updated_at
                            )
                            VALUES (?, ?, 0, NULL, ?, ?)
                            ON CONFLICT(user_id)
                            DO UPDATE SET
                                last_charged_at = excluded.last_charged_at,
                                debt_amount = 0,
                                debt_started_at = NULL,
                                updated_at = excluded.updated_at
                            """,
                            (user_id, now_iso, now_iso, now_iso),
                        )

                    confiscated_title_name = get_title_text(settings, confiscated_title_id) or confiscated_title_id
                    await _safe_notify_title_tax(
                        bot,
                        user_id,
                        "⚠️ Долг по титульному налогу не был погашен вовремя.\n"
                        f"Изъят титул: {confiscated_title_name}.\n"
                        "Долг закрыт, отсчёт налога начнётся заново через 24 часа.",
                    )
                    continue

                tax_amount = calculate_title_tax(settings, title_ids)
                if tax_amount <= 0:
                    continue

                last_charged_dt = parse_datetime(state.last_charged_at) if state else None
                if last_charged_dt is not None and (
                    now_dt - last_charged_dt
                ).total_seconds() < settings.title_tax_period_seconds:
                    continue

                if await db.try_withdraw(user_id, tax_amount):
                    await db.upsert_title_tax_state(
                        user_id,
                        last_charged_at=now_iso,
                        debt_amount=0,
                        debt_started_at=None,
                    )
                    continue

                await db.upsert_title_tax_state(
                    user_id,
                    last_charged_at=now_iso,
                    debt_amount=tax_amount,
                    debt_started_at=now_iso,
                )
                await _safe_notify_title_tax(
                    bot,
                    user_id,
                    "⚠️ Не удалось списать титульный налог.\n"
                    f"Сумма долга: {tax_amount} {settings.currency}.\n"
                    f"Льготный период: {format_duration(settings.title_tax_grace_seconds)}.\n"
                    "Пока долг не погашен, эффекты титулов отключены.\n"
                    "Если долг не будет закрыт вовремя, бот заберёт один неактивный титул.",
                )
        except Exception:
            pass
        await asyncio.sleep(interval)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)

    settings = load_settings()

    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    db = Database(settings.db_path)
    await db.connect()
    await db.init()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    dp.update.middleware(SettingsMiddleware(settings))
    dp.update.middleware(DbMiddleware(db))

    dp.message.middleware(MuteMiddleware(db))
    dp.message.middleware(StartGateMiddleware(db))
    dp.callback_query.middleware(StartGateMiddleware(db))
    dp.message.middleware(RateLimitMiddleware(settings.rate_limit_seconds))
    dp.callback_query.middleware(RateLimitMiddleware(settings.rate_limit_seconds))

    dp.include_router(start.router)
    dp.include_router(help.router)
    dp.include_router(shop.router)
    dp.include_router(pay.router)
    dp.include_router(daily.router)
    dp.include_router(titles.router)
    dp.include_router(games.router)
    dp.include_router(profile.router)
    dp.include_router(tops.router)

    cleanup_bans_task = asyncio.create_task(
        ban_cleanup_loop(
            bot,
            db,
            settings.ban_check_interval_seconds,
            settings.ban_invite_link_ttl_seconds,
        )
    )
    cleanup_mutes_task = asyncio.create_task(
        mute_cleanup_loop(bot, db, settings.mute_check_interval_seconds)
    )
    cleanup_duels_task = asyncio.create_task(
        duel_cleanup_loop(
            bot,
            db,
            settings.duel_check_interval_seconds,
            settings.duel_ttl_seconds,
        )
    )
    title_tax_task = asyncio.create_task(
        title_tax_loop(
            bot,
            db,
            settings,
            settings.title_tax_check_interval_seconds,
        )
    )
    try:
        await on_startup(bot)
        await dp.start_polling(bot)
    finally:
        cleanup_bans_task.cancel()
        cleanup_mutes_task.cancel()
        cleanup_duels_task.cancel()
        title_tax_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_bans_task
            await cleanup_mutes_task
            await cleanup_duels_task
            await title_tax_task
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
