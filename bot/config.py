from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ShopItem:
    id: str
    name: str
    price: int
    kind: str  # ban, mute, title, protection
    duration_seconds: Optional[int] = None
    description: str = ""
    title_text: Optional[str] = None


@dataclass(frozen=True)
class Settings:
    bot_token: str
    db_path: str = "data/bot.db"
    start_balance: int = 200
    currency: str = "bolt_coin"

    # Betting limits
    min_bet: int = 1
    max_bet: int = 1_000_000

    # Animation delays (seconds)
    animation_delay: float = 2.0

    # Simple rate limit for commands/callbacks (seconds). Set to 0 to disable.
    rate_limit_seconds: float = 1.5

    # Slot payouts by symbol for 🎰 (3 in a row only)
    # multiplier in basis points (100 = x1.0)
    slot_symbol_payouts: dict[str, tuple[int, str]] = field(
        default_factory=lambda: {
            "seven": (700, "Джекпот x7"),
            "bar": (400, "BAR x4"),
            "cherry": (260, "Вишни x2.6"),
            "lemon": (140, "Лимоны x1.4"),
        }
    )
    # Slot payouts for 2 in a row
    slot_pair_payouts: dict[str, tuple[int, str]] = field(
        default_factory=lambda: {
            "seven": (190, "Пара 7 x1.9"),
            "bar": (150, "Пара BAR x1.5"),
            "cherry": (130, "Пара 🍒 x1.3"),
            "lemon": (120, "Пара 🍋 x1.2"),
        }
    )

    # Basketball: dice.value for 🏀 is 1..5
    basket_success_values: tuple[int, ...] = (4, 5)
    basket_multiplier_bp: int = 260  # x2.6

    # Duel settings
    duel_ttl_seconds: int = 120
    duel_check_interval_seconds: int = 10

    # Daily reward
    daily_cash_amount: int = 75
    daily_cash_cooldown_seconds: int = 12 * 60 * 60

    # Telegram API limits: bans shorter than ~30s can be treated as permanent
    telegram_min_restrict_seconds: int = 30

    # Cleanup loops
    mute_check_interval_seconds: int = 10
    ban_invite_link_ttl_seconds: int = 3600

    # Shop settings
    ban_check_interval_seconds: int = 10
    shop_items: tuple[ShopItem, ...] = (
        ShopItem(
            id="ban_10",
            name="Бан на 10 секунд",
            price=200,
            kind="ban",
            duration_seconds=10,
            description="Временно блокирует пользователя в чате.",
        ),
        ShopItem(
            id="ban_30",
            name="Бан на 30 секунд",
            price=400,
            kind="ban",
            duration_seconds=30,
            description="Блокировка пользователя на 30 секунд.",
        ),
        ShopItem(
            id="ban_60",
            name="Бан на 1 минуту",
            price=700,
            kind="ban",
            duration_seconds=60,
            description="Блокировка пользователя на 1 минуту.",
        ),
        ShopItem(
            id="ban_120",
            name="Бан на 2 минуты",
            price=1200,
            kind="ban",
            duration_seconds=120,
            description="Блокировка пользователя на 2 минуты.",
        ),
        ShopItem(
            id="ban_300",
            name="Бан на 5 минут",
            price=2500,
            kind="ban",
            duration_seconds=300,
            description="Блокировка пользователя на 5 минут.",
        ),
        ShopItem(
            id="ban_600",
            name="Бан на 10 минут",
            price=4500,
            kind="ban",
            duration_seconds=600,
            description="Блокировка пользователя на 10 минут.",
        ),
        ShopItem(
            id="ban_1800",
            name="Бан на 30 минут",
            price=10000,
            kind="ban",
            duration_seconds=1800,
            description="Блокировка пользователя на 30 минут.",
        ),
        ShopItem(
            id="mute_10",
            name="Мут на 10 секунд",
            price=120,
            kind="mute",
            duration_seconds=10,
            description="Запрещает пользователю отправлять сообщения на время.",
        ),
        ShopItem(
            id="mute_30",
            name="Мут на 30 секунд",
            price=250,
            kind="mute",
            duration_seconds=30,
            description="Запрещает пользователю отправлять сообщения 30 секунд.",
        ),
        ShopItem(
            id="mute_60",
            name="Мут на 1 минуту",
            price=450,
            kind="mute",
            duration_seconds=60,
            description="Запрещает пользователю отправлять сообщения 1 минуту.",
        ),
        ShopItem(
            id="mute_120",
            name="Мут на 2 минуты",
            price=800,
            kind="mute",
            duration_seconds=120,
            description="Запрещает пользователю отправлять сообщения 2 минуты.",
        ),
        ShopItem(
            id="mute_300",
            name="Мут на 5 минут",
            price=1700,
            kind="mute",
            duration_seconds=300,
            description="Запрещает пользователю отправлять сообщения 5 минут.",
        ),
        ShopItem(
            id="mute_600",
            name="Мут на 10 минут",
            price=3000,
            kind="mute",
            duration_seconds=600,
            description="Запрещает пользователю отправлять сообщения 10 минут.",
        ),
        ShopItem(
            id="mute_1800",
            name="Мут на 30 минут",
            price=7000,
            kind="mute",
            duration_seconds=1800,
            description="Запрещает пользователю отправлять сообщения 30 минут.",
        ),
        ShopItem(
            id="shield_60",
            name="Защита на 60 секунд",
            price=180,
            kind="protection",
            duration_seconds=60,
            description="Защищает от банов и мутов.",
        ),
        ShopItem(
            id="shield_300",
            name="Защита на 5 минут",
            price=650,
            kind="protection",
            duration_seconds=300,
            description="Защищает от банов и мутов.",
        ),
        ShopItem(
            id="shield_900",
            name="Защита на 15 минут",
            price=1600,
            kind="protection",
            duration_seconds=900,
            description="Защищает от банов и мутов.",
        ),
        ShopItem(
            id="title_wanderer",
            name="Титул: Странник",
            price=400,
            kind="title",
            description="Уникальный титул, доступен только одному игроку.",
            title_text="Странник",
        ),
        ShopItem(
            id="title_pioneer",
            name="Титул: Пионер",
            price=550,
            kind="title",
            description="Уникальный титул, доступен только одному игроку.",
            title_text="Пионер",
        ),
        ShopItem(
            id="title_hawk",
            name="Титул: Ястреб",
            price=700,
            kind="title",
            description="Уникальный титул, доступен только одному игроку.",
            title_text="Ястреб",
        ),
        ShopItem(
            id="title_shadow",
            name="Титул: Тень",
            price=850,
            kind="title",
            description="Уникальный титул, доступен только одному игроку.",
            title_text="Тень",
        ),
        ShopItem(
            id="title_marauder",
            name="Титул: Мародер",
            price=1000,
            kind="title",
            description="Уникальный титул, доступен только одному игроку.",
            title_text="Мародер",
        ),
        ShopItem(
            id="title_archon",
            name="Титул: Архонт",
            price=1300,
            kind="title",
            description="Уникальный титул, доступен только одному игроку.",
            title_text="Архонт",
        ),
        ShopItem(
            id="title_legend",
            name="Титул: Легенда",
            price=1400,
            kind="title",
            description="Редкий уникальный титул, доступен только одному игроку.",
            title_text="Легенда",
        ),
    )
    # Title bonuses (basis points, 100 = 1%)
    title_bonus_bp: dict[str, int] = field(
        default_factory=lambda: {
            "title_wanderer": 100,
            "title_pioneer": 150,
            "title_hawk": 200,
            "title_shadow": 250,
            "title_marauder": 300,
            "title_archon": 350,
            "title_legend": 400,
        }
    )



def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in environment")
    return Settings(bot_token=token)
