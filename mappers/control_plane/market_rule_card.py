"""One presentation for a market-rule pin: venue, transform, Optic.

Presentation only. No lookup, no bind, no census. Gap proposer, Mapper Chat,
Unmapped Why, Editor, Cart, Proposed, Rules, and Approve/history call this
instead of formatting the bands themselves.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from mappers.control_plane.league_review import book_label
from mappers.control_plane.models import MappingMarketRulesPayload, MarketRulePin
from mappers.control_plane.rows import MarketRuleRow

_Pin = MarketRulePin | MarketRuleRow | Mapping[str, Any]

_PT_RE = re.compile(r"(\d+)pt(\d+)")
_EXAMPLE_PREFIXES = (
    "polymarket_usa:ticker:",
    "crypto:symbol:",
    "polymarket:slug:",
)
_LINE_PREFIXES = ("polymarket_usa:line:",)
_FLIP = {"under": "over", "over": "under", "yes": "no", "no": "yes"}
_NCAAF_MARK = "NFL slug; no ncaaf slug in hand"


def market_rule_card(
    pin: _Pin,
    *,
    league: str,
    evidence_refs: list[str] | None = None,
    prior: Any | None = None,
) -> dict[str, str]:
    """Venue, transform, and Optic bands plus one cart label."""
    refs = [str(ref) for ref in (evidence_refs or []) if str(ref).strip()]
    book = _text(_get(pin, "sportsbook")).lower()
    source_key = _text(_get(pin, "source_key"))
    action = _text(_get(pin, "action")) or "map"
    canonical = _text(_get(pin, "canonical_market_type"))
    offset = _optional_float(_get(pin, "line_offset"))
    yes_side = _text(_get(pin, "yes_side"))
    side_swap = _optional_bool(_get(pin, "side_swap"))
    operator = _text(_get(pin, "match_operator")) or "exact"
    _ = prior
    example = example_from_refs(refs)
    venue_line = _venue_line_text(refs, example, book)
    resulting_line = _resulting_line(venue_line, offset)
    resulting_side = _resulting_side(yes_side, side_swap)
    coverage = _coverage(source_key, example, operator)
    venue = _venue_band(book, league, source_key, example, venue_line)
    transform = (
        f"offset {_offset_text(offset)} · yes_side {_yes_text(yes_side)}"
        f" · side_swap {_swap_text(side_swap)}"
    )
    optic_name = canonical if action != "ignore" and canonical else "ignored"
    optic = (
        f"{optic_name} · example line {resulting_line} · side {resulting_side}{coverage}"
    )
    return {
        "venue": venue,
        "transform": transform,
        "optic": optic,
        "label": _label(venue, action, canonical, offset, yes_side),
    }


def apply_rule_card(
    row: dict[str, Any],
    pin: MarketRulePin | Mapping[str, Any],
    *,
    league: str,
    evidence_refs: list[str] | None = None,
) -> dict[str, str]:
    """Copy the three bands and the served fields onto a console row."""
    card = market_rule_card(pin, league=league, evidence_refs=evidence_refs)
    row["line_offset"] = _optional_float(_get(pin, "line_offset"))
    row["yes_side"] = _text(_get(pin, "yes_side")) or None
    row["side_swap"] = _optional_bool(_get(pin, "side_swap"))
    row["match_operator"] = _text(_get(pin, "match_operator")) or "exact"
    row["venue"] = card["venue"]
    row["transform"] = card["transform"]
    row["optic"] = card["optic"]
    row["card_label"] = card["label"]
    return card


def notes_with_example(
    trader_note: str | None,
    example: str | None,
    *,
    mark: str | None = None,
) -> str | None:
    """Keep the trader note and put the venue example with it.

    Official description stays its own field. The example is what Rules
    shows after Approve, because ``notes`` is the column that survives.
    """
    note = (trader_note or "").strip()
    piece = _example_piece(example, mark)
    if piece and piece not in note:
        note = f"{note}\n{piece}".strip() if note else piece
    return note or None


def pin_notes(obs: Mapping[str, Any], trader_note: str | None) -> str | None:
    """Trader note plus the venue example carried on the observation."""
    refs = [str(ref) for ref in (obs.get("evidence_refs") or []) if ref]
    example = example_from_refs(refs)
    mark = _ncaaf_mark(str(obs.get("league") or ""), example)
    return notes_with_example(trader_note, example, mark=mark)


def example_from_refs(refs: list[str]) -> str | None:
    """One raw ticker, slug, or symbol from evidence. Empty when absent."""
    for prefix in _EXAMPLE_PREFIXES:
        hit = _tagged(refs, prefix)
        if hit:
            return hit
    return None


def payload_from_market_pin(pin: Mapping[str, Any]) -> MappingMarketRulesPayload:
    """Harvest pin dict to a payload. Context stays out of ``rules``."""
    rules = [MarketRulePin.model_validate(row) for row in (pin.get("rules") or [])]
    context = [MarketRulePin.model_validate(row) for row in (pin.get("context_rules") or [])]
    return MappingMarketRulesPayload(
        league=str(pin.get("league") or ""),
        rules=rules,
        evidence_refs=[str(ref) for ref in (pin.get("evidence_refs") or []) if ref],
        context_rules=context,
    )


def attach_already_mapped_context(
    store: Any,
    pins: list[dict[str, Any]],
    skipped: list[dict[str, str]],
) -> None:
    """Hang already-mapped skips on a real pin. They are not a second proposal."""
    grouped = _already_mapped_by_league(skipped)
    if not grouped:
        return
    rules = _tip_rules(store)
    for pin in pins:
        league = str(pin.get("league") or "")
        extra = grouped.pop(league, [])
        if not extra:
            continue
        context = list(pin.get("context_rules") or [])
        context.extend(_context_pin(skip, rules) for skip in extra)
        pin["context_rules"] = context


def _already_mapped_by_league(
    skipped: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in skipped:
        if str(row.get("reason") or "") != "already_mapped":
            continue
        grouped.setdefault(str(row.get("league") or ""), []).append(row)
    return grouped


def _tip_rules(store: Any) -> list[Any]:
    rid = getattr(store, "current_rule_set_id", None)
    if not rid:
        return []
    return list(store.market_rules_for(rid))


def _context_pin(skip: dict[str, str], rules: list[Any]) -> dict[str, Any]:
    """A display pin copied from the tip. Approve never reads this list."""
    match = _matching_rule(rules, skip)
    canonical = str(skip.get("detail") or "").strip()
    if not canonical and match is not None:
        canonical = _text(getattr(match, "canonical_market_type", None))
    return MarketRulePin(
        sportsbook=str(skip.get("sportsbook") or ""),
        rule_kind="taxonomy",
        source_key_type=str(skip.get("source_key_type") or "") or "market_id",
        source_key=str(skip.get("source_key") or ""),
        action="map",
        canonical_market_type=canonical or None,
        match_operator=_rule_text(match, "match_operator") or "exact",
        notes=_rule_text(match, "notes"),
        line_offset=_optional_float(getattr(match, "line_offset", None)) if match else None,
        yes_side=_rule_text(match, "yes_side"),
        side_swap=_optional_bool(getattr(match, "side_swap", None)) if match else None,
        official_description=_rule_text(match, "official_description"),
        citation_url=_rule_text(match, "citation_url"),
    ).model_dump(mode="json")


def _matching_rule(rules: list[Any], skip: dict[str, str]) -> Any | None:
    league = str(skip.get("league") or "")
    book = str(skip.get("sportsbook") or "").lower()
    key_type = str(skip.get("source_key_type") or "")
    key = str(skip.get("source_key") or "")
    for row in rules:
        if str(getattr(row, "league", "") or "") != league:
            continue
        if str(getattr(row, "sportsbook", "") or "").lower() != book:
            continue
        if str(getattr(row, "source_key_type", "") or "") != key_type:
            continue
        if str(getattr(row, "source_key", "") or "") != key:
            continue
        return row
    return None


def _venue_band(
    book: str,
    league: str,
    source_key: str,
    example: str | None,
    venue_line: str,
) -> str:
    parts = [f"{book_label(book)} {source_key}"]
    if example:
        parts.append(f"example {example}")
    if venue_line != "n/a":
        parts.append(f"line {venue_line}")
    text = " · ".join(parts)
    mark = _ncaaf_mark(league, example)
    if mark:
        text = f"{text} · {mark}"
    return text


def _label(
    venue: str,
    action: str,
    canonical: str,
    offset: float | None,
    yes_side: str,
) -> str:
    head = venue.split(" · ", 1)[0]
    if action == "ignore" or not canonical:
        return f"{head} (ignore)"
    return (
        f"{head} → {canonical} · offset {_offset_text(offset)}"
        f" · yes_side {_yes_text(yes_side)}"
    )


def _coverage(source_key: str, example: str | None, operator: str) -> str:
    blob = f"{source_key} {example or ''}".casefold()
    if "tds-" in blob:
        return " (rule covers tds-0pt5, 2pt5, 4pt5 …)"
    if operator == "prefix" and source_key:
        return f" (rule covers {source_key}…)"
    return ""


def _venue_line_text(refs: list[str], example: str | None, book: str) -> str:
    for prefix in _LINE_PREFIXES:
        hit = _tagged(refs, prefix)
        if hit:
            return _format_line_token(hit) or hit
    if example:
        parsed = _line_from_example(example)
        if parsed:
            return parsed
    return "n/a"


def _line_from_example(example: str) -> str | None:
    pt = _PT_RE.search(example)
    if pt is not None:
        return _format_number(float(f"{pt.group(1)}.{pt.group(2)}"))
    return None


def _resulting_line(venue_line: str, offset: float | None) -> str:
    if offset is None:
        return venue_line
    if venue_line == "n/a":
        return "n/a"
    try:
        return _format_number(float(venue_line) + float(offset))
    except ValueError:
        return "n/a"


def _resulting_side(yes_side: str, side_swap: bool | None) -> str:
    if not yes_side:
        return "unset"
    side = yes_side.strip().lower()
    if side_swap:
        return _FLIP.get(side, side)
    return side


def _ncaaf_mark(league: str, example: str | None) -> str | None:
    slug = (league or "").strip().lower()
    if slug != "ncaaf" or not example:
        return None
    text = example.casefold()
    if "ncaaf" in text or "-cfb-" in text or text.startswith("cfb"):
        return None
    return _NCAAF_MARK


def _example_piece(example: str | None, mark: str | None) -> str:
    raw = (example or "").strip()
    if raw and mark:
        return f"example: {raw} ({mark})"
    if raw:
        return f"example: {raw}"
    return ""


def _offset_text(offset: float | None) -> str:
    if offset is None:
        return "none"
    return _format_number(offset)


def _yes_text(yes_side: str) -> str:
    return yes_side.strip().lower() if yes_side.strip() else "unset"


def _swap_text(side_swap: bool | None) -> str:
    if side_swap:
        return "yes"
    return "none"


def _format_line_token(token: str) -> str | None:
    parsed = _parse_number(token)
    if parsed is None:
        return _line_from_example(token)
    return _format_number(parsed)


def _format_number(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def _parse_number(token: str) -> float | None:
    try:
        return float(token)
    except ValueError:
        return None


def _tagged(refs: list[str], prefix: str) -> str | None:
    for ref in refs:
        if ref.startswith(prefix):
            value = ref[len(prefix):].strip()
            if value:
                return value
    return None


def _get(pin: _Pin, name: str) -> Any:
    if isinstance(pin, Mapping):
        return pin.get(name)
    return getattr(pin, name, None)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _rule_text(row: Any, name: str) -> str | None:
    if row is None:
        return None
    text = _text(getattr(row, name, None))
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def served_words(pin: _Pin) -> dict[str, str]:
    """The three transform words Rules and the card both print."""
    return {
        "offset": _offset_text(_optional_float(_get(pin, "line_offset"))),
        "yes_side": _yes_text(_text(_get(pin, "yes_side"))),
        "side_swap": _swap_text(_optional_bool(_get(pin, "side_swap"))),
    }


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes"}:
        return True
    if lowered in {"0", "false", "no"}:
        return False
    return None
