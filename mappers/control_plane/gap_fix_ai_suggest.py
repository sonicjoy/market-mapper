"""LLM suggestions for harvest skips unique-bind would not pin.

Closed Optic candidate list only. Never auto-Approve. Kill switch
``MAPPING_PIPELINE_GAP_SUGGEST`` defaults on. Suggestion pins are appended
last and carry ``ai:suggest`` evidence so Review is explicit.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from BigQuery.alerts import bool_env
from mappers.alias_kinds import optic_pin
from mappers.canonical_codes import names_fit, person_league, school_marks, tokens
from mappers.control_plane.alias_payload import alias_payload
from mappers.control_plane.chat_llm_cache import cached_chat_llm
from mappers.control_plane.entity_types import match_entity_type_for_pin
from mappers.control_plane.gap_fix_keys import (
    alias_was_removed,
    crypto_aliases,
    entity_has_pin,
    key_for_code,
    used_keys,
)
from mappers.control_plane.gap_fix_name_bind import vs_sides
from mappers.control_plane.settings import get_settings
from mappers.seed.poly_usa_exchange import POLY_BOOK

AI_REF = "ai:suggest"
AI_NOTE = "AI suggestion — unique-bind did not apply; human must Approve."
MAX_AI_SKIPS = 8
_AI_REASONS = frozenset({"collision", "name_mismatch", "name_ambiguous"})
_JSON = re.compile(r"\{.*\}", re.S)
logger = logging.getLogger(__name__)


def gap_suggest_enabled() -> bool:
    """Kill switch; default on. Set ``MAPPING_PIPELINE_GAP_SUGGEST=0`` to disable."""
    return bool_env("MAPPING_PIPELINE_GAP_SUGGEST", default=True)


def append_ai_suggestions(
    store: Any,
    skipped: list[dict[str, str]],
    pins: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    *,
    llm: Any | None = None,
) -> int:
    """Append suggestion pins last. Returns how many were added."""
    if not gap_suggest_enabled():
        logger.info("pipeline gap-fix AI suggestions skipped (MAPPING_PIPELINE_GAP_SUGGEST=0)")
        return 0
    eligible = _ai_skips(skipped)[:MAX_AI_SKIPS]
    if not eligible:
        logger.info("pipeline gap-fix AI suggestions eligible=0")
        return 0
    model = llm if llm is not None else _load_llm()
    if model is None:
        logger.info(
            "pipeline gap-fix AI suggestions eligible=%d but no llm",
            len(eligible),
        )
        return 0
    added = 0
    for skip in eligible:
        pin = _suggest_pin(store, skip, model, seen)
        if pin is None:
            continue
        pins.append(pin)
        added += 1
    logger.info(
        "pipeline gap-fix AI suggestions eligible=%d appended=%d",
        len(eligible),
        added,
    )
    return added


def is_ai_suggest_pin(pin: dict[str, Any] | Any) -> bool:
    """True when a harvest pin or alias payload is an AI suggestion."""
    refs = getattr(pin, "evidence_refs", None)
    if refs is None and isinstance(pin, dict):
        refs = pin.get("evidence_refs")
    return any(str(ref) == AI_REF or str(ref).startswith("ai:suggest") for ref in (refs or []))


def _load_llm() -> Any | None:
    """Chat factory when the CronJob has a key; None on miss (fail open)."""
    try:
        return cached_chat_llm(get_settings())
    except Exception as exc:
        logger.info("pipeline gap-fix AI suggest skipped (no llm): %s", exc)
        return None


def _ai_skips(skipped: list[dict[str, str]]) -> list[dict[str, str]]:
    """Near-miss skips that still have an Optic candidate list."""
    out: list[dict[str, str]] = []
    for row in skipped:
        if str(row.get("reason") or "") not in _AI_REASONS:
            continue
        if str(row.get("leave") or ""):
            continue
        if not _candidates(row):
            continue
        out.append(row)
    return out


def _suggest_pin(
    store: Any,
    skip: dict[str, str],
    llm: Any,
    seen: set[tuple[str, str, str]],
) -> dict[str, Any] | None:
    """One suggestion pin from a closed-list LLM pick, or None."""
    candidates = _eligible_candidates(skip)
    if not candidates:
        return None
    allowed = {row["id"] for row in candidates}
    picked = _complete_pick(llm, skip, candidates)
    if not picked or picked not in allowed:
        return None
    name = next(row["name"] for row in candidates if row["id"] == picked)
    pin = _draft_pin(store, skip, picked, name)
    if pin is None:
        return None
    key = (pin["league"], pin["canonical_key"], pin["aliases"][0]["alias_value"])
    if key in seen:
        return None
    seen.add(key)
    return pin


def _complete_pick(
    llm: Any, skip: dict[str, str], candidates: list[dict[str, str]],
) -> str:
    """optic_id from JSON, else empty. Invented ids are dropped by the caller."""
    try:
        result = llm.complete(_messages(skip, candidates), [])
    except Exception as exc:
        logger.info("pipeline gap-fix AI suggest complete failed: %s", exc)
        return ""
    return _parse_optic_id(getattr(result, "text", "") or "")


def _messages(skip: dict[str, str], candidates: list[dict[str, str]]) -> list[dict[str, Any]]:
    """System + user turn: pick 0 or 1 id from the list."""
    lines = [
        f"NEEDLE: {skip.get('needle') or skip.get('title') or ''}",
        f"TITLE: {skip.get('title') or ''}",
        f"LEAGUE: {skip.get('league') or ''}",
        f"SKIP: {skip.get('reason') or ''}",
        "CANDIDATES:",
    ]
    lines.extend(f"- id={row['id']} name={row['name']}" for row in candidates)
    lines.append('Reply JSON only: {"optic_id":"..."} or {"abstain":true}.')
    return [
        {
            "role": "system",
            "content": (
                "You suggest sports mapping aliases for a human reviewer. "
                "Unique-bind already failed. Pick at most one Optic id from "
                "CANDIDATES. Abstain when names differ by State, Tech, or A&M, "
                "or when the candidate opponent is not the title opponent. "
                "If unsure, abstain. Never invent an id."
            ),
        },
        {"role": "user", "content": "\n".join(lines)},
    ]


def _parse_optic_id(text: str) -> str:
    """optic_id from a JSON object, ignoring markdown fences."""
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


def _candidates(skip: dict[str, str]) -> list[dict[str, str]]:
    """Optic {id, name} rows from JSON or home/away fields."""
    raw = str(skip.get("candidates") or "").strip()
    if raw:
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError:
            rows = []
        out: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            oid = str(row.get("id") or "").strip()
            name = str(row.get("name") or "").strip()
            if not oid or not name:
                continue
            item = {"id": oid, "name": name}
            opp = str(row.get("opponent") or "").strip()
            if opp:
                item["opponent"] = opp
            out.append(item)
        return out
    pairs = (
        (str(skip.get("home_id") or ""), str(skip.get("home") or "")),
        (str(skip.get("away_id") or ""), str(skip.get("away") or "")),
    )
    return [{"id": oid, "name": name} for oid, name in pairs if oid and name]


def _draft_pin(
    store: Any, skip: dict[str, str], oid: str, name: str,
) -> dict[str, Any] | None:
    """Crypto / Poly suggestion pin, or None on collide/incomplete."""
    league = str(skip.get("league") or "")
    if not league:
        return None
    used = used_keys(store, league)
    owners = [str(o) for o in str(skip.get("owners") or "").split(",") if o]
    key, collide = key_for_code(store, league, oid, name, used, owners)
    if not key or collide:
        return None
    entity_type = match_entity_type_for_pin(store, league, key)
    aliases = [
        alias for alias in _aliases(skip, oid)
        if not entity_has_pin(store, league, key, alias)
        and not alias_was_removed(store, league, key, alias)
    ]
    if not aliases:
        return None
    evidence = _evidence(skip, oid, name)
    return alias_payload(league, key, name, entity_type, aliases, evidence)


def _aliases(skip: dict[str, str], oid: str) -> list[dict[str, str]]:
    """Book alias plus Optic id. Empty when the skip has no alias value."""
    value = str(skip.get("alias_value") or "").strip()
    book = str(skip.get("alias_book") or "").strip().lower()
    if book == "crypto.com" and value:
        return crypto_aliases(value, oid, include_optic=True)
    if book == POLY_BOOK and value:
        return [
            {"sportsbook": POLY_BOOK, "alias_kind": "name", "alias_value": value},
            optic_pin(oid),
        ]
    return []


def _evidence(skip: dict[str, str], oid: str, name: str) -> list[str]:
    """AI label first, then gap/title/Optic refs."""
    refs = [AI_REF, f"ai:skip:{skip.get('reason') or 'unknown'}", AI_NOTE]
    ticker = str(skip.get("event_ticker") or skip.get("symbol") or "").strip()
    if ticker:
        refs.append(f"gap:{ticker}")
    title = str(skip.get("title") or "").strip()
    if title:
        book = str(skip.get("alias_book") or "source")
        refs.append(f"{book}:title:{title}")
    needle = str(skip.get("needle") or "").strip()
    if needle:
        refs.append(f"ai:needle:{needle}")
    refs.append(f"optic:competitor:{oid}:{name}")
    return refs


def _eligible_candidates(skip: dict[str, str]) -> list[dict[str, str]]:
    """Closed list after State/Tech/A&M and title-opponent filters."""
    rows = _with_opponents(_candidates(skip))
    needle = str(skip.get("needle") or "")
    player = person_league(str(skip.get("league") or ""))
    opponent = _title_opponent(skip)
    tagged = any(bool(row.get("opponent")) for row in rows)
    out: list[dict[str, str]] = []
    for row in rows:
        if not player and school_marks(needle) != school_marks(row["name"]):
            continue
        if opponent and tagged and row.get("opponent") and not _opponent_fit(
            opponent, row["opponent"], player=player,
        ):
            continue
        out.append(row)
    return out


def _with_opponents(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Fill opponent from the other side when the skip is a two-team fixture."""
    if len(rows) != 2 or any(row.get("opponent") for row in rows):
        return rows
    left, right = rows
    return [
        {**left, "opponent": right["name"]},
        {**right, "opponent": left["name"]},
    ]


def _title_opponent(skip: dict[str, str]) -> str:
    """Other vs-side from the skip title, else empty."""
    sides = vs_sides(str(skip.get("title") or ""))
    if sides is None:
        return ""
    needle = str(skip.get("needle") or "").casefold().strip()
    if needle == sides[0].casefold():
        return sides[1]
    if needle == sides[1].casefold():
        return sides[0]
    return sides[1]


def _opponent_fit(left: str, right: str, *, player: bool) -> bool:
    """True when the title opponent is the candidate's fixture opponent."""
    if names_fit(left, right, player=player):
        return True
    if player:
        return False
    lt = [t.upper() for t in tokens(left)]
    rt = [t.upper() for t in tokens(right)]
    if not lt or not rt or lt[0] != rt[0] or len(lt[0]) < 4:
        return False
    return school_marks(left) == school_marks(right)
