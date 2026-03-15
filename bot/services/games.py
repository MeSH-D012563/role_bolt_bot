from __future__ import annotations

from bot.config import Settings


SLOT_CODE_TO_SYMBOL = {
    0: "bar",
    1: "cherry",
    2: "lemon",
    3: "seven",
}

SLOT_SYMBOL_EMOJI = {
    "bar": "BAR",
    "cherry": "🍒",
    "lemon": "🍋",
    "seven": "7️⃣",
}


def _decode_slot_symbols(value: int) -> list[str]:
    if value < 1 or value > 64:
        return ["unknown", "unknown", "unknown"]
    v = value - 1
    codes = [v & 3, (v >> 2) & 3, (v >> 4) & 3]
    return [SLOT_CODE_TO_SYMBOL.get(c, "unknown") for c in codes]


def evaluate_slot(value: int, settings: Settings) -> tuple[int, str]:
    symbols = _decode_slot_symbols(value)
    counts: dict[str, int] = {}
    for s in symbols:
        counts[s] = counts.get(s, 0) + 1

    if len(set(symbols)) == 1:
        symbol = symbols[0]
        payout = settings.slot_symbol_payouts.get(symbol)
        if not payout:
            return 0, "Промах"
        multiplier_bp, label = payout
        emoji = SLOT_SYMBOL_EMOJI.get(symbol, symbol)
        return multiplier_bp, f"{emoji} {label}"

    pair_symbol = None
    for sym, cnt in counts.items():
        if cnt == 2:
            pair_symbol = sym
            break

    if pair_symbol:
        payout = settings.slot_pair_payouts.get(pair_symbol)
        if not payout:
            return 0, "Промах"
        multiplier_bp, label = payout
        emoji = SLOT_SYMBOL_EMOJI.get(pair_symbol, pair_symbol)
        return multiplier_bp, f"{emoji} {label}"

    return 0, "Промах"


def basket_is_success(value: int, settings: Settings) -> bool:
    return value in settings.basket_success_values


def calc_payout(bet: int, multiplier_bp: int) -> int:
    return (bet * multiplier_bp) // 100
