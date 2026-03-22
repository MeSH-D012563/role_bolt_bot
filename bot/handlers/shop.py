from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatPermissions, Message

from bot.config import Settings
from bot.database import Database, utc_now
from bot.keyboards import shop_keyboard
from bot.services.formatting import format_percent_bp, format_user
from bot.services.messages import answer_in_chunks
from bot.services.shop import (
    calculate_title_tax,
    category_items,
    describe_title_effects,
    format_title_effects,
    get_item,
    get_discounted_price,
    get_title_effect,
    get_title_text,
    iter_items,
    list_punishment_items,
    list_protection_items,
    list_title_items,
)
from bot.services.timefmt import format_duration, seconds_until

router = Router()


def parse_item_id(args: Optional[str]) -> Optional[str]:
    if not args:
        return None
    parts = args.split()
    if not parts:
        return None
    return parts[0].strip().lower()


async def resolve_target_user(message: Message, args: Optional[str]):
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user

    return None


async def get_active_protections(db: Database, user_id: int) -> list[tuple[str, int]]:
    protections = await db.get_protections(user_id)
    active: list[tuple[str, int]] = []
    for p in protections:
        remaining = seconds_until(p.expires_at)
        if remaining <= 0:
            await db.remove_protection(user_id, p.protection_id)
        else:
            active.append((p.protection_id, remaining))
    return active


async def get_user_title(db: Database, settings: Settings, user_id: int) -> str | None:
    user = await db.get_user(user_id)
    if user is None:
        return None
    return get_title_text(settings, user.active_title_id)


async def get_title_tax_debt_amount(db: Database, user_id: int) -> int:
    state = await db.get_title_tax_state(user_id)
    if state is None or state.debt_amount <= 0:
        return 0
    return state.debt_amount


@router.message(Command("shop"))
async def cmd_shop(message: Message, db: Database, settings: Settings) -> None:
    if message.chat.type != "private":
        await message.answer("Магазин доступен только в ЛС. Напиши боту в личку.")
        return
    items = category_items(settings, "all")
    text = await build_shop_text(db, settings, message.from_user.id, "all")
    await answer_in_chunks(message, text, reply_markup=shop_keyboard(items, "all"))


@router.message(Command("help_shop", "shop_help"))
async def cmd_help_shop(message: Message, settings: Settings) -> None:
    if message.chat.type != "private":
        await message.answer("Эта команда доступна только в ЛС. Напиши боту в личку.")
        return
    lines = [
        "🛍 Магазин — справка",
        "",
        f"Покупки совершаются за {settings.currency} с твоего баланса.",
        "",
        "Как купить:",
        "1. Открой /shop в ЛС и выбери товар.",
        "2. Используй команду /buy <item_id>.",
        "3. Если товар требует цель — ответь на сообщение цели.",
        "",
        "Где работает:",
        "• /shop и /help_shop — только ЛС",
        "• /buy — в ЛС и группах",
        "• Наказания (бан/мут) — только в группах",
        "",
        "Быстрые примеры:",
        "• /buy <item_id>",
        "• /buy ban_10 (ответом на сообщение)",
        "• /buy mute_10 (ответом на сообщение)",
        "",
        "Правила наказаний:",
        "• Бан нельзя применять к администраторам и создателю чата",
        "• Бан снимается автоматически после окончания времени",
        "• Мут запрещает отправлять сообщения на время действия",
        "• Если у цели есть активная защита — наказание не применится",
        "• Если применить не удалось — средства возвращаются",
        "• Для наказаний бот должен быть администратором чата",
        "",
        "Защита:",
        "• Защита активируется на покупателя и блокирует бан/мут на время",
        "• Повторная покупка продлевает время",
        "",
        "Титулы:",
        "• Каждый титул уникален и доступен только одному игроку",
        "• Купленный титул нельзя купить повторно другим игроком",
        "• Титулы можно выбирать в профиле через /set_title",
        "• Активный титул отображается, когда бот упоминает игрока",
        "• У титулов разные эффекты: бонусы к играм, защите и /get_cash",
        "• Скидка титула на защиты отображается прямо в /shop",
        f"• При 2+ титулах взимается налог {format_percent_bp(settings.title_tax_rate_bp)} в сутки от общей стоимости титулов",
        "• Если налог не списался, даётся 24 часа на погашение долга",
        "• Пока долг активен, эффекты титулов отключены",
        "• После просрочки бот забирает один неактивный титул",
        "",
        "Товары:",
    ]

    for item in iter_items(settings):
        duration = ""
        if item.duration_seconds:
            duration = f" ({format_duration(item.duration_seconds)})"
        if item.kind == "title":
            lines.append(
                f"• {item.id} — {item.name} — {item.price} {settings.currency}{duration}"
            )
            lines.append(f"Эффекты: {format_title_effects(settings, item.id)}")
        else:
            lines.append(
                f"• {item.id} — {item.name} — {item.price} {settings.currency}{duration}"
            )
        if item.description:
            lines.append(f"Описание: {item.description}")

    await answer_in_chunks(message, "\n".join(lines))


