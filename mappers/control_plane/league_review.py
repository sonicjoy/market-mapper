"""League change lines and pin evidence for review cards."""

from __future__ import annotations

from typing import Any, TypedDict

from mappers.control_plane.dry_run_already import (
    league_already_live,
    resolved_enabled,
    resolved_extra_optic_ids,
    resolved_fixture_horizon,
    resolved_output_order,
)
from mappers.control_plane.entry import league_label
from mappers.control_plane.models import (
    BatchChangesPayload,
    EntityAliasPayload,
    MappingLeaguePayload,
)
from mappers.control_plane.rows import LeagueRow
from mappers.seed.league_meta import merge_league_meta_into_exchanges

BOOK_LABELS = {
    "kalshi": "Kalshi",
    "crypto.com": "crypto.com",
    "optic": "Optic",
    "polymarket": "Polymarket",
    "polymarket_usa": "Polymarket US",
    "px": "ProphetX",
    "novig": "Novig",
    "huddle": "Huddle",
    "txodds": "TxODDS",
}


class LeagueCardDiff(TypedDict):
    """Structured Proposed-card lists for a league pin."""

    enable: list[str]
    disable: list[str]
    change: list[str]
    already: list[str]
    other: list[str]


def book_label(sportsbook: str) -> str:
    """Display label for a sportsbook id."""
    return BOOK_LABELS.get(sportsbook, sportsbook or "unknown")


def league_title(slug: str | None) -> str:
    """Human league name, with slug when the label differs."""
    if not slug:
        return "?"
    label = league_label(slug)
    return f"{label} ({slug})" if label.lower() != slug.lower() else slug


def _ex_rows(exchanges: list[Any]) -> list[tuple[str, bool, str, str, dict[str, str]]]:
    """Normalize exchange pins to (book, enabled, source_id, profile, settings)."""
    out: list[tuple[str, bool, str, str, dict[str, str]]] = []
    for ex in exchanges or []:
        book, enabled, source, profile, settings = _ex_fields(ex)
        if book:
            out.append((book, enabled, source, profile, settings))
    return out


def _ex_fields(ex: Any) -> tuple[str, bool, str, str, dict[str, str]]:
    """One exchange pin as comparable fields, including slug_prefix."""
    book, enabled, source, profile, raw = _ex_raw(ex)
    prefix = str(raw.get("slug_prefix") or "").strip()
    settings = {"slug_prefix": prefix} if prefix else {}
    return book, enabled, source, profile, settings


def _ex_raw(ex: Any) -> tuple[str, bool, str, str, dict[str, Any]]:
    """Untyped exchange fields plus the settings dict."""
    if hasattr(ex, "sportsbook"):
        raw = getattr(ex, "settings", None) or {}
        return (
            str(ex.sportsbook or ""),
            bool(getattr(ex, "enabled", True)),
            str(getattr(ex, "source_league_id", None) or ""),
            str(getattr(ex, "parser_profile", None) or ""),
            dict(raw) if isinstance(raw, dict) else {},
        )
    if isinstance(ex, dict):
        raw = ex.get("settings") or {}
        return (
            str(ex.get("sportsbook") or ""),
            bool(ex.get("enabled", True)),
            str(ex.get("source_league_id") or ""),
            str(ex.get("parser_profile") or ""),
            dict(raw) if isinstance(raw, dict) else {},
        )
    return ("", False, "", "", {})


def enabled_book_text(exchanges: list[Any]) -> str:
    """Comma-separated enabled books, with source ids when set."""
    parts: list[str] = []
    for book, enabled, source, _profile, _settings in _ex_rows(exchanges):
        if not enabled:
            continue
        name = book_label(book)
        parts.append(f"{name} ({source})" if source else name)
    return ", ".join(parts)


def format_league_row(row: LeagueRow) -> str:
    """Add/remove line: league plus enabled books."""
    title = league_title(row.league)
    books = enabled_book_text(row.exchanges)
    return f"{title} — {books}" if books else title


def payload_as_row(league: MappingLeaguePayload, prior: LeagueRow | None = None) -> LeagueRow:
    """League payload as a tip row for add-vs-update compare."""
    settings = league.league_settings()
    exchanges = merge_league_meta_into_exchanges(
        [ex.model_dump(mode="json") for ex in league.exchanges],
        settings,
    )
    return LeagueRow(
        league=league.league,
        sport=league.sport,
        optic_league_id=league.optic_league_id,
        extra_optic_league_ids=resolved_extra_optic_ids(league.extra_optic_league_ids, prior),
        fixture_source=league.fixture_source,
        fixture_horizon_hours=resolved_fixture_horizon(league.fixture_horizon_hours, prior),
        enabled=resolved_enabled(league.enabled, prior),
        output_order=resolved_output_order(league.output_order, prior),
        exchanges=exchanges,
        notes=league.notes,
        settings=settings,
    )


def _payload_leagues(payload: object) -> list[MappingLeaguePayload]:
    """League pins from a single artifact or a batch."""
    if isinstance(payload, MappingLeaguePayload):
        return [payload]
    if isinstance(payload, BatchChangesPayload):
        return list(payload.leagues)
    return []


