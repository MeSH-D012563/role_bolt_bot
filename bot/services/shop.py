from __future__ import annotations

from typing import Iterable

from bot.config import Settings, ShopItem, TitleEffect
from bot.services.formatting import format_percent_bp


def get_item(settings: Settings, item_id: str) -> ShopItem | None:
    for item in settings.shop_items:
        if item.id == item_id:
            return item
    return None


def iter_items(settings: Settings) -> Iterable[ShopItem]:
    return settings.shop_items


def get_title_text(settings: Settings, title_id: str | None) -> str | None:
    if not title_id:
        return None
    for item in settings.shop_items:
        if item.id == title_id and item.kind == "title":
            return item.title_text or item.name
    return None


def get_title_effect(
    settings: Settings,
    title_id: str | None,
    *,
    effects_enabled: bool = True,
) -> TitleEffect:
    if not title_id or not effects_enabled:
        return TitleEffect()
    return settings.title_effects.get(title_id, TitleEffect())


def get_title_price(settings: Settings, title_id: str | None) -> int:
    item = get_item(settings, title_id or "")
    if item is None or item.kind != "title":
        return 0
    return item.price


def describe_title_effects(settings: Settings, title_id: str | None) -> list[str]:
    effect = get_title_effect(settings, title_id)
    parts: list[str] = []
    if effect.slot_bonus_bp > 0:
        parts.append(f"слот +{format_percent_bp(effect.slot_bonus_bp)} к выплатам")
    if effect.basket_bonus_bp > 0:
        parts.append(f"баскет +{format_percent_bp(effect.basket_bonus_bp)} к банку")
    if effect.loss_refund_bp > 0:
        parts.append(
            f"возврат {format_percent_bp(effect.loss_refund_bp)} ставки при проигрыше"
        )
    if effect.daily_bonus_amount > 0:
        parts.append(f"+{effect.daily_bonus_amount} {settings.currency} к /get_cash")
    if effect.protection_discount_bp > 0:
        parts.append(f"защиты -{format_percent_bp(effect.protection_discount_bp)}")
    return parts


def format_title_effects(settings: Settings, title_id: str | None) -> str:
    parts = describe_title_effects(settings, title_id)
    if not parts:
        return "без эффектов"
    return ", ".join(parts)


def get_discounted_price(price: int, discount_bp: int) -> int:
    if discount_bp <= 0:
        return price
    discounted = (price * (10000 - discount_bp)) // 10000
    return max(discounted, 1)


def calculate_title_tax(settings: Settings, title_ids: list[str]) -> int:
    if len(title_ids) <= 1:
        return 0
    total_value = sum(get_title_price(settings, title_id) for title_id in title_ids)
    if total_value <= 0:
        return 0
    return max((total_value * settings.title_tax_rate_bp + 9999) // 10000, 1)


def pick_confiscation_title(
    settings: Settings,
    title_ids: list[str],
    active_title_id: str | None,
) -> str | None:
    if not title_ids:
        return None
    pool = [title_id for title_id in title_ids if title_id != active_title_id]
    if not pool:
        pool = list(title_ids)
    pool.sort(key=lambda title_id: (get_title_price(settings, title_id), title_id), reverse=True)
    return pool[0] if pool else None


def list_title_items(settings: Settings) -> list[ShopItem]:
    return [item for item in settings.shop_items if item.kind == "title"]


def list_punishment_items(settings: Settings) -> list[ShopItem]:
    return [item for item in settings.shop_items if item.kind in ("ban", "mute")]


def list_protection_items(settings: Settings) -> list[ShopItem]:
    return [item for item in settings.shop_items if item.kind == "protection"]


def category_items(settings: Settings, category: str) -> list[ShopItem]:
    if category == "title":
        return list_title_items(settings)
    if category == "protect":
        return list_protection_items(settings)
    if category == "punish":
        return list_punishment_items(settings)
    return list(settings.shop_items)
