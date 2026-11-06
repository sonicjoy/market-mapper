"""Read-only crypto.com gap probe: catalogue × tip crypto_id × Optic fixture."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from mappers.canonical_codes import person_league
from mappers.control_plane.chat_tools_mapping import mapping_fn_from_args, row_from_mapping
from mappers.control_plane.crypto_alias_correct import hold_kind
from mappers.control_plane.crypto_optic_match import (
    catalogue_sides,
    day_names_a_side,
    match_optic_fixture,
    name_sides,
)
from mappers.control_plane.evidence_format import optic_identity_refs
from mappers.control_plane.gap_crypto_catalogue import catalogue_lookup
from mappers.control_plane.gap_fix_skip import crypto_id_labels
from mappers.control_plane.gap_fix_tip import (
    index_tip_leagues,
    indexed_crypto_owners,
    league_tip,
)
from mappers.control_plane.gap_optic_cache import cached_optic_fixtures, optic_horizon_hours
from mappers.crypto_meta import is_tennis_crypto_league, narrow_crypto_leagues

CatalogueFn = Callable[[str], dict[str, Any]]
FixturesFn = Callable[..., list[dict[str, Any]]]

_NX = re.compile(r"^NX\.F\.OPT\.([A-Z0-9]+)", re.I)
_FUTURES = re.compile(r"-20\d{2}\.O\.", re.I)
_MAX_SYMBOLS = 5


def run_probe_crypto_gap(store: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Probe crypto.com symbols: market_mapping first, then catalogue."""
    symbols = _symbols_from_args(args)
    if not symbols:
        return {"ok": False, "warnings": ["symbol is required"]}
    league = str(args.get("league") or "").strip() or None
    mapping_fn = mapping_fn_from_args(args)
    hits = {symbol: mapping_fn(symbol) for symbol in symbols}
    catalogue_fn = args.get("catalogue_fn") or _default_catalogue
    fixtures_fn = args.get("fixtures_fn")
    now = _as_utc(args.get("now"))
    tips = args.get("tips")
    if tips is None:
        tips = index_tip_leagues(store)
    rows = [
        row_from_mapping(symbol, hits[symbol])
        if hits[symbol]
        else _probe_one(store, symbol, league, catalogue_fn, fixtures_fn, now, tips)
        for symbol in symbols
    ]
    return {"ok": all(r.get("ok") for r in rows), "count": len(rows), "results": rows}


def _symbols_from_args(args: dict[str, Any]) -> list[str]:
    """Deduped NX symbols from symbol / symbols."""
    raw: list[str] = []
    one = str(args.get("symbol") or "").strip()
    if one:
        raw.append(one)
    extra = args.get("symbols") or []
    if isinstance(extra, list):
        raw.extend(str(s).strip() for s in extra)
    seen: set[str] = set()
    out: list[str] = []
    for symbol in raw:
        if symbol and symbol not in seen:
            seen.add(symbol)
            out.append(symbol)
        if len(out) >= _probe_limit(args):
            break
    return out


def _probe_limit(args: dict[str, Any]) -> int:
    raw = args.get("probe_limit")
    if raw is not None:
        return max(1, int(raw))
    return _MAX_SYMBOLS


