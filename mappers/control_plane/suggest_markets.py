"""Suggest market rules from optic_spine.csv (no LLM, no clone required)."""

from __future__ import annotations

import csv
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from mappers.control_plane.models import MarketRulePin
from mappers.control_plane.rows import LeagueRow, MarketRuleRow

_SPINE_PATH = Path(__file__).resolve().parents[2] / "docs" / "mapping-rules" / "optic_spine.csv"

# sportsbook → (source_key_type, spine column)
_BOOK_COLUMNS: dict[str, tuple[str, str]] = {
    "optic": ("market_id", "optic_market_id"),
    "crypto.com": ("contract_type", "crypto_contract_types"),
    "polymarket": ("kind", "polymarket_kinds"),
    "polymarket_usa": ("kind", "polymarket_kinds"),
    "px": ("market_name", "px_market_keys"),
    "novig": ("market_type", "novig_market_types"),
}


@lru_cache(maxsize=1)
def _load_spine() -> tuple[dict[str, str], ...]:
    """Load optic_spine.csv rows (cached)."""
    if not _SPINE_PATH.is_file():
        return ()
    with _SPINE_PATH.open(encoding="utf-8", newline="") as fh:
        return tuple(csv.DictReader(fh))


def _parse_spine_key(raw: str, *, book: str) -> tuple[str, str]:
    """Return ``(source_key, match_operator)`` from one spine cell token."""
    key = raw.strip()
    if not key:
        return "", "exact"
    if book == "px" and ":" in key:
        prefix, rest = key.split(":", 1)
        if prefix == "exact":
            return (rest.strip() or key), "exact"
        if prefix == "suffix":
            return (rest.strip() or key), "suffix"
    # crypto spine sometimes uses "game_line:Moneyline" / "game_prop:…"
    if ":" in key and key.split(":", 1)[0] in {
        "game_line",
        "game_prop",
        "prop",
        "team_prop",
    }:
        key = key.split(":", 1)[1].strip() or key
    return key, "exact"


def _split_spine_keys(raw: str, *, book: str) -> list[tuple[str, str]]:
    """Split a spine multi-value cell into ``(source_key, match_operator)`` pairs.

    ``scripts/export_mapping_rules.py`` joins with ``;``; accept ``,`` too.
    """
    if not raw or not raw.strip():
        return []
    out: list[tuple[str, str]] = []
    for chunk in raw.replace(",", ";").split(";"):
        key, match_operator = _parse_spine_key(chunk, book=book)
        if key:
            out.append((key, match_operator))
    return out


def _rows_for_optic_id(optic_league_id: str) -> list[dict[str, str]]:
    needle = optic_league_id.strip()
    return [r for r in _load_spine() if (r.get("optic_league_id") or "").strip() == needle]


def _rows_for_league_slug(league: str) -> list[dict[str, str]]:
    needle = league.strip()
    return [r for r in _load_spine() if (r.get("league") or "").strip() == needle]


def _rows_for_sport_template(
    sport: str,
    tip_leagues: list[LeagueRow],
) -> list[dict[str, str]]:
    """Union spine rows from tip leagues of the same sport."""
    sport_n = sport.strip().lower()
    if not sport_n:
        return []
    slugs = {row.league for row in tip_leagues if (row.sport or "").strip().lower() == sport_n}
    if not slugs:
        return []
    return [r for r in _load_spine() if (r.get("league") or "").strip() in slugs]


def _optic_pins_from_rows(rows: list[dict[str, str]]) -> list[tuple[str, str]]:
    """Dedupe optic_market_id → canonical (first wins)."""
    seen: dict[str, str] = {}
    for row in rows:
        mid = (row.get("optic_market_id") or "").strip()
        cmt = (row.get("canonical_market_type") or "").strip()
        if mid and cmt and mid not in seen:
            seen[mid] = cmt
    return list(seen.items())