def payload_league_group(payload: object, tip_leagues: list[LeagueRow] | None = None) -> dict[str, Any]:
    """Add vs update league lines using tip rows when the snapshot is missing."""
    tip = {row.league: row for row in (tip_leagues or []) if not row.tombstone}
    added = 0
    modified = 0
    lines: list[str] = []
    for league in _payload_leagues(payload):
        prior = tip.get(league.league)
        if prior is None:
            added += 1
            lines.append(f"+ {format_payload_league(league)}")
            continue
        if league_already_live(prior, league):
            continue
        modified += 1
        lines.append(f"~ {format_league_mod(prior, payload_as_row(league, prior))}")
    return {
        "added_count": added,
        "modified_count": modified,
        "removed_count": 0,
        "lines": sorted(lines),
    }


def format_payload_league(league: MappingLeaguePayload) -> str:
    """Payload fallback line when no tip snapshot is stored."""
    title = league_title(league.league)
    books = enabled_book_text(league.exchanges)
    return f"{title} — {books}" if books else title


def format_league_mod(parent: LeagueRow, child: LeagueRow) -> str:
    """Update line: enable/disable/change books versus the live tip."""
    title = league_title(child.league or parent.league)
    buckets = _exchange_buckets(parent.exchanges, child.exchanges)
    bits = _mod_phrases(buckets["enable"], buckets["disable"], buckets["change"])
    bits.extend(_league_meta_bits(parent, child))
    if not bits:
        return f"Update {title}"
    already = ", ".join(buckets["already_names"])
    extra = f"; {already} already on" if already else ""
    return f"{'; '.join(bits)} on {title}{extra}"


def league_mod_lists(parent: LeagueRow, child: LeagueRow) -> LeagueCardDiff:
    """Adding / removing / changing / already-live lists for a Proposed card."""
    buckets = _exchange_buckets(parent.exchanges, child.exchanges)
    return _card_diff(
        buckets["enable"],
        buckets["disable"],
        buckets["change"],
        buckets["already"],
        _league_meta_bits(parent, child),
    )


def league_card_copy(lg: MappingLeaguePayload, prior: LeagueRow | None) -> tuple[str, LeagueCardDiff]:
    """Headline plus structured lists for a Proposed league card."""
    if prior is None:
        return format_payload_league(lg), _add_lists(lg)
    child = payload_as_row(lg, prior)
    return format_league_mod(prior, child), league_mod_lists(prior, child)


def _add_lists(lg: MappingLeaguePayload) -> LeagueCardDiff:
    """New-league card: every enabled book is an add."""
    enable: list[str] = []
    for book, on, src, _profile, settings in _ex_rows(lg.exchanges):
        if on:
            enable.append(_pin_label(book_label(book), src, settings))
    return _card_diff(enable, [], [], [], [])


def _card_diff(
    enable: list[str],
    disable: list[str],
    change: list[str],
    already: list[str],
    other: list[str],
) -> LeagueCardDiff:
    return {
        "enable": enable,
        "disable": disable,
        "change": change,
        "already": already,
        "other": other,
    }


def _exchange_buckets(parent_ex: list[Any], child_ex: list[Any]) -> dict[str, list[str]]:
    """Classify each book as enable / disable / change / already."""
    before = {b: (on, src, st) for b, on, src, _p, st in _ex_rows(parent_ex)}
    after = {b: (on, src, st) for b, on, src, _p, st in _ex_rows(child_ex)}
    buckets: dict[str, list[str]] = {
        "enable": [],
        "disable": [],
        "change": [],
        "already": [],
        "already_names": [],
    }
    empty: tuple[bool, str, dict[str, str]] = (False, "", {})
    for book in sorted(set(before) | set(after)):
        _classify_book(book, before.get(book, empty), after.get(book, empty), buckets)
    return buckets


def _classify_book(
    book: str,
    prior: tuple[bool, str, dict[str, str]],
    nxt: tuple[bool, str, dict[str, str]],
    buckets: dict[str, list[str]],
) -> None:
    """Append one book to the matching delta list."""
    b_on, b_src, b_set = prior
    a_on, a_src, a_set = nxt
    name = book_label(book)
    if a_on and not b_on:
        buckets["enable"].append(_pin_label(name, a_src, a_set))
        return
    if b_on and not a_on:
        buckets["disable"].append(name)
        return
    if not (a_on and b_on):
        return
    change = _book_change_label(name, b_src, b_set, a_src, a_set)
    if change:
        buckets["change"].append(change)
        return
    buckets["already"].append(_pin_label(name, a_src, a_set))
    buckets["already_names"].append(name)


def _pin_label(name: str, src: str, settings: dict[str, str]) -> str:
    """Book plus source id and slug prefix when they add information."""
    prefix = (settings.get("slug_prefix") or "").strip()
    extras: list[str] = []
    if src:
        extras.append(src)
    if prefix and prefix.casefold() != src.casefold():
        extras.append(f"prefix {prefix}")
    return f"{name} ({', '.join(extras)})" if extras else name


