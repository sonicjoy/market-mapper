"""Per-source-key evidence for market-rule cards.

A league group stores one evidence list. Each card shows the refs that name
its own source key. Notes stay on the row and never enter this split.
"""

from __future__ import annotations

import re
from typing import Any

from mappers.control_plane.entry import league_label
from mappers.control_plane.league_review import book_label
from mappers.control_plane.market_rule_card import apply_rule_card
from mappers.control_plane.models import MarketRulePin

_ALNUM = re.compile(r"[A-Za-z0-9]+")


def evidence_by_source_key(refs: list[str], source_keys: list[str]) -> dict[str, list[str]]:
    """Give each source key only the evidence that names it.

    The longest key wins when a token ends with more than one key, so
    ``KXNHL1HSPREAD`` belongs to ``1HSPREAD`` and not ``SPREAD``. Match is
    case-sensitive. A ref that names no key stays with the previous owner.
    A leading unmatched run waits for the first key that matches. When
    nothing matches and the group has one key, that key keeps the list.
    """
    keys = list(dict.fromkeys(key for key in source_keys if key))
    buckets: dict[str, list[str]] = {key: [] for key in keys}
    owner: str | None = None
    pending: list[str] = []
    claimed = False
    for ref in refs:
        named = _owner_for_ref(ref, keys)
        if named is None:
            if owner is None:
                pending.append(ref)
            else:
                buckets[owner].append(ref)
            continue
        if owner is None and pending:
            buckets[named].extend(pending)
            pending = []
        owner = named
        claimed = True
        buckets[owner].append(ref)
    if not claimed and len(keys) == 1:
        buckets[keys[0]].extend(pending)
    return buckets


def _owner_for_ref(ref: str, keys: list[str]) -> str | None:
    segment = ref.rsplit(":", 1)[-1]
    best: str | None = None
    best_len = -1
    for key in keys:
        if len(key) <= best_len or not _segment_names_key(segment, key):
            continue
        best = key
        best_len = len(key)
    return best


def _segment_names_key(segment: str, key: str) -> bool:
    if segment == key or segment.endswith(key):
        return True
    return any(token == key or token.endswith(key) for token in _ALNUM.findall(segment))


def context_mapping_rows(
    league: str,
    pins: list[MarketRulePin],
    *,
    sport: str,
    league_is_new: bool,
    evidence: list[str] | None = None,
    evidence_by_key: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Read-only rows for keys already on the tip. Not an approvable pin."""
    rows: list[dict[str, Any]] = []
    for pin in pins:
        refs = _refs_for_pin(pin, evidence, evidence_by_key)
        rows.append(_context_row(league, pin, sport, league_is_new, refs))
    return rows


def _refs_for_pin(
    pin: MarketRulePin,
    evidence: list[str] | None,
    evidence_by_key: dict[str, list[str]] | None,
) -> list[str]:
    if evidence_by_key is None:
        return list(evidence or [])
    return list(evidence_by_key.get(str(pin.source_key or ""), []))


def _context_row(
    league: str,
    pin: MarketRulePin,
    sport: str,
    league_is_new: bool,
    refs: list[str],
) -> dict[str, Any]:
    canonical = str(pin.canonical_market_type or "")
    book = str(pin.sportsbook or "")
    key = str(pin.source_key or "")
    row: dict[str, Any] = {
        "kind": "market_rule",
        "key": f"rule:{league}:{book}:{pin.source_key_type}:{key}",
        "action": "update",
        "tier": "confirmed",
        "confidence": None,
        "reason": None,
        "alternatives": [],
        "keep_default": False,
        "league": league,
        "league_label": league_label(league),
        "league_is_new": league_is_new,
        "sport": sport,
        "rfq_demand": None,
        "next_fixtures": [],
        "evidence": list(refs),
        "read_only": True,
        "sportsbook": book,
        "source": {
            "platform": book_label(book),
            "name": key,
            "code": key,
            "description": str(pin.source_key_type or ""),
        },
        "target": {"platform": "Optic", "name": canonical or "ignored", "description": canonical},
        "official_description": str(pin.official_description or "").strip() or None,
        "citation_url": str(pin.citation_url or "").strip() or None,
        "notes": str(pin.notes or "").strip() or None,
    }
    apply_rule_card(row, pin, league=league, evidence_refs=refs)
    return row
