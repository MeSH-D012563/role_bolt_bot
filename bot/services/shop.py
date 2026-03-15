from __future__ import annotations

from typing import Iterable

from bot.config import Settings, ShopItem


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


def get_title_bonus_bp(settings: Settings, title_id: str | None) -> int:
    if not title_id:
        return 0
    return settings.title_bonus_bp.get(title_id, 0)


def list_title_items(settings: Settings) -> list[ShopItem]:
    return [item for item in settings.shop_items if item.kind == "title"]


def list_punishment_items(settings: Settings) -> list[ShopItem]:
    return [item for item in settings.shop_items if item.kind in ("ban", "mute")]


def list_protection_items(settings: Settings) -> list[ShopItem]:
    return [item for item in settings.shop_items if item.kind == "protection"]


def list_punishment_items(settings: Settings) -> list[ShopItem]:
    return [item for item in settings.shop_items if item.kind in ("ban", "mute")]


def category_items(settings: Settings, category: str) -> list[ShopItem]:
    if category == "title":
        return list_title_items(settings)
    if category == "protect":
        return list_protection_items(settings)
    if category == "punish":
        return list_punishment_items(settings)
    return list(settings.shop_items)