def _book_pins_from_rows(
    rows: list[dict[str, str]],
    *,
    column: str,
    book: str,
) -> list[tuple[str, str, str]]:
    """Majority-vote source_key → canonical from spine rows."""
    votes: dict[tuple[str, str], Counter[str]] = {}
    for row in rows:
        cmt = (row.get("canonical_market_type") or "").strip()
        if not cmt:
            continue
        for key, match_operator in _split_spine_keys(row.get(column) or "", book=book):
            votes.setdefault((key, match_operator), Counter())[cmt] += 1
    out: list[tuple[str, str, str]] = []
    for (key, match_operator), counter in sorted(votes.items()):
        cmt, _n = counter.most_common(1)[0]
        out.append((key, cmt, match_operator))
    return out


def _match_rows(
    *,
    optic_league_id: str,
    sport: str,
    tip_leagues: list[LeagueRow],
    template_league: str | None,
) -> tuple[list[dict[str, str]], str | None]:
    """Best spine slice for this league, and where it came from."""
    if optic_league_id.strip() and (rows := _rows_for_optic_id(optic_league_id)):
        return rows, "optic_league_id"
    if template_league and (rows := _rows_for_league_slug(template_league)):
        return rows, f"template:{template_league}"
    if rows := _rows_for_sport_template(sport, tip_leagues):
        return rows, f"sport:{sport}"
    return [], None


