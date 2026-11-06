"""Record why a walked RFQ key did not draft a pin (gap ledger transparency)."""

from __future__ import annotations

from typing import Any

# Harvest must never leave a walked key without a skip reason before the ledger write.
WALK_WITHOUT_OUTCOME = "walk_without_outcome"
ALIASES_COMPLETE = "aliases_complete"


def walk_skip_reason(row: dict[str, Any] | None) -> str:
    """Reason when a walk drafted neither a pin nor a skip row."""
    if row is not None:
        kind = str(row.get("kind") or "").strip()
        if kind:
            return kind
    return ALIASES_COMPLETE


def pin_harvest_pairs(pin: dict[str, Any]) -> set[tuple[str, str]]:
    """Every RFQ key this pin covers, including keys folded in from another book."""
    return set(_harvest_pairs(pin))


def remember_harvest_key(keep: dict[str, Any], drop: dict[str, Any]) -> None:
    """Keep the dropped pin's RFQ keys on the leader so the ledger still counts them pinned."""
    pairs = _harvest_pairs(keep)
    for item in _harvest_pairs(drop):
        if item not in pairs:
            pairs.append(item)
    if not pairs:
        return
    _write_pairs(keep, pairs)


def take_harvest_pin(
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    seen: set[tuple[str, str, str]],
    pin: dict[str, Any],
    *,
    identity: Any,
    merge_league: Any,
) -> None:
    """Keep one pin per identity, and keep every RFQ key the dropped pin covered."""
    ident = identity(pin)
    if ident is None:
        _skip_unidentified(pin, skipped)
        return
    if ident not in seen:
        seen.add(ident)
        pins.append(pin)
        return
    _absorb_duplicate(pins, pin, ident, identity, merge_league)


def _harvest_pairs(pin: dict[str, Any]) -> list[tuple[str, str]]:
    stored = pin.get("harvest_pairs")
    if isinstance(stored, list) and stored:
        return _pairs_from_stored(stored)
    return _pairs_from_legacy(pin)


def _pairs_from_stored(stored: list[Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in stored:
        if not isinstance(item, dict):
            continue
        book = str(item.get("book") or "").strip()
        key = str(item.get("key") or "").strip()
        if book and key and (book, key) not in out:
            out.append((book, key))
    return out


def _pairs_from_legacy(pin: dict[str, Any]) -> list[tuple[str, str]]:
    book = str(pin.get("harvest_book") or pin.get("book") or "").strip()
    primary = str(pin.get("harvest_key") or pin.get("gap_key") or "").strip()
    keys = [str(item).strip() for item in (pin.get("harvest_keys") or [])]
    if primary:
        keys.append(primary)
    out: list[tuple[str, str]] = []
    for key in keys:
        if book and key and (book, key) not in out:
            out.append((book, key))
    return out


def _write_pairs(keep: dict[str, Any], pairs: list[tuple[str, str]]) -> None:
    keep["harvest_pairs"] = [{"book": book, "key": key} for book, key in pairs]
    keep["harvest_keys"] = [key for _, key in pairs]
    if not str(keep.get("harvest_book") or "").strip():
        keep["harvest_book"] = pairs[0][0]
    if not str(keep.get("harvest_key") or "").strip():
        keep["harvest_key"] = pairs[0][1]
        keep["gap_key"] = pairs[0][1]


def _skip_unidentified(pin: dict[str, Any], skipped: list[dict[str, str]]) -> None:
    for book, key in pin_harvest_pairs(pin):
        skipped.append({"book": book, "key": key, "reason": ALIASES_COMPLETE})


def _absorb_duplicate(
    pins: list[dict[str, Any]],
    pin: dict[str, Any],
    ident: tuple[str, str, str],
    identity: Any,
    merge_league: Any,
) -> None:
    leader = next((row for row in pins if identity(row) == ident), None)
    if leader is not None:
        if ident[0] != "mapping_league":
            _fold_aliases(leader, pin)
        remember_harvest_key(leader, pin)
    if ident[0] == "mapping_league":
        merge_league(pins, pin, ident)


def _fold_aliases(keep: dict[str, Any], drop: dict[str, Any]) -> None:
    # gap_fix_optic_merge imports this module.
    from mappers.control_plane.gap_fix_optic_merge import fold_pin_aliases

    fold_pin_aliases(keep, drop)


def ensure_walk_recorded(
    book: str,
    key: str,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
    before_pins: int,
    before_skip: int,
    *,
    row: dict[str, Any] | None = None,
) -> None:
    """Append a skip row when this walked key produced no pin and no skip of its own."""
    if not book or not key:
        return
    if _key_recorded(book, key, pins[before_pins:], skipped[before_skip:]):
        return
    skipped.append({"book": book, "key": key, "reason": walk_skip_reason(row)})


def _key_recorded(
    book: str,
    key: str,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
) -> bool:
    ident = (book, key)
    if any(ident in pin_harvest_pairs(pin) for pin in pins):
        return True
    return any(_skip_ident(row) == ident for row in skipped)


def _skip_ident(row: dict[str, str]) -> tuple[str, str]:
    book = str(row.get("book") or "").strip()
    key = str(row.get("key") or row.get("event_ticker") or row.get("symbol") or "")
    return book, key


def reconcile_walked_skips(
    walked: set[tuple[str, str]],
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
) -> None:
    """Safety net: every walked key must have a pin or a skip before ledger."""
    if not walked:
        return
    pinned = _harvest_pin_keys(pins)
    skip_keys = {
        (
            str(row.get("book") or "").strip(),
            str(row.get("key") or row.get("event_ticker") or row.get("symbol") or ""),
        )
        for row in skipped
        if str(row.get("book") or "").strip()
    }
    for book, key in sorted(walked):
        if not key:
            continue
        if (book, key) in pinned or (book, key) in skip_keys:
            continue
        skipped.append({"book": book, "key": key, "reason": WALK_WITHOUT_OUTCOME})


def _harvest_pin_keys(pins: list[dict[str, Any]]) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for pin in pins:
        out.update(pin_harvest_pairs(pin))
    return out
