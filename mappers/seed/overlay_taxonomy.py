"""Apply coalesced BQ taxonomy rules onto exchange configs."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from mappers.exchanges.runshop import RunshopConfig
from mappers.exchanges.runshop_crosswalk import crosswalk_rules_from_market_rules
from mappers.exchanges.runshop_vendor import DEFAULT_MARKETS_PATH
from mappers.market_types import Scope, Shape
from mappers.seed.poly_usa_exchange import POLY_BOOK

if TYPE_CHECKING:
    # Runtime import would close a cycle: mappers.control_plane.__init__ eagerly
    # pulls the console/gap-fix chain, which overlays taxonomy from here.
    from mappers.control_plane.rows import MarketRuleRow


def league_rules(cfg: Any, rules: list[MarketRuleRow]) -> list[MarketRuleRow]:
    """Rules for one league slug."""
    slug = str(cfg.league) if cfg.league is not None else ""
    return [
        row for row in rules
        if row.league == slug and row.enabled and not row.tombstone
    ]


_CRYPTO_LINE_GROUPS = frozenset({"Game Line", "Fight Line"})


def crypto_overlay_applies(
    crypto: Any,
    *,
    source_key_type: str,
    source_key: str,
    market_group: str = "",
) -> bool:
    """True when the crypto overlay table would map this source key."""
    if crypto is None:
        return False
    if source_key_type == "team_prop_contract_type" or market_group == "Team Prop":
        return source_key in (crypto.team_prop_contract_types or {})
    if (
        source_key_type == "game_prop_contract_type"
        or market_group in {"Game Prop", "Fight Prop"}
    ):
        return source_key in (crypto.game_prop_contract_types or {})
    if source_key_type == "player_prop_contract_type" or market_group == "Player Prop":
        return source_key in (crypto.prop_contract_types or {})
    if market_group in _CRYPTO_LINE_GROUPS:
        return source_key in (crypto.contract_types or {})
    if source_key in (crypto.contract_types or {}):
        return True
    return source_key in (crypto.prop_contract_types or {})


def overlay_optic(optic: Any, rows: list[MarketRuleRow], cfg: Any) -> Any:
    """Merge tip Optic maps onto the Python table (do not replace)."""
    if optic is None:
        return None
    maps = {
        row.source_key: _market_type(cfg, row.canonical_market_type)
        for row in rows
        if row.sportsbook == "optic"
        and row.action == "map"
        and row.source_key_type == "market_id"
    }
    maps = {key: mt for key, mt in maps.items() if mt is not None}
    if not maps:
        return optic
    table = {**maps, **optic.table_types}  # code wins on overlap
    return replace(optic, table_types=table)


def overlay_px(px: Any, rows: list[MarketRuleRow], cfg: Any) -> Any:
    """Overlay PX exact and suffix maps. Prefix is not a PX operator."""
    if px is None:
        return None
    exact: dict[str, Any] = {}
    suffix: list[tuple[str, Any]] = []
    for row in rows:
        if row.sportsbook != "px" or row.action != "map":
            continue
        mt = _market_type(cfg, row.canonical_market_type)
        if mt is None:
            continue
        if row.match_operator == "suffix":
            suffix.append((row.source_key, mt))
        else:
            exact[row.source_key] = mt
    if not exact and not suffix:
        return px
    final_suffix = suffix or list(px.suffix)
    final_suffix.sort(key=lambda item: len(item[0]), reverse=True)
    return replace(
        px,
        exact=exact or dict(px.exact),
        suffix=final_suffix,
    )


def overlay_crypto(crypto: Any, rows: list[MarketRuleRow], cfg: Any) -> Any:
    """Merge tip crypto.com contract maps onto the Python tables."""
    if crypto is None:
        return None
    game = dict(crypto.contract_types)
    player = dict(crypto.prop_contract_types)
    team = dict(getattr(crypto, "team_prop_contract_types", None) or {})
    game_prop = dict(crypto.game_prop_contract_types)
    for row in rows:
        _apply_crypto_map_row(row, cfg, game, player, team, game_prop)
    return replace(
        crypto,
        contract_types=game,
        prop_contract_types=player,
        team_prop_contract_types=team,
        game_prop_contract_types=game_prop,
    )


def _apply_crypto_map_row(
    row: Any,
    cfg: Any,
    game: dict[str, Any],
    player: dict[str, Any],
    team: dict[str, Any],
    game_prop: dict[str, Any],
) -> None:
    """Route one tip map by source_key_type. Notes do not choose a table."""
    if row.sportsbook != "crypto.com" or row.action != "map":
        return
    mt = _market_type(cfg, row.canonical_market_type)
    if mt is None:
        return
    key = row.source_key
    if key.startswith("team_prop:"):
        team[key.split(":", 1)[1].strip() or key] = mt
        return
    if key.startswith("game_prop:"):
        game_prop[key.split(":", 1)[1].strip() or key] = mt
        return
    table = _crypto_type_table(row.source_key_type, player, team, game_prop)
    if table is not None:
        table[key] = mt
        return
    if row.source_key_type != "contract_type":
        return
    if mt.scope == Scope.TEAM and mt.shape == Shape.TOTAL:
        return
    game[key] = mt


def _crypto_type_table(
    source_key_type: str,
    player: dict[str, Any],
    team: dict[str, Any],
    game_prop: dict[str, Any],
) -> dict[str, Any] | None:
    """Prop tables keyed by source_key_type. Notes never choose a table."""
    if source_key_type == "team_prop_contract_type":
        return team
    if source_key_type == "game_prop_contract_type":
        return game_prop
    if source_key_type == "player_prop_contract_type":
        return player
    return None


def overlay_poly(poly: Any, rows: list[MarketRuleRow], cfg: Any) -> Any:
    """Overlay Polymarket market_types from the tip."""
    if poly is None:
        return None
    maps = _poly_market_types(rows, cfg, POLY_BOOK)
    if maps:
        return replace(poly, market_types=maps)
    return poly


def _poly_market_types(
    rows: list[MarketRuleRow],
    cfg: Any,
    sportsbook: str,
) -> dict[str, Any]:
    maps = {
        row.source_key: _market_type(cfg, row.canonical_market_type)
        for row in rows
        if row.sportsbook == sportsbook
        and row.action == "map"
        and row.source_key_type == "kind"
    }
    return {key: mt for key, mt in maps.items() if mt is not None}


def overlay_underdog(underdog: Any, rows: list[MarketRuleRow], cfg: Any) -> Any:
    """Underdog's crosswalk is code (keyed on Optic market ids); tip rules never touch it."""
    _ = (rows, cfg)
    return underdog