def _book_suggestions(
    book: str,
    rows: list[dict[str, str]],
    *,
    league: str,
    source: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Suggestions for one sportsbook, plus a warning when it yields none."""
    meta = _BOOK_COLUMNS.get(book)
    if not meta:
        return [], f"No spine column mapping for sportsbook {book!r}; skipped."
    key_type, column = meta
    if book == "optic":
        pairs = [(key, cmt, "exact") for key, cmt in _optic_pins_from_rows(rows)]
    else:
        pairs = _book_pins_from_rows(rows, column=column, book=book)
    if not pairs:
        return [], f"No {book} keys in matched spine rows."
    out: list[dict[str, Any]] = []
    for source_key, cmt, match_operator in pairs:
        pin = MarketRulePin(
            sportsbook=book,
            rule_kind="taxonomy",
            source_key_type=key_type,
            source_key=source_key,
            action="map",
            canonical_market_type=cmt,
            league=league.strip() or None,
            confidence="spine_suggest",
            match_operator=match_operator,
            notes=f"suggested from optic_spine ({source})",
        )
        out.append(
            {
                "id": f"{book}|{key_type}|{source_key}",
                "label": f"{book} {source_key} → {cmt}",
                "selected_default": True,
                "pin": pin.model_dump(mode="json"),
            }
        )
    return out, None


def _source_warning(source: str, sport: str, template_league: str | None) -> str | None:
    if source.startswith("sport:"):
        return f"Optic league id not in spine — using same-sport tip template ({sport}). Review carefully."
    if source.startswith("template:"):
        return f"Using spine template from league {template_league!r}."
    return None


def _no_suggestions(warning: str) -> dict[str, Any]:
    return {"ok": False, "warnings": [warning], "source": None, "suggestions": []}


def _collect_book_suggestions(
    books: list[str],
    rows: list[dict[str, str]],
    *,
    league: str,
    source: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Spine pins and per-book warnings for the enabled sportsbooks."""
    suggestions: list[dict[str, Any]] = []
    warnings: list[str] = []
    for book in books:
        found, warning = _book_suggestions(book, rows, league=league, source=source)
        suggestions.extend(found)
        if warning:
            warnings.append(warning)
    return suggestions, warnings


def _tip_market_keys(
    rules: list[MarketRuleRow],
    *,
    league: str,
) -> set[tuple[str, str, str]]:
    """Map/ignore pins already on the tip for this league."""
    lg = league.strip()
    out: set[tuple[str, str, str]] = set()
    for mr in rules:
        if mr.tombstone or not mr.enabled:
            continue
        if mr.action not in ("map", "ignore"):
            continue
        row_league = (mr.league or "").strip()
        if row_league and row_league != lg:
            continue
        out.add((mr.sportsbook, mr.source_key_type, mr.source_key))
    return out


def filter_existing_market_suggestions(
    suggestions: list[dict[str, Any]],
    rules: list[MarketRuleRow],
    *,
    league: str = "",
) -> tuple[list[dict[str, Any]], int]:
    """Drop spine suggestions that already map/ignore on the tip."""
    existing = _tip_market_keys(rules, league=league)
    if not existing:
        return suggestions, 0
    kept: list[dict[str, Any]] = []
    skipped = 0
    for item in suggestions:
        pin = dict(item.get("pin") or {})
        key = (
            str(pin.get("sportsbook") or ""),
            str(pin.get("source_key_type") or ""),
            str(pin.get("source_key") or ""),
        )
        if key in existing:
            skipped += 1
            continue
        kept.append(item)
    return kept, skipped


def _finalize_market_suggestions(
    result: dict[str, Any],
    *,
    store: Any,
    league: str,
) -> dict[str, Any]:
    """Drop tip market rules and merge warnings into the built payload."""
    if store is None:
        return result
    rid = getattr(store, "current_rule_set_id", None)
    if not rid or not hasattr(store, "market_rules_for"):
        return result
    suggestions, skipped = filter_existing_market_suggestions(
        list(result.get("suggestions") or []),
        list(store.market_rules_for(rid)),
        league=league.strip(),
    )
    warnings = list(result.get("warnings") or [])
    if skipped:
        warnings.append(f"Skipped {skipped} market rule(s) already on this league.")
    result["suggestions"] = suggestions
    result["warnings"] = warnings
    result["ok"] = bool(suggestions)
    return result


def suggest_market_rules(
    *,
    league: str,
    optic_league_id: str,
    sport: str = "",
    sportsbooks: list[str] | None = None,
    tip_leagues: list[LeagueRow] | None = None,
    template_league: str | None = None,
    store: Any = None,
) -> dict[str, Any]:
    """Build suggested MarketRulePin payloads for enabled sportsbooks."""
    books = [b.strip() for b in (sportsbooks or ["optic"]) if b and b.strip()]
    if not books:
        return _no_suggestions("Enable at least one exchange to suggest market rules.")

    rows, source = _match_rows(
        optic_league_id=optic_league_id,
        sport=sport,
        tip_leagues=tip_leagues or [],
        template_league=template_league,
    )
    if not rows or source is None:
        return _no_suggestions(
            "No optic_spine rows matched this Optic league / sport template. "
            "Clone from an analogue league or enter market rules manually."
        )

    warnings: list[str] = []
    if note := _source_warning(source, sport, template_league):
        warnings.append(note)

    suggestions, book_warnings = _collect_book_suggestions(
        books, rows, league=league, source=source
    )
    warnings.extend(book_warnings)
    built = {
        "ok": bool(suggestions),
        "warnings": warnings,
        "source": source,
        "suggestions": suggestions,
        "payload_template": {"kind": "mapping_market_rules", "league": league.strip()},
    }
    return _finalize_market_suggestions(built, store=store, league=league)


@lru_cache(maxsize=1)
def spine_league_slugs() -> frozenset[str]:
    """Every league slug named in optic_spine.csv (static catalogue, no store)."""
    return frozenset(slug for row in _load_spine() if (slug := (row.get("league") or "").strip()))


def spine_optic_league_id(slug: str) -> str:
    """Optic league id optic_spine.csv pins for this slug; empty unless exactly one."""
    want = slug.strip()
    ids = {
        (row.get("optic_league_id") or "").strip()
        for row in _load_spine()
        if (row.get("league") or "").strip() == want
    } - {""}
    return next(iter(ids)) if len(ids) == 1 else ""


def leagues_for_market_id(optic_id: str) -> tuple[str, ...]:
    """Tip league slugs in optic_spine that emit this Optic market_id."""
    needle = optic_id.strip()
    if not needle:
        return ()
    found: list[str] = []
    seen: set[str] = set()
    for row in _load_spine():
        if (row.get("optic_market_id") or "").strip() != needle:
            continue
        slug = (row.get("league") or "").strip()
        if slug and slug not in seen:
            seen.add(slug)
            found.append(slug)
    return tuple(found)
