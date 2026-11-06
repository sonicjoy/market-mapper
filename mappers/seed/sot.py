"""Legacy loader: the activated BQ rule-set tip, COW-coalesced.

Classify still reads the tip (``mapping_entities`` /
``mapping_market_rules`` coalesced tip→root). The tip is retiring and is
being replaced by code-owned tables; do not add rules here or on the
tip, new rules go in code (see CLAUDE.md). Tests
use ``tests/fixtures/sot/tip.json`` via ``MAPPING_SOT_FIXTURE`` (set
automatically in ``tests/conftest.py``).
"""

from __future__ import annotations

import ast
import os
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from mappers.alias_kinds import OPTIC_ID_KINDS
from mappers.exchanges.polymarket import _norm_name
from mappers.handicap_name_crumb import is_selection_alias
from mappers.seed.league_meta import invert_entity_type, league_settings_from_row, runshop_enabled_on_row
from mappers.seed.overlay_taxonomy import (
    league_rules,
    overlay_crypto,
    overlay_huddle,
    overlay_novig,
    overlay_optic,
    overlay_poly,
    overlay_px,
    overlay_runshop,
    overlay_underdog,
)
from mappers.shared import AliasData, AliasMap, CollisionEntry
from mappers.vocab.kalshi_scopes import scope_types

__all__ = [
    "SotSnapshot",
    "entities_to_alias_data",
    "load_live_snapshot",
    "load_snapshot",
    "overlay_league_config",
    "poly_team_name_aliases",
    "reset_sot_cache",
]

if TYPE_CHECKING:
    from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow

_TEST_PROJECT = "marketmaking-test"

# BQ (sportsbook, alias_kind) → load_aliases exchange key.
_EXCHANGE_KEY = {
    ("kalshi", "code"): "kalshi",
    ("crypto.com", "external_id"): "crypto_id",
    ("crypto.com", "crypto_id"): "crypto_id",
    ("crypto.com", "name"): "crypto_name",
    ("px", "code"): "px",
    ("polymarket", "name"): "polymarket",
    ("polymarket_usa", "code"): "polymarket_usa",
    ("underdog", "code"): "underdog",
    # DKEX team display name (metadata.participants[].name) -> canonical.
    ("dkex", "name"): "dkex",
}


@dataclass(frozen=True)
class SotSnapshot:
    """Coalesced tip used for one mapping run."""

    rule_set_id: str
    entities: list[EntityRow]
    market_rules: list[MarketRuleRow]
    leagues: list[LeagueRow] = field(default_factory=list)


_SNAP: SotSnapshot | None = None


def reset_sot_cache() -> None:
    """Drop the process snapshot (tests / next map tick)."""
    global _SNAP
    _SNAP = None


def load_live_snapshot() -> SotSnapshot:
    """Read the activated tip straight from BigQuery, ignoring any fixture.

    Used by ``scripts/build_sot_fixture.py`` to regenerate the offline
    fixture; the mapper itself goes through :func:`load_snapshot`.
    """
    # Lazy: BigQueryStore pulls control_plane.service; keep this module
    # import-safe for the mapper (circular via entry_structured otherwise).
    from BigQuery.client import ro_client
    from mappers.control_plane.bq_store import BigQueryStore

    project = os.environ.get("GCP_PROJECT") or ""
    environment = "test" if project == _TEST_PROJECT else "prod"
    store = BigQueryStore(ro_client(), environment=environment, allow_activate=False)
    tip = store.current_rule_set_id
    if not tip:
        raise RuntimeError(f"no activated mapping_rule_sets tip in project {project!r}")
    return SotSnapshot(
        rule_set_id=tip,
        entities=store.entities_for(tip),
        market_rules=store.market_rules_for(tip),
        leagues=store.leagues_for(tip),
    )


def load_snapshot() -> SotSnapshot:
    """Resolve the live tip and COW-coalesce entities + market rules.

    Live classify (test/prod VM) has no ``MAPPING_SOT_FIXTURE`` and reads
    BigQuery. Tests set that env to the offline JSON fixture.
    """
    global _SNAP
    if _SNAP is not None:
        return _SNAP
    from mappers.seed.fixture_store import fixture_path, load_fixture

    path = fixture_path()
    _SNAP = load_fixture(path) if path is not None else load_live_snapshot()
    return _SNAP


