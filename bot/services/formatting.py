from __future__ import annotations

from typing import Any

from aiogram.types import User


def _apply_title(name: str, title: str | None) -> str:
    if title:
        return f"{title} {name}"
    return name


def format_username(username: str | None, user_id: int, title: str | None = None) -> str:
    if username:
        return _apply_title(f"@{username}", title)
    return _apply_title(f"id:{user_id}", title)


def format_user(user: Any, title: str | None = None) -> str:
    username = getattr(user, "username", None)
    if username:
        return _apply_title(f"@{username}", title)

    first_name = getattr(user, "first_name", "") or ""
    last_name = getattr(user, "last_name", "") or ""
    full_name = (f"{first_name} {last_name}").strip()
    if full_name:
        return _apply_title(full_name, title)

    user_id = getattr(user, "id", None)
    if user_id is not None:
        return _apply_title(f"id:{user_id}", title)

    return _apply_title("пользователь", title)


def format_percent_bp(bp: int) -> str:
    if bp <= 0:
        return "0%"
    whole = bp // 100
    frac = bp % 100
    if frac == 0:
        return f"{whole}%"
    value = bp / 100
    return f"{value:.1f}%".rstrip("0").rstrip(".")