def _book_change_label(
    name: str,
    b_src: str,
    b_set: dict[str, str],
    a_src: str,
    a_set: dict[str, str],
) -> str:
    """Source-id and/or prefix change, or empty when the pin is unchanged."""
    bits: list[str] = []
    b_pfx = (b_set.get("slug_prefix") or "").strip()
    a_pfx = (a_set.get("slug_prefix") or "").strip()
    if a_src != b_src:
        bits.append(f"{b_src or '—'} → {a_src or '—'}")
    if a_pfx != b_pfx:
        bits.append(f"prefix {b_pfx} → {a_pfx}" if b_pfx and a_pfx else f"prefix {a_pfx or 'cleared'}")
    return f"{name} {', '.join(bits)}" if bits else ""


def _league_meta_bits(parent: LeagueRow, child: LeagueRow) -> list[str]:
    """Non-exchange field diffs that still change the live league row."""
    bits: list[str] = []
    if (parent.optic_league_id or "") != (child.optic_league_id or ""):
        bits.append(f"optic id {parent.optic_league_id} → {child.optic_league_id}")
    if (parent.sport or "") != (child.sport or ""):
        bits.append(f"sport {parent.sport} → {child.sport}")
    if float(parent.fixture_horizon_hours or 0) != float(child.fixture_horizon_hours or 0):
        p_h = float(parent.fixture_horizon_hours or 0)
        c_h = float(child.fixture_horizon_hours or 0)
        bits.append(f"horizon {p_h:g}h → {c_h:g}h")
    if list(parent.extra_optic_league_ids or []) != list(child.extra_optic_league_ids or []):
        bits.append("extra optic ids changed")
    if list(parent.output_order or []) != list(child.output_order or []):
        bits.append("output order changed")
    if bool(parent.enabled) != bool(child.enabled):
        bits.append("enable league" if child.enabled else "disable league")
    return bits


def _mod_phrases(enabled: list[str], disabled: list[str], changed: list[str]) -> list[str]:
    """Enable / disable / change fragments for the update sentence."""
    bits: list[str] = []
    if enabled:
        bits.append(f"Enable {', '.join(enabled)}")
    if disabled:
        bits.append(f"disable {', '.join(disabled)}")
    if changed:
        bits.append(f"change {', '.join(changed)}")
    return bits


def _dedupe(refs: list[str]) -> list[str]:
    """Keep first-seen evidence refs."""
    out: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        key = ref.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def league_pin_refs(league: MappingLeaguePayload) -> list[str]:
    """Structured refs from submitted pins (no live re-probe)."""
    refs = [str(r).strip() for r in league.evidence_refs if str(r).strip()]
    optic = league.optic_league_id.strip()
    if optic:
        refs.append(f"optic:id:{optic}")
    for book, enabled, source, profile, _settings in _ex_rows(league.exchanges):
        if not enabled:
            continue
        if source:
            refs.append(f"{book}:id:{source}")
        if profile:
            refs.append(f"{book}:parser:{profile}")
    if league.notes:
        refs.append(f"note:{league.notes}")
    return _dedupe(refs)


def payload_league_refs(payload: object) -> list[str]:
    """League pin refs from a single league or a batch."""
    if isinstance(payload, MappingLeaguePayload):
        return league_pin_refs(payload)
    if isinstance(payload, BatchChangesPayload):
        refs: list[str] = []
        for league in payload.leagues:
            refs.extend(league_pin_refs(league))
        return _dedupe(refs)
    return []


def payload_alias_refs(payload: object) -> list[str]:
    """Harvest/source evidence_refs copied onto alias payloads."""
    if isinstance(payload, EntityAliasPayload):
        return _dedupe([str(r).strip() for r in payload.evidence_refs if str(r).strip()])
    if isinstance(payload, BatchChangesPayload):
        refs: list[str] = []
        for alias in payload.entity_aliases:
            refs.extend(str(r).strip() for r in alias.evidence_refs if str(r).strip())
        return _dedupe(refs)
    return []


def probe_evidence_refs(probes: list[dict[str, Any]], optic: str) -> list[str]:
    """Chat onboard probe hits and intentional skips."""
    refs: list[str] = []
    if optic.strip():
        refs.append(f"optic:id:{optic.strip()}")
    for row in probes:
        refs.extend(_probe_row_refs(row))
    return _dedupe(refs)


def _probe_row_refs(row: dict[str, Any]) -> list[str]:
    """One probe row → fixture / prefix / skip refs."""
    refs: list[str] = []
    book = str(row.get("book") or "")
    if row.get("fixture_count") is not None:
        refs.append(f"optic:fixtures:{row['fixture_count']}")
    source = str(row.get("source") or "").strip()
    if source and row.get("evidence"):
        refs.append(f"harvest:{row.get('book')}:{source}")
    if row.get("evidence"):
        return refs
    reason = str(row.get("note") or row.get("error") or "").strip()
    if book and reason:
        refs.append(f"skip:{book}:{reason}")
    return refs