def _as_utc(value: Any) -> datetime:
    """Coerce probe clock to aware UTC (injectable `now` for tests)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _default_catalogue(symbol: str) -> dict[str, Any]:
    """Live BQ catalogue lookup; soft miss."""
    try:
        return catalogue_lookup(symbol)
    except Exception as exc:  # noqa: BLE001 — chat tools soft-fail
        return {"ok": False, "seen": False, "symbol": symbol, "error": str(exc)[:160]}


def _parse_symbol(symbol: str) -> dict[str, Any] | None:
    """NX.F.OPT.<token> plus tournament-future flag."""
    m = _NX.match(symbol.strip())
    if m is None:
        return None
    return {"token": m.group(1).upper(), "futures": bool(_FUTURES.search(symbol))}


def _probe_one(
    store: Any,
    symbol: str,
    league: str | None,
    catalogue_fn: CatalogueFn,
    fixtures_fn: FixturesFn | None,
    now: datetime,
    tips: Any,
) -> dict[str, Any]:
    """One symbol: parse, catalogue, then tip/Optic classify."""
    parsed = _parse_symbol(symbol)
    if parsed is None:
        return {"ok": True, "symbol": symbol, "kind": "parse_miss", "seen": False}
    cat = catalogue_fn(symbol)
    if not cat.get("ok") or not cat.get("seen"):
        return _miss_row(store, symbol, parsed, league, error=str(cat.get("error") or ""))
    return _probe_seen(store, symbol, league, parsed, cat, fixtures_fn, now, tips)


def _miss_row(
    store: Any, symbol: str, parsed: dict[str, Any], league: str | None, *, error: str = "",
) -> dict[str, Any]:
    """Catalogue miss: still surface NX token, inferred league, and sportsbook."""
    slugs = _infer_leagues(store, parsed["token"], league)
    return {
        "ok": True,
        "symbol": symbol,
        "sportsbook": "crypto.com",
        "league": slugs[0] if slugs else "",
        "leagues": slugs,
        "token": parsed["token"],
        "kind": "catalogue_miss",
        "mapped_rows": [],
        "crypto_ids": [],
        "tip": [],
        "optic": {},
        "error": error,
    }


def _probe_seen(
    store: Any,
    symbol: str,
    league: str | None,
    parsed: dict[str, Any],
    cat: dict[str, Any],
    fixtures_fn: FixturesFn | None,
    now: datetime,
    tips: Any,
) -> dict[str, Any]:
    """Catalogue hit: infer leagues, resolve ids, match Optic, classify."""
    slugs = _infer_leagues(store, parsed["token"], league)
    slugs = narrow_crypto_leagues(
        slugs, str(cat.get("meta_league") or ""), _league_rows(store),
    )
    hours = _hours_to_kick(cat, now)
    horizon = _horizon(store, slugs)
    timed = "tournament_future" if parsed.get("futures") else _time_kind(hours, horizon)
    ids = _catalogue_ids(cat)
    tip = _tip_resolve(store, slugs, ids, tips)
    if timed in {"completed_stale", "outside_horizon", "tournament_future"}:
        return _result(symbol, parsed, cat, slugs, ids, tip, None, timed, hours, horizon)
    optic = _optic_match(store, slugs, cat, fixtures_fn)
    kind = _classify(parsed, slugs, ids, tip, optic, hours, horizon)
    kind = _refine_mapped(kind, store, slugs, cat, ids, tip, optic, tips)
    return _result(symbol, parsed, cat, slugs, ids, tip, optic, kind, hours, horizon)


def _result(
    symbol: str,
    parsed: dict[str, Any],
    cat: dict[str, Any],
    slugs: list[str],
    ids: list[str],
    tip: list[dict[str, Any]],
    optic: dict[str, Any] | None,
    kind: str,
    hours: float | None,
    horizon: float,
) -> dict[str, Any]:
    """Kalshi-shaped probe row plus crypto catalogue fields."""
    return {
        "ok": True,
        "symbol": symbol,
        "sportsbook": "crypto.com",
        "league": _pick_league(slugs, optic),
        "leagues": slugs,
        "token": parsed["token"],
        "meta_name": cat.get("meta_name") or "",
        "meta_league": cat.get("meta_league") or "",
        "meta_event_date": cat.get("meta_event_date") or "",
        "contract_type": cat.get("contract_type") or "",
        "market_type": cat.get("market_type") or "",
        "player_id": cat.get("player_id") or "",
        "player_name": cat.get("player_name") or "",
        "crypto_ids": ids,
        "home_name": cat.get("home_name") or "",
        "away_name": cat.get("away_name") or "",
        "tip": tip,
        "optic": optic,
        "kind": kind,
        "hours_to_kick": hours,
        "horizon_hours": horizon,
        "mapped_rows": [],
        "evidence_refs": _evidence(symbol, cat, optic),
    }


def _catalogue_ids(cat: dict[str, Any]) -> list[str]:
    """Home/away EXTERNAL ids from catalogue, skipping blanks."""
    out: list[str] = []
    for key in ("home_id", "away_id"):
        val = str(cat.get(key) or "").strip()
        if val:
            out.append(val)
    return out


def _crypto_tokens(ex: dict[str, Any]) -> set[str]:
    """Symbol tokens this crypto.com exchange row can own."""
    raw = ex.get("settings")
    settings = raw if isinstance(raw, dict) else {}
    vals = [
        ex.get("source_league_id"),
        settings.get("league"),
        settings.get("sport_grouping"),
        settings.get("symbol_prefix"),
    ]
    return {str(v).strip().upper() for v in vals if v}


def _infer_leagues(store: Any, token: str, forced: str | None) -> list[str]:
    """NX token leagues win; caller league is fallback when the token is unwired."""
    needle = token.upper()
    hits: list[str] = []
    for row in _league_rows(store):
        for ex in row.exchanges or []:
            if str(ex.get("sportsbook") or "").lower() != "crypto.com":
                continue
            if needle in _crypto_tokens(ex):
                hits.append(row.league)
                break
    if hits:
        return hits
    if forced and _league_row(store, forced) is not None:
        return [forced]
    return []


def _league_row(store: Any, league: str) -> Any | None:
    """Tip league row by slug, or None."""
    return next((r for r in _league_rows(store) if r.league == league), None)


def _league_rows(store: Any) -> list[Any]:
    """Activated tip mapping_leagues rows."""
    rid = store.current_rule_set_id
    if not rid:
        return []
    return list(store.leagues_for(rid))


def _tip_resolve(store: Any, leagues: list[str], ids: list[str], tips: Any) -> list[dict[str, Any]]:
    """crypto_id → tip canonicals (all claimants across inferred leagues)."""
    if not ids:
        return []
    rows: list[dict[str, Any]] = []
    for cid in ids:
        owners: list[str] = []
        seen: set[str] = set()
        for league in leagues:
            for owner in indexed_crypto_owners(league_tip(store, league, tips), cid):
                if owner in seen:
                    continue
                seen.add(owner)
                owners.append(owner)
        rows.append({"crypto_id": cid, "owners": owners})
    return rows


def _optic_match(
    store: Any,
    leagues: list[str],
    cat: dict[str, Any],
    fixtures_fn: FixturesFn | None,
) -> dict[str, Any] | None:
    """First Optic fixture on the catalogue kickoff day (ids, then names)."""
    sides = catalogue_sides(cat)
    ids = _catalogue_ids(cat)
    day = str(cat.get("meta_event_date") or "")[:10]
    last: dict[str, Any] | None = None
    for tip_slug, optic_id in _optic_probe_targets(store, leagues):
        hit = _optic_one(
            store, tip_slug, optic_id, sides, ids, day, fixtures_fn,
        )
        if hit and hit.get("fixture_id"):
            hit["league"] = tip_slug
            return hit
        last = hit
    return last


def _optic_probe_targets(
    store: Any, tip_slugs: list[str],
) -> list[tuple[str, str]]:
    """(tip slug, optic league id) pairs — primary book plus extra_optic_league_ids."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for slug in tip_slugs:
        row = _league_row(store, slug)
        if row is None:
            continue
        primary = str(row.optic_league_id or "").strip()
        pairs = [(slug, primary)] if primary else []
        pairs.extend(
            (slug, str(extra).strip())
            for extra in (row.extra_optic_league_ids or [])
            if str(extra).strip()
        )
        for tip_slug, optic_id in pairs:
            key = (tip_slug, optic_id)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def _optic_one(
    store: Any,
    tip_slug: str,
    optic_league_id: str,
    sides: tuple[str, str] | None,
    ids: list[str],
    day: str,
    fixtures_fn: FixturesFn | None,
) -> dict[str, Any] | None:
    """Optic id-match then name-match; unique other-day hit before mismatch."""
    tip = _league_row(store, tip_slug)
    if tip is None or not optic_league_id:
        return None
    try:
        fixtures = list(cached_optic_fixtures(
            optic_league_id,
            horizon_hours=optic_horizon_hours(tip),
            fetch_fn=fixtures_fn,
        ))
    except Exception as exc:  # noqa: BLE001 — Optic is optional evidence
        return {"error": str(exc)[:160]}
    hit = match_optic_fixture(
        fixtures, sides, ids, day, player=person_league(tip_slug),
    )
    if hit:
        return hit
    if not fixtures or sides is None:
        return None
    if is_tennis_crypto_league(tip):
        return None
    if not day_names_a_side(
        fixtures, sides, day, player=person_league(tip_slug),
    ):
        return None
    return {"name_mismatch": True, "sides": [sides[0], sides[1]]}


