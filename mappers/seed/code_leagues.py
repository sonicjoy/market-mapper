"""Leagues owned by code: slug -> (sport, Optic league ids).

A league here joins the map run set (fetch + map) with no tip row. Its
Optic market table is the sport's; which venues map it is decided by each
venue's own code table (e.g. ``polymarket_usa_leagues``). A slug the tip
also lists keeps the tip's config.
"""

from __future__ import annotations

from mappers.exchanges.optic import OpticConfig
from mappers.market_types import MarketType
from mappers.pipeline import LeagueConfig
from mappers.seed.pdc_leagues import PDC_OPTIC_LEAGUES
from mappers.shared import FIXTURE_HORIZON_HOURS
from mappers.sport import Sport
from mappers.vocab.basketball_markets import BASKETBALL_OPTIC_TABLE_TYPES
from mappers.vocab.combat_markets import BOXING_OPTIC_TABLE_TYPES
from mappers.vocab.soccer_markets import SOCCER_OPTIC_TABLE_TYPES
from mappers.vocab.tennis_markets import TENNIS_OPTIC_TABLE_TYPES

# Darts: match winner only, two players, no draw (Optic 2-way moneyline).
DARTS_OPTIC_TABLE_TYPES: dict[str, MarketType] = {
    "moneyline": MarketType.MONEYLINE,
}

_TABLES: dict[Sport, dict[str, MarketType]] = {
    Sport.BASKETBALL: BASKETBALL_OPTIC_TABLE_TYPES,
    Sport.BOXING: BOXING_OPTIC_TABLE_TYPES,
    Sport.DARTS: DARTS_OPTIC_TABLE_TYPES,
    Sport.SOCCER: SOCCER_OPTIC_TABLE_TYPES,
    Sport.TENNIS: TENNIS_OPTIC_TABLE_TYPES,
}

# A person-sport slug must name the sport ("tennis", "boxing", "darts") so
# person_league holds. The first Optic id is the league's; the rest extra.
CODE_LEAGUES: dict[str, tuple[Sport, tuple[str, ...]]] = {
    "wta_doubles": (Sport.TENNIS, ("wta_doubles",)),
    "turkey_bsl": (Sport.BASKETBALL, ("turkey_-_bsl",)),
    # PolyUS basketball leagues, Optic fixtures + titles checked 2026-11-05.
    "australia_nbl": (Sport.BASKETBALL, ("australia_-_nbl",)),
    "spain_liga_acb": (Sport.BASKETBALL, ("spain_-_liga_acb",)),
    "france_lnb_pro_a": (Sport.BASKETBALL, ("france_-_lnb_pro_a",)),
    "france_lnb_pro_b": (Sport.BASKETBALL, ("france_-_lnb_pro_b",)),
    "greece_a1_league": (Sport.BASKETBALL, ("greece_-_a1_league",)),
    "japan_b1_league": (Sport.BASKETBALL, ("japan_-_b1_league",)),
    "international_vtb_united_league": (Sport.BASKETBALL, ("international_-_vtb_united_league",)),
    "boxing_matches": (Sport.BOXING, ("boxing_matches",)),
    "pdc_darts": (Sport.DARTS, PDC_OPTIC_LEAGUES),
    "modus_darts": (Sport.DARTS, ("modus_-_super_series",)),
    "greece_cup": (Sport.SOCCER, ("greece_-_cup",)),
}


def code_league_configs() -> dict[str, LeagueConfig]:
    """LeagueConfig per code league (Optic only; venues add themselves)."""
    out: dict[str, LeagueConfig] = {}
    for slug, (sport, (optic_id, *extra)) in CODE_LEAGUES.items():
        table = dict(_TABLES[sport])
        out[slug] = LeagueConfig(
            league=slug,
            sport=sport,
            PX=None,
            OPTIC=OpticConfig(
                league_id=optic_id,
                table_types=table,
                horizon_hours=FIXTURE_HORIZON_HOURS,
                extra_league_ids=tuple(extra),
            ),
            OUTPUT_ORDER=tuple(dict.fromkeys(table.values())),
            MarketType=MarketType,
        )
    return out
