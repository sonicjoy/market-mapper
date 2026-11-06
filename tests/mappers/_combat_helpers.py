"""Shared UFC/boxing tip-row fixtures for combat profile tests."""

from __future__ import annotations

from mappers.control_plane.rows import LeagueRow
from mappers.exchanges.kalshi import KalshiConfig
from mappers.exchanges.optic import OpticConfig
from mappers.seed.tip_factories import build_tip_league
from mappers.sport import Sport
from mappers.vocab.combat_markets import (
    BOXING_OPTIC_TABLE_TYPES,
    UFC_OPTIC_TABLE_TYPES,
)

UFC_KALSHI = KalshiConfig(sport=Sport.MMA)
BOXING_KALSHI = KalshiConfig(sport=Sport.BOXING)
UFC_OPTIC = OpticConfig(league_id="ufc", table_types=dict(UFC_OPTIC_TABLE_TYPES))
BOXING_OPTIC = OpticConfig(
    league_id="boxing_matches",
    table_types=dict(BOXING_OPTIC_TABLE_TYPES),
)


def ufc_tip_row() -> LeagueRow:
    """Tip row mirroring the legacy ufc.py LEAGUE wiring."""
    return LeagueRow(
        league="ufc",
        sport="mma",
        optic_league_id="ufc",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[
            "moneyline",
            "method_of_victory",
            "method_of_finish",
            "round_betting",
            "total_rounds",
            "fight_goes_distance",
            "game_win_by_kotko",
            "win_by_ko_sub_dq",
        ],
        exchanges=[
            {
                "sportsbook": "crypto.com",
                "enabled": True,
                "parser_profile": "crypto_mma_v1",
                "settings": {
                    "sport_grouping": "MMA",
                    "league": "UFC",
                    "period_type": "Full Fight",
                    "game_prop_accept_round_periods": True,
                },
            },
            {
                "sportsbook": "polymarket",
                "enabled": True,
                "parser_profile": "poly_ufc_v1",
                "settings": {
                    "slug_prefix": "ufc",
                    "optic_league_id": "ufc",
                    "question_style": "tennis_prefix",
                },
            },
            {
                "sportsbook": "novig",
                "enabled": True,
                "parser_profile": "novig_generic_v1",
                "settings": {"league": "UFC"},
            },
        ],
        notes=None,
        tombstone=False,
    )


def boxing_tip_row() -> LeagueRow:
    """Tip row for boxing_matches (Optic only; Kalshi comes from the sport)."""
    return LeagueRow(
        league="boxing_matches",
        sport="boxing",
        optic_league_id="boxing_matches",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=["moneyline"],
        exchanges=[],
        notes=None,
        tombstone=False,
    )


def ufc_league_config():
    return build_tip_league(ufc_tip_row())


def boxing_league_config():
    return build_tip_league(boxing_tip_row())
