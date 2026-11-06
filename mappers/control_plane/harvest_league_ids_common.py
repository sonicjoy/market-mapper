"""Shared helpers for league exchange-id harvest."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from mappers.control_plane.suggest_aliases import fetch_optic_fixtures

FixturesFn = Callable[..., list[dict[str, Any]]]

_SPORT_GROUPING: dict[str, str] = {
    "soccer": "SOCCER",
    "tennis": "TENNIS",
    "esports": "ESPORT",
    "mma": "MMA",
    "boxing": "MMA",
}


def fetch_league_fixtures(
    optic_league_id: str,
    horizon_hours: float,
    fixtures_fn: FixturesFn | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Optic fixtures for one league; surface fetch errors instead of [] silently."""
    optic = optic_league_id.strip()
    if not optic:
        return [], None
    try:
        if fixtures_fn is not None:
            return list(fixtures_fn(optic, horizon_hours=horizon_hours)), None
        return list(fetch_optic_fixtures(optic, horizon_hours=horizon_hours)), None
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)[:160]


def league_match_needles(
    league: str,
    optic_league_id: str,
    fixtures: list[dict[str, Any]],
) -> list[str]:
    """League display names for PX/Poly matching — never team names."""
    names: list[str] = []
    for fx in fixtures:
        league_obj = fx.get("league")
        if isinstance(league_obj, dict):
            label = str(league_obj.get("name") or "").strip()
            if label:
                names.append(label)
    if not names:
        names = [_humanize(optic_league_id), _humanize(league)]
    out: list[str] = []
    for name in names:
        norm = _norm(name)
        if norm and norm not in out:
            out.append(norm)
    return out


def title_matches_league(title: str, needle: str) -> bool:
    """Fail closed on loose substring hits; allow exact single-token titles."""
    if not title or not needle:
        return False
    if title == needle:
        return True
    needle_tokens = needle.split()
    if len(needle_tokens) < 2:
        return False
    title_tokens = set(title.split())
    return (
        set(needle_tokens) <= title_tokens
        or (len(title_tokens) >= 2 and title_tokens <= set(needle_tokens))
    )


def crypto_settings_from_meta(
    meta_league: str,
    sport: str,
    *,
    sport_grouping: str | None = None,
) -> dict[str, str]:
    """settings.league + settings.sport_grouping for crypto_generic_v1."""
    meta = meta_league.strip()
    sport_l = sport.strip().lower()
    grouping = (sport_grouping or "").strip() or _SPORT_GROUPING.get(sport_l, meta.upper())
    if sport_l == "football" and meta.upper() in {"NFL", "CFB"}:
        grouping = meta.upper()
    if sport_l == "basketball" and meta.upper() in {"NBA", "WNBA", "CBB"}:
        grouping = meta.upper()
    return {"league": meta, "sport_grouping": grouping}


def archive_crypto_pin(league_slug: str, sport: str) -> dict[str, Any] | None:
    """crypto.com meta from the python archive when the slug is already wired."""
    cfg = _archive_cfg(league_slug)
    if cfg is None or cfg.CRYPTO is None:
        return None
    meta = str(cfg.CRYPTO.league or "").strip()
    if not meta:
        return None
    settings = crypto_settings_from_meta(
        meta,
        sport,
        sport_grouping=str(cfg.CRYPTO.sport_grouping or ""),
    )
    return {
        "ok": True,
        "book": "crypto.com",
        "evidence": True,
        "source": meta,
        "settings": settings,
    }


def archive_underdog_pin(league_slug: str) -> dict[str, Any] | None:
    """Underdog venue league token from the python archive when wired."""
    cfg = _archive_cfg(league_slug)
    if cfg is None or getattr(cfg, "UNDERDOG", None) is None:
        return None
    code = str(cfg.UNDERDOG.league or "").strip().upper()
    if not code:
        return None
    return {
        "ok": True,
        "book": "underdog",
        "evidence": True,
        "source": code,
        "league": code,
    }


def archive_novig_pin(league_slug: str) -> dict[str, Any] | None:
    """Novig league string from the python archive when the slug is already wired."""
    cfg = _archive_cfg(league_slug)
    if cfg is None or cfg.NOVIG is None:
        return None
    code = str(cfg.NOVIG.league or "").strip()
    if not code:
        return None
    return {
        "ok": True,
        "book": "novig",
        "evidence": True,
        "source": code,
        "league": code,
    }


def fixtures_by_optic_window(
    optic_league_id: str,
    fixtures: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Gap-propose-shaped Optic index for official Polymarket unique bind."""
    from mappers.control_plane.gap_fix_poly_bq import fetch_optic_window
    from mappers.control_plane.poly_us_match import normalize_fixture

    by_optic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    optic = optic_league_id.strip()
    for row in fetch_optic_window():
        oid = str(row.get("optic_league_id") or "").strip()
        if oid:
            by_optic[oid].append(normalize_fixture(row))
    if optic and fixtures:
        stamped = [
            normalize_fixture({**fx, "optic_league_id": optic}) for fx in fixtures
        ]
        by_optic[optic] = stamped + by_optic.get(optic, [])
    return dict(by_optic)


def exchange_pin_on_tip(row: Any, sportsbook: str) -> dict[str, Any] | None:
    """Full enabled exchange pin from a tip row, or None when unwired."""
    book = sportsbook.strip().lower()
    for ex in getattr(row, "exchanges", None) or []:
        if str(ex.get("sportsbook") or "").lower() != book:
            continue
        if ex.get("enabled") is False:
            return None
        settings = ex.get("settings") if isinstance(ex.get("settings"), dict) else {}
        source = exchange_source_on_pin(ex, book)
        if not source and book != "optic":
            return None
        return {
            "sportsbook": book,
            "enabled": True,
            "parser_profile": str(ex.get("parser_profile") or ""),
            "source_league_id": source or None,
            "settings": dict(settings),
        }
    return None


def exchange_source_on_pin(ex: dict[str, Any], sportsbook: str) -> str:
    """Non-empty source id on one exchange pin."""
    book = sportsbook.strip().lower()
    src = str(ex.get("source_league_id") or "").strip()
    if src:
        return src
    settings = ex.get("settings") or {}
    if not isinstance(settings, dict):
        return ""
    if book in {"polymarket", "polymarket_usa"}:
        return str(settings.get("slug_prefix") or "").strip()
    if book == "novig":
        return str(settings.get("league") or "").strip()
    if book == "crypto.com":
        return str(settings.get("league") or "").strip()
    if book == "px":
        return str(settings.get("tournament_id") or "").strip()
    if book == "underdog":
        return str(settings.get("league") or "").strip()
    if book == "dkex":
        return str(settings.get("league") or "").strip()
    return ""


def wired_probe_row(row: Any, sportsbook: str) -> dict[str, Any] | None:
    """Chat/Editor skip row preserving tip settings (PX tournament_id, crypto grouping)."""
    pin = exchange_pin_on_tip(row, sportsbook)
    if pin is None:
        return None
    book = sportsbook.strip().lower()
    source = str(pin.get("source_league_id") or "").strip()
    if book == "optic" and not source:
        return None
    return {
        "ok": True,
        "book": book,
        "evidence": True,
        "source": source,
        "settings": dict(pin.get("settings") or {}),
        "note": "already wired on tip",
        "skipped_probe": True,
    }


def _archive_cfg(slug: str) -> Any | None:
    from mappers.run import LEAGUES

    return LEAGUES.get(slug.strip())


def _humanize(text: str) -> str:
    raw = text.strip().replace("_-_", " ").replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", raw).strip()


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
