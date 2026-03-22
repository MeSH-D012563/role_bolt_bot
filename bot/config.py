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
class TitleEffect:
    slot_bonus_bp: int = 0
    basket_bonus_bp: int = 0
    loss_refund_bp: int = 0
    daily_bonus_amount: int = 0
    protection_discount_bp: int = 0


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
            "seven": (620, "Джекпот x6.2"),
            "bar": (380, "BAR x3.8"),
            "cherry": (260, "Вишни x2.6"),
            "lemon": (160, "Лимоны x1.6"),
        }
    )
    # Slot payouts for 2 in a row
    slot_pair_payouts: dict[str, tuple[int, str]] = field(
        default_factory=lambda: {
            "seven": (155, "Пара 7 x1.55"),
            "bar": (135, "Пара BAR x1.35"),
            "cherry": (115, "Пара 🍒 x1.15"),
            "lemon": (100, "Пара 🍋 x1.0"),
        }
    )

    # Basketball: dice.value for 🏀 is 1..5
    basket_success_values: tuple[int, ...] = (4, 5)
    basket_multiplier_bp: int = 235  # x2.35

    # Duel settings
    duel_ttl_seconds: int = 120
    duel_check_interval_seconds: int = 10

    # Daily reward
    daily_cash_amount: int = 75
    daily_cash_cooldown_seconds: int = 12 * 60 * 60

    # Title tax
    title_tax_rate_bp: int = 250  # 2.5% from total title value if player owns 2+ titles
    title_tax_period_seconds: int = 24 * 60 * 60
    title_tax_grace_seconds: int = 24 * 60 * 60
    title_tax_check_interval_seconds: int = 60 * 60

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
            price=450,
            kind="title",
            description="Экономический титул для стабильного прироста через ежедневный бонус.",
            title_text="Странник",
        ),
        ShopItem(
            id="title_pioneer",
            name="Титул: Пионер",
            price=650,
            kind="title",
            description="Специализация на слотах с небольшим бонусом к выигрышам.",
            title_text="Пионер",
        ),
        ShopItem(
            id="title_hawk",
            name="Титул: Ястреб",
            price=650,
            kind="title",
            description="Специализация на баскетболе с бонусом к банку при попадании.",
            title_text="Ястреб",
        ),
        ShopItem(
            id="title_shadow",
            name="Титул: Тень",
            price=900,
            kind="title",
            description="Страхует неудачные ходы частичным возвратом ставки.",
            title_text="Тень",
        ),
        ShopItem(
            id="title_marauder",
            name="Титул: Мародер",
            price=950,
            kind="title",
            description="Снижает цену защит и усиливает контроль над темпом игры.",
            title_text="Мародер",
        ),
        ShopItem(
            id="title_archon",
            name="Титул: Архонт",
            price=1250,
            kind="title",
            description="Гибридный титул для экономики и магазина защит.",
            title_text="Архонт",
        ),
        ShopItem(
            id="title_legend",
            name="Титул: Легенда",
            price=1550,
            kind="title",
            description="Продвинутый слот‑титул с прибавкой к ежедневному доходу.",
            title_text="Легенда",
        ),
        ShopItem(
            id="title_oracle",
            name="Титул: Оракул",
            price=1550,
            kind="title",
            description="Продвинутый титул для баскетбола и спокойного фарма.",
            title_text="Оракул",
        ),
        ShopItem(
            id="title_phantom",
            name="Титул: Фантом",
            price=1900,
            kind="title",
            description="Агрессивный гибрид слота и страховки от неудач.",
            title_text="Фантом",
        ),
        ShopItem(
            id="title_overlord",
            name="Титул: Владыка",
            price=2200,
            kind="title",
            description="Усиливает баскетбол и даёт максимальную скидку на защиты.",
            title_text="Владыка",
        ),
        ShopItem(
            id="title_sovereign",
            name="Титул: Суверен",
            price=2600,
            kind="title",
            description="Универсальный титул для обеих PvE‑игр.",
            title_text="Суверен",
        ),
        ShopItem(
            id="title_immortal",
            name="Титул: Бессмертный",
            price=3200,
            kind="title",
            description="Самый гибкий титул: понемногу усиливает все мирные способы заработка.",
            title_text="Бессмертный",
        ),
    )
    title_effects: dict[str, TitleEffect] = field(
        default_factory=lambda: {
            "title_wanderer": TitleEffect(daily_bonus_amount=10),
            "title_pioneer": TitleEffect(slot_bonus_bp=125),
            "title_hawk": TitleEffect(basket_bonus_bp=125),
            "title_shadow": TitleEffect(loss_refund_bp=200),
            "title_marauder": TitleEffect(protection_discount_bp=1000),
            "title_archon": TitleEffect(daily_bonus_amount=15, protection_discount_bp=500),
            "title_legend": TitleEffect(slot_bonus_bp=200, daily_bonus_amount=10),
            "title_oracle": TitleEffect(basket_bonus_bp=200, daily_bonus_amount=10),
            "title_phantom": TitleEffect(slot_bonus_bp=100, loss_refund_bp=300),
            "title_overlord": TitleEffect(basket_bonus_bp=100, protection_discount_bp=1500),
            "title_sovereign": TitleEffect(slot_bonus_bp=150, basket_bonus_bp=150),
            "title_immortal": TitleEffect(
                slot_bonus_bp=200,
                basket_bonus_bp=200,
                loss_refund_bp=100,
                daily_bonus_amount=15,
            ),
        }
    )



def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is not set in environment")
    return Settings(bot_token=token)