def _pick_league(slugs: list[str], optic: dict[str, Any] | None) -> str | None:
    """Prefer optic-hit league, else first inferred slug."""
    if optic and optic.get("league"):
        return str(optic["league"])
    return slugs[0] if slugs else None


def _horizon(store: Any, leagues: list[str]) -> float:
    """Widest tip fixture horizon among inferred leagues (default 96)."""
    hours: list[float] = []
    for slug in leagues:
        row = _league_row(store, slug)
        if row is not None:
            hours.append(float(row.fixture_horizon_hours or 96))
    return max(hours) if hours else 96.0


def _hours_to_kick(cat: dict[str, Any], now: datetime) -> float | None:
    """Hours from now to catalogue kickoff; None if unparseable."""
    dt = _parse_kickoff(str(cat.get("meta_event_date") or ""))
    if dt is None:
        return None
    return (dt - now).total_seconds() / 3600.0


def _parse_kickoff(raw: str) -> datetime | None:
    """ISO kickoff to aware UTC."""
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _time_kind(hours: float | None, horizon: float) -> str | None:
    """Stale / outside-horizon residual when kickoff is known."""
    if hours is None:
        return None
    if hours < 0:
        return "completed_stale"
    if hours > horizon:
        return "outside_horizon"
    return None


def _classify(
    parsed: dict[str, Any],
    slugs: list[str],
    ids: list[str],
    tip: list[dict[str, Any]],
    optic: dict[str, Any] | None,
    hours: float | None,
    horizon: float,
) -> str:
    """Gap kind: parse/catalogue misses handled earlier."""
    if parsed.get("futures"):
        return "tournament_future"
    if not slugs:
        return "league_not_wired"
    timed = _time_kind(hours, horizon)
    if not ids:
        return timed or "catalogue_miss"
    if len(ids) < 2:
        return timed or "disambig"
    if optic and optic.get("name_mismatch"):
        return timed or "name_mismatch"
    if any(not row.get("owners") for row in tip):
        return timed or "unknown_alias"
    if optic is None or optic.get("error") or not optic.get("fixture_id"):
        return timed or "missing_optic"
    return "unmapped"


