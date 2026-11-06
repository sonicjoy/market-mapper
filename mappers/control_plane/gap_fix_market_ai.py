"""LLM suggestions for market-rule harvest skips unique-bind would not pin.

Closed Optic candidate list only. Never auto-Approve. Kill switch
``MAPPING_PIPELINE_GAP_SUGGEST`` defaults on. Suggestion pins are appended
last and carry ``ai:suggest`` evidence so Review is explicit.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from mappers.control_plane.chat_llm_cache import cached_chat_llm
from mappers.control_plane.gap_fix_ai_suggest import gap_suggest_enabled
from mappers.control_plane.gap_market_bind import spine_canonical_for_source
from mappers.control_plane.gap_market_period import (
    canonical_period_scope,
    source_period_scope,
)
from mappers.control_plane.pin_flow_markets import MarketRuleObservation, draft_ai_market_pin
from mappers.control_plane.settings import get_settings

MAX_AI_MARKET_SKIPS = 8
_AI_REASONS = frozenset({"no_optic_canonical"})
_JSON = re.compile(r"\{.*\}", re.S)
logger = logging.getLogger(__name__)


def append_ai_market_suggestions(
    store: Any,
    skipped: list[dict[str, str]],
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str, str]],
    *,
    llm: Any | None = None,
) -> int:
    """Append market-rule suggestion pins last. Returns how many were added."""
    if not gap_suggest_enabled():
        logger.info("pipeline gap-fix market AI skipped (MAPPING_PIPELINE_GAP_SUGGEST=0)")
        return 0
    eligible = _ai_skips(store, skipped)[:MAX_AI_MARKET_SKIPS]
    if not eligible:
        logger.info("pipeline gap-fix market AI eligible=0")
        return 0
    model = llm if llm is not None else _load_llm()
    if model is None:
        logger.info("pipeline gap-fix market AI eligible=%d but no llm", len(eligible))
        return 0
    added = 0
    for skip in eligible:
        pin = _suggest_pin(store, skip, model, seen)
        if pin is None:
            continue
        pins.append(pin)
        added += 1
    logger.info(
        "pipeline gap-fix market AI eligible=%d appended=%d",
        len(eligible),
        added,
    )
    return added


def _load_llm() -> Any | None:
    try:
        return cached_chat_llm(get_settings())
    except Exception as exc:
        logger.info("pipeline gap-fix market AI skipped (no llm): %s", exc)
        return None


def _ai_skips(store: Any, skipped: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in skipped:
        if str(row.get("reason") or "") not in _AI_REASONS:
            continue
        if not _candidates(row):
            continue
        if not _skip_ai_eligible(store, row):
            continue
        if not _eligible_candidates(store, row):
            continue
        out.append(row)
    return out


def _suggest_pin(
    store: Any,
    skip: dict[str, str],
    llm: Any,
    seen: set[tuple[str, str, str, str]],
) -> dict[str, Any] | None:
    candidates = _eligible_candidates(store, skip)
    if not candidates:
        return None
    allowed = {row["id"] for row in candidates}
    picked = _complete_pick(llm, skip, candidates)
    if not picked or picked not in allowed:
        return None
    name = next(row["name"] for row in candidates if row["id"] == picked)
    obs = _observation_from_skip(skip, candidates)
    pin = draft_ai_market_pin(
        store,
        obs,
        optic_id=picked,
        canonical=name,
        skip_reason=str(skip.get("reason") or "unknown"),
    )
    if pin is None:
        return None
    rules = pin.get("rules") or []
    if not rules:
        return None
    book_rule = next((r for r in rules if str(r.get("sportsbook") or "") != "optic"), rules[0])
    key = (
        str(pin.get("league") or ""),
        str(book_rule.get("sportsbook") or ""),
        str(book_rule.get("source_key_type") or ""),
        str(book_rule.get("source_key") or ""),
    )
    if key in seen:
        return None
    seen.add(key)
    return pin


def _observation_from_skip(
    skip: dict[str, str],
    candidates: list[dict[str, str]],
) -> MarketRuleObservation:
    live = {str(row["id"]) for row in candidates}
    source_key = str(skip.get("source_key") or "").strip()
    book = str(skip.get("sportsbook") or "").strip().lower()
    refs = [f"gap:{source_key}"] if source_key else []
    if book:
        refs.append(f"{book}:source_key:{source_key}")
    return {
        "league": str(skip.get("league") or ""),
        "sportsbook": book,
        "source_key": source_key,
        "source_key_type": str(skip.get("source_key_type") or ""),
        "demand": int(str(skip.get("demand") or "0") or "0"),
        "evidence_refs": refs,
        "live_optic_market_ids": live,
        "market_group": str(skip.get("market_group") or ""),
    }


def _candidates(skip: dict[str, str]) -> list[dict[str, str]]:
    """Optic {id, name} rows from JSON on the skip."""
    raw = str(skip.get("candidates") or "").strip()
    if not raw:
        return []
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("id") or "").strip()
        name = str(row.get("name") or "").strip()
        if oid and name:
            out.append({"id": oid, "name": name})
    return out


def _skip_ai_eligible(store: Any, skip: dict[str, str]) -> bool:
    """Fail closed: Kalshi takes no tip market rules, so no AI pick for it."""
    _ = store
    return str(skip.get("sportsbook") or "").strip().lower() != "kalshi"


def _expected_canonicals(store: Any, skip: dict[str, str]) -> set[str]:
    """Spine canonicals for this source key."""
    league = str(skip.get("league") or "").strip()
    book = str(skip.get("sportsbook") or "").strip().lower()
    source_key = str(skip.get("source_key") or "").strip()
    market_group = str(skip.get("market_group") or "")
    out: set[str] = set()
    spine = spine_canonical_for_source(
        league=league,
        book=book,
        source_key=source_key,
        market_group=market_group,
    )
    if spine:
        out.add(spine)
    return out


def _eligible_candidates(store: Any, skip: dict[str, str]) -> list[dict[str, str]]:
    """Closed list after spine and period-scope filters."""
    rows = _candidates(skip)
    if not rows:
        return []
    expected = _expected_canonicals(store, skip)
    source_period = source_period_scope(str(skip.get("source_key") or ""))
    out: list[dict[str, str]] = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if expected:
            if name not in expected:
                continue
        elif source_period and canonical_period_scope(name) != source_period:
            continue
        out.append(row)
    return out


def _complete_pick(
    llm: Any,
    skip: dict[str, str],
    candidates: list[dict[str, str]],
) -> str:
    try:
        result = llm.complete(_messages(skip, candidates), [])
    except Exception as exc:
        logger.info("pipeline gap-fix market AI complete failed: %s", exc)
        return ""
    return _parse_optic_id(getattr(result, "text", "") or "")


def _messages(skip: dict[str, str], candidates: list[dict[str, str]]) -> list[dict[str, Any]]:
    lines = [
        f"LEAGUE: {skip.get('league') or ''}",
        f"SPORTSBOOK: {skip.get('sportsbook') or ''}",
        f"SKIP: {skip.get('reason') or ''}",
        f"SOURCE ({skip.get('source_key_type') or ''}): {skip.get('source_key') or ''}",
        "CANDIDATES:",
    ]
    lines.extend(f"- id={row['id']} name={row['name']}" for row in candidates)
    lines.append('Reply JSON only: {"optic_id":"..."} or {"abstain":true}.')
    return [
        {
            "role": "system",
            "content": (
                "You suggest sports mapping market rules for a human reviewer. "
                "Unique-bind already failed. Pick at most one Optic id from "
                "CANDIDATES. Abstain when the source is a period market "
                "(half/quarter) but every candidate is full-game, or when "
                "periods do not match. If unsure, abstain. Never invent an id."
            ),
        },
        {"role": "user", "content": "\n".join(lines)},
    ]


def _parse_optic_id(text: str) -> str:
    match = _JSON.search(text.strip())
    if match is None:
        return ""
    try:
        body = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ""
    if not isinstance(body, dict) or body.get("abstain") is True:
        return ""
    return str(body.get("optic_id") or "").strip()
