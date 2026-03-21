from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import Message

TELEGRAM_TEXT_LIMIT = 4096
SAFE_TEXT_LIMIT = 4000


def split_message_text(text: str, limit: int = SAFE_TEXT_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""

    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        remaining = line
        while len(remaining) > limit:
            split_at = remaining.rfind(" ", 0, limit)
            if split_at <= 0:
                split_at = limit
            chunks.append(remaining[:split_at].rstrip())
            remaining = remaining[split_at:].lstrip()
        current = remaining

    if current:
        chunks.append(current)

    return chunks or [text[:limit]]


async def answer_in_chunks(
    message: Message,
    text: str,
    *,
    reply_markup=None,
    **kwargs,
) -> Sequence[Message]:
    chunks = split_message_text(text)
    sent_messages: list[Message] = []

    for index, chunk in enumerate(chunks):
        sent = await message.answer(
            chunk,
            reply_markup=reply_markup if index == 0 else None,
            **(kwargs if index == 0 else {}),
        )
        sent_messages.append(sent)

    return sent_messages