def _refine_mapped(
    kind: str,
    store: Any,
    slugs: list[str],
    cat: dict[str, Any],
    ids: list[str],
    tip: list[dict[str, Any]],
    optic: dict[str, Any] | None,
    tips: Any,
) -> str:
    """Alias hits are not mapped. Wrong Optic owner → correction card."""
    if kind != "unmapped" or not isinstance(optic, dict) or not optic.get("fixture_id"):
        return kind
    league = _pick_league(slugs, optic)
    if not league:
        return kind
    refined = hold_kind(
        league_tip(store, league, tips), league, ids, crypto_id_labels(cat, ids), tip, optic,
    )
    return refined or kind


def _evidence(symbol: str, cat: dict[str, Any], optic: dict[str, Any] | None) -> list[str]:
    """Evidence refs for a later entity_alias proposal."""
    refs = [f"gap:{symbol}"]
    title = str(cat.get("meta_name") or "").strip()
    if title:
        refs.append(f"crypto:title:{title}")
    refs.extend(_crypto_name_refs(cat, title))
    refs.extend(optic_identity_refs(optic))
    return refs


def _crypto_name_refs(cat: dict[str, Any], title: str) -> list[str]:
    """Participant crypto:name refs; never the event title."""
    home = str(cat.get("home_name") or "").strip()
    away = str(cat.get("away_name") or "").strip()
    if not home or not away:
        sides = name_sides(title)
        if sides is not None:
            home = home or sides[0]
            away = away or sides[1]
    return [f"crypto:name:{n}" for n in dict.fromkeys([home, away]) if n]
