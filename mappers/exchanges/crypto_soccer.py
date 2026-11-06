"""Shared crypto.com soccer vocabulary (game lines, props, game props).

Used by World Cup, EPL, UCL and any other soccer league module that
shares the same FIX contract_type strings validated on FIFA fixtures.
"""

from mappers.exchanges.crypto_com import CryptoConfig
from mappers.market_types import MarketType


def _n_plus_props(
    label: str, mt: MarketType, ns: tuple[int, ...],
) -> dict[str, MarketType]:
    return {f"{n}+ {label}": mt for n in ns}


SOCCER_PROP_CONTRACT_TYPES: dict[str, MarketType] = {
    "Anytime Goal Scorer": MarketType.PLAYER_GOALS,
    "First Goalscorer": MarketType.FIRST_GOAL_SCORER,
    "To Give Assist": MarketType.PLAYER_ASSISTS,
    "To Score Or Give Assist": MarketType.PLAYER_GOALS_OR_ASSIST,
    "To Receive A Card": MarketType.PLAYER_CARDS,
    "To Receive A Red Card": MarketType.PLAYER_RED_CARDS,
    **{f"To Score {n}+ Goals": MarketType.PLAYER_GOALS for n in (2, 3, 4, 5)},
    **_n_plus_props("Shots", MarketType.PLAYER_SHOTS, (1, 2, 3, 4, 5, 6)),
    **_n_plus_props(
        "Shots on Target", MarketType.PLAYER_SHOTS_ON_TARGET, (1, 2, 3, 4)),
    **_n_plus_props("Saves", MarketType.PLAYER_SAVES, (1, 2, 3, 4, 5, 6, 7, 8)),
    **_n_plus_props("Fouls Committed", MarketType.PLAYER_FOULS, (1, 2)),
    **_n_plus_props("Fouls Won", MarketType.PLAYER_FOULS_WON, (1, 2)),
}

SOCCER_GAME_LINE_CONTRACT_TYPES: dict[str, MarketType] = {
    "Moneyline (3-Way)": MarketType.MONEYLINE_3WAY,
    "Moneyline (2-Way)": MarketType.MONEYLINE_DNB,
    "Total Goals": MarketType.GAME_TOTAL,
    "Spread": MarketType.POINT_SPREAD,
    "To Advance": MarketType.TO_ADVANCE,
}

SOCCER_GAME_PROP_CONTRACT_TYPES: dict[str, MarketType] = {
    "Both Teams To Score": MarketType.BTTS,
    # Home / Away / No Goal; No Goal is Optic's Draw selection.
    "First Team To Score": MarketType.FIRST_TEAM_TO_SCORE,
}

# Half lines share the full-game contract strings under their own feed
# period (checked against crypto_underlying_securities 2026-11-05); Optic
# carries 1st/2nd-half winner, total goals, asian handicap and BTTS.
SOCCER_PERIOD_LINES: dict[str, dict[str, MarketType]] = {
    "1st Half": {
        "Moneyline (3-Way)": MarketType.FIRST_HALF_WINNER_3WAY,
        "Total Goals": MarketType.FIRST_HALF_TOTAL,
        "Spread": MarketType.FIRST_HALF_POINT_SPREAD,
        "Both Teams To Score": MarketType.FIRST_HALF_BTTS,
    },
    "2nd Half": {
        "Moneyline (3-Way)": MarketType.SECOND_HALF_WINNER_3WAY,
        "Total Goals": MarketType.SECOND_HALF_TOTAL,
        "Spread": MarketType.SECOND_HALF_POINT_SPREAD,
        "Both Teams To Score": MarketType.SECOND_HALF_BTTS,
    },
}

SOCCER_PERIOD = "90 Minutes and Stoppage Time"
TO_ADVANCE_PERIOD = "Full Game"


def soccer_crypto_config(league: str) -> CryptoConfig:
    """Build a soccer CryptoConfig for a crypto meta_league code (FIFA, UCL, EPL)."""
    return CryptoConfig(
        sport_grouping="SOCCER",
        league=league,
        period_type=SOCCER_PERIOD,
        contract_types=dict(SOCCER_GAME_LINE_CONTRACT_TYPES),
        contract_period_types={"To Advance": TO_ADVANCE_PERIOD},
        period_contract_types={k: dict(v) for k, v in SOCCER_PERIOD_LINES.items()},
        prop_contract_types=dict(SOCCER_PROP_CONTRACT_TYPES),
        prop_period_type=SOCCER_PERIOD,
        game_prop_contract_types=dict(SOCCER_GAME_PROP_CONTRACT_TYPES),
        game_prop_period_type=SOCCER_PERIOD,
    )