def overlay_novig(novig: Any, rows: list[MarketRuleRow], cfg: Any) -> Any:
    """Novig's market vocab is code (``novig_markets``); tip rules never touch it."""
    _ = (rows, cfg)
    return novig


def overlay_huddle(huddle: Any, rows: list[MarketRuleRow], cfg: Any) -> Any:
    """Huddle's market vocab is code (``football_huddle``); tip rules never touch it."""
    _ = (rows, cfg)
    return huddle


def overlay_runshop(
    runshop: RunshopConfig | None,
    rows: list[MarketRuleRow],
    cfg: Any,
    *,
    runshop_enabled: bool = False,
) -> RunshopConfig | None:
    """Overlay Runshop crosswalk from mapping_market_rules."""
    if not runshop_enabled and runshop is None:
        return None
    crosswalk = crosswalk_rules_from_market_rules(rows, league=str(cfg.league))
    if runshop is None and not crosswalk:
        return None
    base = runshop or RunshopConfig(
        markets_path=DEFAULT_MARKETS_PATH,
        crosswalk_path=None,
    )
    if not crosswalk:
        return base
    return replace(
        base,
        crosswalk_rules=tuple(crosswalk),
        crosswalk_path=None,
    )


def _market_type(cfg: Any, value: str | None) -> Any:
    if not value:
        return None
    enum_cls = cfg.MarketType
    try:
        return enum_cls(value)
    except ValueError:
        return next((mt for mt in enum_cls if mt.value == value), None)