@router.message(Command("buy"))
async def cmd_buy(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    item_id = parse_item_id(command.args)
    if not item_id:
        await message.answer("Формат: /buy <item_id> (ответом на сообщение)")
        return

    item = get_item(settings, item_id)
    if item is None:
        await message.answer("Товар не найден. Посмотри список в /shop")
        return

    await process_buy(message, db, settings, item, command.args)


@router.message(Command("set_title"))
async def cmd_set_title(message: Message, command: CommandObject, db: Database, settings: Settings) -> None:
    if not command.args:
        await message.answer("Формат: /set_title <title_id|none>")
        return

    arg = command.args.strip().lower()
    if arg in ("none", "off", "clear", "нет"):
        await db.set_active_title(message.from_user.id, None)
        await message.answer("Активный титул выключен")
        return

    item = get_item(settings, arg)
    if item is None or item.kind != "title":
        await message.answer("Такого титула нет. Посмотри /profile или /shop")
        return

    owned = await db.get_user_titles(message.from_user.id)
    if arg not in owned:
        await message.answer("Этот титул тебе не принадлежит. Список — в /profile")
        return

    await db.set_active_title(message.from_user.id, arg)
    title_text = item.title_text or item.name
    await message.answer(
        f"Активный титул установлен: {title_text}\n"
        f"Эффекты: {format_title_effects(settings, arg)}"
    )


@router.callback_query(F.data.startswith("shop:cat:"))
async def shop_category_callback(callback, db: Database, settings: Settings) -> None:
    if callback.message.chat.type != "private":
        await callback.answer("Доступно только в ЛС", show_alert=True)
        return
    category = callback.data.split(":")[2]
    items = category_items(settings, category)
    text = await build_shop_text(db, settings, callback.from_user.id, category)
    await callback.message.edit_text(text, reply_markup=shop_keyboard(items, category))
    await callback.answer()


@router.callback_query(F.data.startswith("shop:buy:"))
async def shop_buy_callback(callback, db: Database, settings: Settings) -> None:
    if callback.message.chat.type != "private":
        await callback.answer("Доступно только в ЛС", show_alert=True)
        return
    parts = callback.data.split(":")
    item_id = parts[2] if len(parts) > 2 else ""
    category = parts[3] if len(parts) > 3 else "all"
    item = get_item(settings, item_id)
    if item is None:
        await callback.answer("Товар не найден", show_alert=True)
        return
    if item.kind in ("ban", "mute"):
        await callback.answer("Наказания применяются в группе: /buy <item_id> (ответом)", show_alert=True)
        return
    await callback.answer()
    await process_buy(callback.message, db, settings, item, None)
    # Auto-refresh shop after purchase
    items = category_items(settings, category)
    text = await build_shop_text(db, settings, callback.from_user.id, category)
    try:
        await callback.message.edit_text(text, reply_markup=shop_keyboard(items, category))
    except Exception:
        pass


@router.callback_query(F.data.startswith("shop:info:"))
async def shop_info_callback(callback, settings: Settings) -> None:
    if callback.message.chat.type != "private":
        await callback.answer("Доступно только в ЛС", show_alert=True)
        return
    item_id = callback.data.split(":")[2]
    item = get_item(settings, item_id)
    if item is None:
        await callback.answer("Товар не найден", show_alert=True)
        return
    if item.kind in ("ban", "mute"):
        await callback.answer("Применяй в группе: /buy <item_id> (ответом)", show_alert=True)
        return
    await callback.answer("Нажми «Купить» ниже", show_alert=False)


async def build_shop_text(db: Database, settings: Settings, viewer_id: int, category: str) -> str:
    category_labels = {
        "all": "Все",
        "punish": "Наказания",
        "protect": "Защиты",
        "title": "Титулы",
    }
    sections: list[str] = [
        "🛍 Магазин",
        f"Валюта: {settings.currency}",
        f"Категория: {category_labels.get(category, 'Все')}",
        "",
    ]
    viewer = await db.get_user(viewer_id)
    viewer_tax_debt = await get_title_tax_debt_amount(db, viewer_id)
    viewer_effect = get_title_effect(
        settings,
        viewer.active_title_id if viewer else None,
        effects_enabled=viewer_tax_debt <= 0,
    )
    viewer_titles = await db.get_user_titles(viewer_id)
    current_tax = calculate_title_tax(settings, viewer_titles)
    if viewer_tax_debt > 0:
        sections.append(
            f"⚠️ Долг по титульному налогу: {viewer_tax_debt} {settings.currency}. Эффекты титулов отключены."
        )
        sections.append("")
    elif current_tax > 0:
        sections.append(
            f"Налог на титулы: {current_tax} {settings.currency} / 24ч (первый титул бесплатный)."
        )
        sections.append("")

    async def add_section(title: str, items_list):
        if not items_list:
            return
        sections.append(f"{title}:")
        compact = category == "all"
        for it in items_list:
            status = ""
            if it.kind == "title":
                owner = await db.get_title_owner(it.id)
                if owner is not None:
                    if owner == viewer_id:
                        status = " (у тебя)"
                    else:
                        status = " (занято)"
            duration = ""
            if it.duration_seconds:
                duration = f" ({format_duration(it.duration_seconds)})"
            price = it.price
            if it.kind == "protection":
                price = get_discounted_price(price, viewer_effect.protection_discount_bp)
            line = (
                f"• {it.id} — {it.name} — {price} {settings.currency}{status}{duration}"
            )
            if it.kind == "protection" and price < it.price:
                line += f" (вместо {it.price})"
            sections.append(line)
            if not compact and it.description:
                sections.append(f"Описание: {it.description}")
            if not compact and it.kind == "title":
                for effect_line in describe_title_effects(settings, it.id):
                    sections.append(f"Эффект: {effect_line}.")
        sections.append("")

    if category == "punish":
        await add_section("Наказания", list_punishment_items(settings))
    elif category == "protect":
        await add_section("Защиты", list_protection_items(settings))
    elif category == "title":
        await add_section("Титулы", list_title_items(settings))
    else:
        await add_section("Наказания", list_punishment_items(settings))
        await add_section("Защиты", list_protection_items(settings))
        await add_section("Титулы", list_title_items(settings))

    sections.append("Покупка: /buy <item_id> (для наказаний — ответом на сообщение)")
    sections.append("Подробности: /help_shop")
    sections.append("ℹ️ Наказания применяются только в группах.")
    return "\n".join(sections)


async def process_buy(
    message: Message,
    db: Database,
    settings: Settings,
    item,
    raw_args: Optional[str],
) -> None:
    if item.kind in ("ban", "mute"):
        if message.chat.type == "private":
            await message.answer("Наказания можно применять только в группах")
            return
        target = await resolve_target_user(message, raw_args)
        if target is None:
            await message.answer("Нужно ответить на сообщение цели: /buy <item_id>")
            return
        if getattr(target, "is_bot", False):
            await message.answer("Нельзя применить к боту")
            return
        if target.id == message.from_user.id:
            await message.answer("Нельзя применить к себе")
            return
        if not await db.user_exists(target.id):
            await message.answer("У цели нет профиля. Ему нужно написать /start")
            return

        active_prot = await get_active_protections(db, target.id)
        if active_prot:
            await message.answer("У цели активна защита — наказание не применено")
            return

        try:
            bot_member = await message.bot.get_chat_member(message.chat.id, message.bot.id)
        except Exception:
            await message.answer("Не удалось проверить права бота в чате")
            return
        if bot_member.status not in ("administrator", "creator"):
            await message.answer("Бот должен быть администратором, чтобы применять наказания")
            return
        if item.kind in ("ban", "mute"):
            can_restrict = True if bot_member.status == "creator" else bool(
                getattr(bot_member, "can_restrict_members", False)
            )
            if not can_restrict:
                await message.answer("Нужно право ограничивать пользователей (can_restrict_members)")
                return

        try:
            member = await message.bot.get_chat_member(message.chat.id, target.id)
            if member.status in ("administrator", "creator"):
                await message.answer("Нельзя применять наказание к администратору или создателю")
                return
        except Exception:
            await message.answer("Не удалось проверить права пользователя")
            return

        if not await db.try_withdraw(message.from_user.id, item.price):
            await message.answer("Недостаточно средств для покупки. Баланс — /profile.")
            return

        duration = item.duration_seconds or 0
        now_dt = datetime.now(timezone.utc)
        expires_at = now_dt + timedelta(seconds=duration)
        expires_iso = expires_at.isoformat()
        started_at = now_dt.isoformat()

        if item.kind == "ban":
            try:
                ban_until = expires_at
                min_restrict = settings.telegram_min_restrict_seconds
                if duration and duration < min_restrict:
                    ban_until = now_dt + timedelta(seconds=min_restrict)
                await message.bot.ban_chat_member(
                    message.chat.id,
                    target.id,
                    until_date=ban_until,
                )
            except Exception:
                await db.deposit(message.from_user.id, item.price)
                await message.answer("Не удалось применить бан. Средства возвращены")
                return

            await db.add_ban(
                message.chat.id,
                target.id,
                expires_iso,
                started_at=started_at,
                duration_seconds=duration,
            )
            target_title = await get_user_title(db, settings, target.id)
            await message.answer(
                f"🚫 {format_user(target, target_title)} забанен на {format_duration(duration)}"
            )
            return

        mute_perms = ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
            can_change_info=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_topics=False,
        )
        try:
            mute_until = expires_at
            min_restrict = settings.telegram_min_restrict_seconds
            if duration and duration < min_restrict:
                mute_until = now_dt + timedelta(seconds=min_restrict)
            await message.bot.restrict_chat_member(
                message.chat.id,
                target.id,
                permissions=mute_perms,
                until_date=mute_until,
            )
        except Exception:
            await db.deposit(message.from_user.id, item.price)
            await message.answer("Не удалось применить мут. Средства возвращены")
            return

        await db.add_mute(
            message.chat.id,
            target.id,
            expires_iso,
            started_at=started_at,
            duration_seconds=duration,
        )
        target_title = await get_user_title(db, settings, target.id)
        await message.answer(
            f"🔇 {format_user(target, target_title)} получил мут на {format_duration(duration)}"
        )
        return

    if item.kind == "protection":
        buyer = await db.get_user(message.from_user.id)
        buyer_tax_debt = await get_title_tax_debt_amount(db, message.from_user.id)
        title_effect = get_title_effect(
            settings,
            buyer.active_title_id if buyer else None,
            effects_enabled=buyer_tax_debt <= 0,
        )
        price = get_discounted_price(item.price, title_effect.protection_discount_bp)
        duration = item.duration_seconds or 0
        now_dt = datetime.now(timezone.utc)
        new_exp = None
        status = "ok"
        async with db.transaction() as conn:
            cur = await conn.execute(
                "UPDATE users SET balance = balance - ?, updated_at = ? WHERE user_id = ? AND balance >= ?",
                (price, now_dt.isoformat(), message.from_user.id, price),
            )
            if cur.rowcount != 1:
                status = "no_funds"
            else:
                cur = await conn.execute(
                    "SELECT expires_at FROM protections WHERE user_id = ? AND protection_id = ?",
                    (message.from_user.id, item.id),
                )
                row = await cur.fetchone()
                base = now_dt
                if row:
                    try:
                        current = datetime.fromisoformat(row["expires_at"])
                        if current > base:
                            base = current
                    except Exception:
                        pass
                new_exp = base + timedelta(seconds=duration)
                await conn.execute(
                    """
                    INSERT INTO protections (user_id, protection_id, expires_at, created_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, protection_id)
                    DO UPDATE SET expires_at = excluded.expires_at
                    """,
                    (message.from_user.id, item.id, new_exp.isoformat(), utc_now()),
                )

        if status == "no_funds":
            await message.answer("Недостаточно средств для покупки. Баланс — /profile.")
            return
        if new_exp is None:
            await message.answer("Не удалось активировать защиту")
            return
        lines = [
            f"🛡 Защита активирована на {format_duration(duration)}.",
            f"Осталось {format_duration(seconds_until(new_exp.isoformat()))}.",
            f"Стоимость: {price} {settings.currency}.",
        ]
        if title_effect.protection_discount_bp > 0 and price < item.price:
            lines.append(
                f"Скидка титула: -{format_percent_bp(title_effect.protection_discount_bp)}."
            )
        await message.answer("\n".join(lines))
        return

    if item.kind == "title":
        debt_amount = await get_title_tax_debt_amount(db, message.from_user.id)
        if debt_amount > 0:
            await message.answer(
                f"Сначала погаси долг по титульному налогу: {debt_amount} {settings.currency}."
            )
            return
        result = "ok"
        async with db.transaction() as conn:
            cur = await conn.execute(
                "SELECT owner_id FROM title_ownership WHERE title_id = ?",
                (item.id,),
            )
            row = await cur.fetchone()
            if row:
                owner_id = int(row["owner_id"])
                if owner_id == message.from_user.id:
                    result = "already"
                else:
                    result = "taken"
            else:
                cur2 = await conn.execute(
                    "UPDATE users SET balance = balance - ?, updated_at = ? WHERE user_id = ? AND balance >= ?",
                    (item.price, utc_now(), message.from_user.id, item.price),
                )
                if cur2.rowcount != 1:
                    result = "no_funds"
                else:
                    await conn.execute(
                        "INSERT INTO title_ownership (title_id, owner_id, purchased_at) VALUES (?, ?, ?)",
                        (item.id, message.from_user.id, utc_now()),
                    )
                    await conn.execute(
                        "UPDATE users SET active_title_id = ?, updated_at = ? WHERE user_id = ?",
                        (item.id, utc_now(), message.from_user.id),
                    )

        if result == "taken":
            await message.answer("Этот титул уже куплен другим игроком")
            return
        if result == "already":
            await message.answer("Этот титул уже у тебя")
            return
        if result == "no_funds":
            await message.answer("Недостаточно средств для покупки. Баланс — /profile.")
            return

        title_text = item.title_text or item.name
        effect_text = format_title_effects(settings, item.id)
        await message.answer(
            f"🏷 Титул «{title_text}» куплен и выбран активным.\n"
            f"Эффекты: {effect_text}\n"
            "Сменить: /set_title"
        )
        return

    await message.answer("Неизвестный тип товара")
