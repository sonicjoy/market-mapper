"""Resolve LeagueConfig from the activated tip via parser profiles.

Every enabled tip league is built by the ``(profile_id, sport)`` registry.
There is no Python league archive: an empty ``python_leagues`` map is the
only run-set path.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from mappers.pipeline import LeagueConfig
from mappers.seed.code_leagues import code_league_configs
from mappers.seed.fixture_sources import FIXTURE_SOURCE_API
from mappers.seed.sot import (
    load_snapshot,
    overlay_league_config,
    poly_team_name_aliases,
    tip_entity_type,
)
from mappers.seed.tip_factories import (
    apply_tip_exchange_settings,
    build_tip_league,
    tip_only_ok,
    with_code_dkex,
    with_code_novig,
    with_code_poly_usa,
    with_code_sxbet,
    with_code_underdog,
)

__all__ = [
    "api_fetch_league_keys",
    "apply_tip_exchange_settings",
    "league_config_from_tip_row",
    "load_tip_leagues",
    "resolve_run_leagues",
    "resolved_run_leagues",
]


def load_tip_leagues() -> dict[str, LeagueConfig]:
    """Build the run set purely from the activated tip (fixture or live BQ)."""
    snap = load_snapshot()
    return resolve_run_leagues(
        {},
        list(snap.leagues),
        market_rules=list(snap.market_rules),
    )


def resolve_run_leagues(
    python_leagues: dict[str, LeagueConfig],
    tip_rows: list[Any],
    *,
    market_rules: list[Any] | None = None,
    filter_keys: list[str] | None = None,
) -> dict[str, LeagueConfig]:
    """Build the map run set from enabled tip rows (M5).

    Tip-only known-profile leagues are included. ``filter_keys``
    (``--league``) still restricts the set when provided. A slug that is
    present on the tip but disabled / tombstoned is excluded even when
    passed via ``filter_keys`` — the tip wins; do not revive it from
    the Python registry. An empty enabled tip falls back to Python.
    """
    by_slug = {
        str(row.league): row
        for row in tip_rows
        if getattr(row, "enabled", True) and not getattr(row, "tombstone", False)
    }
    on_tip = {str(row.league) for row in tip_rows}
    code = code_league_configs()
    python_leagues = {**code, **python_leagues}
    wanted = _wanted_slugs(python_leagues, by_slug, on_tip, filter_keys)
    # Code leagues join the tip's; a slug on the tip keeps the tip's config.
    wanted += [
        slug for slug in sorted(code)
        if slug not in on_tip and slug not in wanted and not filter_keys
    ]
    return _build_run_set(python_leagues, by_slug, wanted, market_rules)


def resolved_run_leagues(
    python_leagues: dict[str, LeagueConfig],
) -> dict[str, LeagueConfig]:
    """Python registry overlaid / extended from the activated tip."""
    snap = load_snapshot()
    return resolve_run_leagues(
        python_leagues,
        list(snap.leagues),
        market_rules=list(snap.market_rules) or None,
    )


def api_fetch_league_keys(
    python_leagues: dict[str, LeagueConfig],
    *,
    exclude: set[str] | frozenset[str] | None = None,
    tip_rows: list[Any] | None = None,
) -> list[str]:
    """League keys for the API fetch + map tick.

    Uses the enabled tip when ``tip_rows`` is omitted. Drops tip rows
    whose fixture_source is not api (bq / synthetic). Empty tip falls
    back to the Python registry.
    """
    skip = set(exclude or ())
    rows = tip_rows
    if rows is None:
        rows = list(load_snapshot().leagues)
    rows = rows or []
    run = resolve_run_leagues(python_leagues, rows)
    by_slug = {str(row.league): row for row in rows}
    return _api_keys(run, by_slug, skip)


def league_config_from_tip_row(
    row: Any,
    python_cfg: LeagueConfig | None,
) -> LeagueConfig | None:
    """Overlay tip settings onto a Python config, or build a tip-only cfg."""
    if python_cfg is not None:
        return apply_tip_exchange_settings(python_cfg, row)
    if tip_only_ok(row):
        return build_tip_league(row)
    return None


def _wanted_slugs(
    python_leagues: dict[str, LeagueConfig],
    by_slug: dict[str, Any],
    on_tip: set[str],
    filter_keys: list[str] | None,
) -> list[str]:
    if filter_keys:
        return [
            key
            for key in filter_keys
            if key in by_slug or (key not in on_tip and key in python_leagues)
        ]
    return sorted(by_slug) if by_slug else sorted(python_leagues)


def _build_run_set(
    python_leagues: dict[str, LeagueConfig],
    by_slug: dict[str, Any],
    wanted: list[str],
    market_rules: list[Any] | None,
) -> dict[str, LeagueConfig]:
    out: dict[str, LeagueConfig] = {}
    for slug in wanted:
        row = by_slug.get(slug)
        if row is not None:
            cfg = league_config_from_tip_row(row, python_leagues.get(slug))
        elif slug in python_leagues:
            cfg = python_leagues[slug]
        else:
            continue
        if cfg is None:
            continue
        cfg = with_code_dkex(cfg, slug)
        cfg = with_code_sxbet(cfg, slug)
        cfg = with_code_underdog(cfg, slug)
        cfg = with_code_novig(cfg, slug)
        if market_rules:
            cfg = overlay_league_config(cfg, market_rules, league_row=row)
        cfg = with_code_poly_usa(cfg)
        cfg = _stamp_poly_name_aliases(cfg, slug)
        out[slug] = cfg
    return out


def _api_keys(
    run: dict[str, LeagueConfig],
    by_slug: dict[str, Any],
    skip: set[str],
) -> list[str]:
    out: list[str] = []
    for slug in sorted(run):
        if slug in skip:
            continue
        row = by_slug.get(slug)
        if row is not None:
            src = str(getattr(row, "fixture_source", "") or "").lower()
            if src and src != FIXTURE_SOURCE_API:
                continue
        out.append(slug)
    return out


def _stamp_poly_name_aliases(cfg: LeagueConfig, slug: str) -> LeagueConfig:
    """Copy tip Polymarket name aliases onto the config overlay table."""
    poly = cfg.POLYMARKET
    if poly is None:
        return cfg
    snap = load_snapshot()
    overlay = poly_team_name_aliases(
        snap.entities,
        league=slug,
        question_style=str(poly.question_style or "mlb_suffix"),
        entity_type=tip_entity_type(snap, slug),
    )
    if not overlay:
        return cfg
    merged = {**dict(poly.team_name_aliases), **overlay}
    if merged == dict(poly.team_name_aliases):
        return cfg
    return replace(cfg, POLYMARKET=replace(poly, team_name_aliases=merged))
