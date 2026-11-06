"""Shared yes/no/select words for Mapper Chat confirm paths."""

from __future__ import annotations

YES = frozenset({
    "yes", "y", "ok", "okay", "add to cart", "confirm", "do it", "add all",
})
NO = frozenset({"no", "n", "not now", "cancel", "discard"})
PREFILL_SEND = frozenset({"prefill", "prefill entry", "prefill editor"})


def is_yes(message: str) -> bool:
    return message.strip().lower() in YES


def is_no(message: str) -> bool:
    return message.strip().lower() in NO


def is_select(message: str) -> bool:
    return message.strip().lower().startswith("select:")


def select_id(message: str) -> str:
    return message.split(":", 1)[1].strip()
