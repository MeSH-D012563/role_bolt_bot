from __future__ import annotations

from datetime import datetime, timezone


def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def seconds_until(ts: str) -> int:
    try:
        target = parse_iso(ts)
    except Exception:
        return 0
    delta = target - utc_now()
    return max(int(delta.total_seconds()), 0)


def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0 сек"
    mins, sec = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    parts = []
    if hours:
        parts.append(f"{hours} ч")
    if mins:
        parts.append(f"{mins} мин")
    if sec or not parts:
        parts.append(f"{sec} сек")
    return " ".join(parts)