def _enabled_entities(
    entities: list[EntityRow],
    *,
    league: str,
    entity_type: str,
) -> Iterator[EntityRow]:
    """Yield enabled entities in one league/type."""
    for ent in entities:
        if ent.league != league or ent.entity_type != entity_type or not ent.enabled:
            continue
        yield ent


def _alias_fields(alias: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return (sportsbook, kind, value) for an enabled alias with a value."""
    if alias.get("enabled") is False:
        return None
    value = str(alias.get("alias_value") or "")
    if not value:
        return None
    return (
        str(alias.get("sportsbook") or ""),
        str(alias.get("alias_kind") or ""),
        value,
    )


def _register_exchange_alias(
    ex_map: AliasMap,
    exchange: str,
    value: str,
    canonical: str,
) -> None:
    """Insert one alias into an exchange map, including PX collision tables."""
    if exchange == "px" and value.startswith("{") and "abbr" in value:
        parsed = ast.literal_eval(value)
        if not isinstance(parsed, dict):
            raise ValueError(f"invalid px collision alias: {value!r}")
        entry = CollisionEntry(
            canonical=canonical,
            id=int(parsed["id"]),
            name=str(parsed["name"]),
        )
        abbr = str(parsed["abbr"])
        existing = ex_map.get(abbr)
        if existing is None:
            ex_map[abbr] = [entry]
        elif isinstance(existing, list):
            existing.append(entry)
        else:
            raise ValueError(
                f"Alias {abbr!r} has both simple and collision entries",
            )
        return
    ex_map[value] = canonical


def entities_to_alias_data(
    entities: list[EntityRow],
    *,
    league: str,
    entity_type: str,
) -> tuple[AliasData, dict[str, str]]:
    """Invert tip entities to pipeline AliasData + optic_id overrides."""
    by_exchange: dict[str, AliasMap] = {}
    canonicals: set[str] = set()
    optic_overrides: dict[str, str] = {}
    for ent in _enabled_entities(entities, league=league, entity_type=entity_type):
        canonicals.add(ent.canonical_key)
        for alias in ent.aliases:
            fields = _alias_fields(alias)
            if fields is None:
                continue
            sportsbook, kind, value = fields
            if sportsbook == "polymarket" and kind == "name" and is_selection_alias(value):
                continue
            if sportsbook == "optic" and kind in OPTIC_ID_KINDS:
                optic_overrides[value] = ent.canonical_key
                continue
            exchange = _EXCHANGE_KEY.get((sportsbook, kind))
            if exchange is None:
                continue
            _register_exchange_alias(
                by_exchange.setdefault(exchange, {}),
                exchange,
                value,
                ent.canonical_key,
            )
    return AliasData(by_exchange, canonicals), optic_overrides


def _poly_overlay_pair(
    poly_name: str,
    optic_name: str,
    style: str,
) -> tuple[str, str] | None:
    """Normalized poly question name → Optic fixture name, or None if identity."""
    left = _norm_name(poly_name, style)
    right = _norm_name(optic_name, style)
    if not left or not right or left == right:
        return None
    return left, right


def poly_team_name_aliases(
    entities: list[Any],
    *,
    league: str,
    question_style: str = "mlb_suffix",
    entity_type: str | None = None,
) -> dict[str, str]:
    """Polymarket display-name overlay for ``team_alias_scope``.

    Tip entities store poly question names as ``(polymarket, name)`` aliases
    whose ``canonical_name`` is the Optic fixture name. Keys and values are
    ``_norm_name``'d with ``question_style`` so ``_name_match`` can look them
    up. Identity aliases (same after normalize) are omitted.
    """
    out: dict[str, str] = {}
    types = (entity_type,) if entity_type else ("team", "fighter")
    for match_type in types:
        out.update(
            _poly_overlays_for_type(entities, league, match_type, question_style),
        )
    return out


def _poly_overlays_for_type(
    entities: list[Any],
    league: str,
    match_type: str,
    question_style: str,
) -> dict[str, str]:
    """Polymarket name overlays for one entity_type bucket."""
    out: dict[str, str] = {}
    for ent in _enabled_entities(entities, league=league, entity_type=match_type):
        name = str(getattr(ent, "canonical_name", "") or "").strip()
        if not name:
            continue
        for alias in ent.aliases:
            fields = _alias_fields(alias)
            if fields is None:
                continue
            sportsbook, kind, value = fields
            if sportsbook != "polymarket" or kind != "name":
                continue
            if is_selection_alias(value):
                continue
            pair = _poly_overlay_pair(value, name, question_style)
            if pair is not None:
                out[pair[0]] = pair[1]
    return out


def tip_league_row(snap: SotSnapshot, league: str) -> LeagueRow | None:
    """Return the enabled tip row for a league slug, if present."""
    for row in snap.leagues:
        if row.league == league and row.enabled and not row.tombstone:
            return row
    return None


def tip_entity_type(snap: SotSnapshot, league: str) -> str:
    """Entity type for alias inversion from the tip row settings."""
    row = tip_league_row(snap, league)
    if row is None:
        return invert_entity_type(league)
    return invert_entity_type(league, league_settings_from_row(row))


def tip_player_entity_type(snap: SotSnapshot, league: str) -> str:
    """Player entity type for alias inversion."""
    base = tip_entity_type(snap, league)
    return "fighter" if base == "fighter" else "player"


def tip_alias_enforcement(snap: SotSnapshot, league: str) -> str:
    """Alias completeness enforcement mode from the tip."""
    row = tip_league_row(snap, league)
    if row is not None:
        raw = league_settings_from_row(row).get("alias_enforcement")
        if raw in ("raise", "warn"):
            return str(raw)
    return "raise"


def overlay_league_config(
    cfg: Any,
    rules: list[MarketRuleRow],
    league_row: Any | None = None,
) -> Any:
    """Apply coalesced BQ taxonomy onto a LeagueConfig (BQ keys win)."""
    rows = league_rules(cfg, rules)
    runshop_enabled = (
        runshop_enabled_on_row(league_row) if league_row is not None else False
    )
    kalshi = cfg.KALSHI
    optic = overlay_optic(cfg.OPTIC, rows, cfg)
    px = overlay_px(cfg.PX, rows, cfg)
    crypto = overlay_crypto(cfg.CRYPTO, rows, cfg)
    poly = overlay_poly(cfg.POLYMARKET, rows, cfg)
    novig = overlay_novig(cfg.NOVIG, rows, cfg)
    underdog = overlay_underdog(cfg.UNDERDOG, rows, cfg)
    huddle = overlay_huddle(cfg.HUDDLE, rows, cfg)
    runshop = overlay_runshop(
        cfg.RUNSHOP,
        rows,
        cfg,
        runshop_enabled=runshop_enabled,
    )
    if all(
        x is cfg_y
        for x, cfg_y in (
            (kalshi, cfg.KALSHI),
            (optic, cfg.OPTIC),
            (px, cfg.PX),
            (crypto, cfg.CRYPTO),
            (poly, cfg.POLYMARKET),
            (novig, cfg.NOVIG),
            (underdog, cfg.UNDERDOG),
            (huddle, cfg.HUDDLE),
            (runshop, cfg.RUNSHOP),
        )
    ) and _output_order(cfg, optic, kalshi, px) == cfg.OUTPUT_ORDER:
        return cfg
    return replace(
        cfg,
        KALSHI=kalshi,
        OPTIC=optic,
        PX=px,
        CRYPTO=crypto,
        POLYMARKET=poly,
        NOVIG=novig,
        UNDERDOG=underdog,
        HUDDLE=huddle,
        RUNSHOP=runshop,
        OUTPUT_ORDER=_output_order(cfg, optic, kalshi, px),
    )


def _output_order(cfg: Any, optic: Any, kalshi: Any, px: Any) -> tuple:
    """Keep the profile's OUTPUT_ORDER, then append overlay-only types."""
    used: list[Any] = []
    if optic is not None:
        used.extend(optic.table_types.values())
    if kalshi is not None:
        used.extend(scope_types(kalshi.sport).values())
    if px is not None:
        used.extend(px.exact.values())
        used.extend(mt for _, mt in px.suffix)
    used_set = set(used)
    kept = [mt for mt in cfg.OUTPUT_ORDER if mt in used_set]
    extra = [mt for mt in dict.fromkeys(used) if mt not in set(kept)]
    return tuple(kept + extra)
