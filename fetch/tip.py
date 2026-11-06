"""Fetch-side tip resolution without importing LEAGUES or League."""

from __future__ import annotations

from typing import Any

from mappers.exchanges.optic import OpticConfig
from mappers.profiles._builders import exchange_settings
from mappers.seed.league_meta import league_settings_from_row
from mappers.seed.sot import load_snapshot
from mappers.seed.tip_leagues import resolved_run_leagues

# Secret Manager entry names, not credential values.
_TENNIS_SECRET = "opticodds_parlay_tennis_access_key"  # nosec B105
_STANDARD_SECRET = "opticodds_access_key"  # nosec B105
_TENNIS_LEAGUES = frozenset({
    "atp", "atp_challenger", "itf_men", "itf_women", "wta", "wta_doubles",
})


def resolved_leagues() -> dict[str, Any]:
    """Active run set for fetch from the activated tip."""
    return resolved_run_leagues({})


def tip_league_rows() -> dict[str, Any]:
    """Enabled tip league rows keyed by slug (fixture or live BQ when available)."""
    try:
        snap = load_snapshot()
    except (FileNotFoundError, RuntimeError):
        return {}
    return {
        str(row.league): row
        for row in snap.leagues
        if getattr(row, "enabled", True) and not getattr(row, "tombstone", False)
    }


def _exchange_settings(league: str, sportsbook: str) -> dict[str, Any]:
    row = tip_league_rows().get(league)
    if row is None:
        return {}
    for ex in getattr(row, "exchanges", None) or []:
        if not ex.get("enabled", True):
            continue
        if str(ex.get("sportsbook") or "") == sportsbook:
            return exchange_settings(ex, sportsbook)
    return {}


def supported_optic_leagues() -> dict[str, OpticConfig]:
    """League slug -> OpticConfig for fetch coverage."""
    return {
        slug: cfg.OPTIC
        for slug, cfg in resolved_leagues().items()
        if cfg.OPTIC is not None
    }


def optic_api_key_secret(league: str) -> str:
    """GCP secret name for OpticOdds API key (tip row, else python archive)."""
    secret = _exchange_settings(league, "optic").get("api_key_secret")
    if secret:
        return str(secret)
    if league in _TENNIS_LEAGUES:
        return _TENNIS_SECRET
    return _STANDARD_SECRET


def px_tournament_ids() -> dict[str, int]:
    """League slug -> ProphetX tournament_id from the resolved run set."""
    out: dict[str, int] = {}
    for slug, cfg in resolved_leagues().items():
        px = cfg.PX
        if px is not None and px.tournament_id is not None:
            out[slug] = int(px.tournament_id)
    return out


def novig_league_map() -> dict[str, str]:
    """League slug -> Novig league string from the resolved run set."""
    return {
        slug: cfg.NOVIG.league
        for slug, cfg in resolved_leagues().items()
        if cfg.NOVIG is not None
    }


def underdog_league_map() -> dict[str, str]:
    """League slug -> UDX sport token (``NFL``, ``NCAAMFB``, ...) from the resolved run set."""
    return {
        slug: cfg.UNDERDOG.league
        for slug, cfg in resolved_leagues().items()
        if cfg.UNDERDOG is not None
    }


def underdog_requested(leagues: list[str]) -> bool:
    """True when any requested league resolves with an Underdog config."""
    wanted = set(leagues)
    return any(slug in wanted for slug in underdog_league_map())


def stx_requested(leagues: list[str]) -> bool:
    """True when any requested league is the run-set league of an STX competition (``stx_leagues``)."""
    from mappers.exchanges.stx_leagues import COMPETITIONS

    wanted = set(leagues)
    return any(c.slug in wanted for c in COMPETITIONS.values() if c.slug)


def runshop_requested(leagues: list[str]) -> bool:
    """True when any requested league has runshop on the tip row."""
    return _book_requested(leagues, "runshop", meta_flag="runshop_enabled")


def huddle_requested(leagues: list[str]) -> bool:
    """True when any requested league has an enabled Huddle tip pin."""
    return _book_requested(leagues, "huddle")


def _book_requested(
    leagues: list[str],
    sportsbook: str,
    *,
    meta_flag: str | None = None,
) -> bool:
    """True when the tip enables this sportsbook for a requested league."""
    rows = tip_league_rows()
    for slug in leagues:
        row = rows.get(slug)
        if row is None:
            continue
        if meta_flag and league_settings_from_row(row).get(meta_flag):
            return True
        for ex in getattr(row, "exchanges", None) or []:
            if ex.get("sportsbook") == sportsbook and ex.get("enabled", True):
                return True
    return False
