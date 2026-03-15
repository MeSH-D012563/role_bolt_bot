from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BotCommand, ChatPermissions

from bot.config import load_settings
from bot.database import Database, utc_now
from bot.middlewares import DbMiddleware, MuteMiddleware, RateLimitMiddleware, SettingsMiddleware, StartGateMiddleware
from bot.handlers import start, games, profile, tops, help, shop, pay, daily, titles


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
    try:
        await on_startup(bot)
        await dp.start_polling(bot)
    finally:
        cleanup_bans_task.cancel()
        cleanup_mutes_task.cancel()
        cleanup_duels_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_bans_task
            await cleanup_mutes_task
            await cleanup_duels_task
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
