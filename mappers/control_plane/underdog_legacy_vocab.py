"""Underdog UDX market crosswalks, keyed on (product, period).

The period is the ticker suffix (``1H``, ``1Q``, ``2H``), never the
sentence. An empty period is the full game. Families with no canonical
type are absent, so they classify to None.
"""

from __future__ import annotations

from mappers.market_types import MarketType

_GAME_LINES: dict[tuple[str, str], MarketType] = {
    ("GAMEWIN", ""): MarketType.MONEYLINE,
    ("SPREAD", ""): MarketType.POINT_SPREAD,
    ("TOTAL", ""): MarketType.GAME_TOTAL,
}

# MLB adds the player and team props Optic already prices.
BASEBALL: dict[tuple[str, str], MarketType] = {
    **_GAME_LINES,
    ("TEAMTOTAL", ""): MarketType.TEAM_TOTAL,
    ("RFI", ""): MarketType.FIRST_INNING_TOTAL,
    ("HITS", ""): MarketType.PLAYER_HITS,
    ("KS", ""): MarketType.PLAYER_STRIKEOUTS,
    ("HRR", ""): MarketType.PLAYER_HITS_RUNS_RBIS,
    ("HR", ""): MarketType.PLAYER_HOME_RUNS,
    ("TB", ""): MarketType.PLAYER_BASES,
    ("RBI", ""): MarketType.PLAYER_RBIS,
}
# Basketball period markets are priced by Optic only for the first half.
BASKETBALL: dict[tuple[str, str], MarketType] = {
    **_GAME_LINES,
    ("SPREAD", "1H"): MarketType.FIRST_HALF_POINT_SPREAD,
    ("TOTAL", "1H"): MarketType.FIRST_HALF_TOTAL,
    ("PTS", ""): MarketType.PLAYER_POINTS,
    ("AST", ""): MarketType.PLAYER_ASSISTS,
    ("REB", ""): MarketType.PLAYER_REBOUNDS,
    ("3PT", ""): MarketType.PLAYER_THREES,
}
# NBA spells the prop products differently from WNBA (``NBAREBS``, ``NBATHREES``).
NBA: dict[tuple[str, str], MarketType] = {
    **_GAME_LINES,
    ("PTS", ""): MarketType.PLAYER_POINTS,
    ("ASSTS", ""): MarketType.PLAYER_ASSISTS,
    ("REBS", ""): MarketType.PLAYER_REBOUNDS,
    ("THREES", ""): MarketType.PLAYER_THREES,
}
# NHL game lines settle on the full game incl. overtime and the shootout, as Optic's hockey
# moneyline / puck_line / total_goals do. TEAMGOALS has no Optic hockey row, so it stays unmapped.
HOCKEY: dict[tuple[str, str], MarketType] = dict(_GAME_LINES)

# Football periods. The ticker suffix keys the period; the venue sentence agrees
# ("during the second quarter", "during the second half and overtime"), and the
# witness rejects a stamp whose own Optic market id names another period.
_FOOTBALL_PERIODS: dict[tuple[str, str], MarketType] = {
    ("GAMEWIN", "1H"): MarketType.FIRST_HALF_WINNER_3WAY,
    ("GAMEWIN", "2H"): MarketType.SECOND_HALF_WINNER_3WAY,
    ("GAMEWIN", "1Q"): MarketType.FIRST_QUARTER_WINNER_3WAY,
    ("GAMEWIN", "2Q"): MarketType.SECOND_QUARTER_WINNER_3WAY,
    ("GAMEWIN", "3Q"): MarketType.THIRD_QUARTER_WINNER_3WAY,
    ("GAMEWIN", "4Q"): MarketType.FOURTH_QUARTER_WINNER_3WAY,
    ("SPREAD", "1H"): MarketType.FIRST_HALF_POINT_SPREAD,
    ("SPREAD", "2H"): MarketType.SECOND_HALF_POINT_SPREAD,
    ("SPREAD", "1Q"): MarketType.FIRST_QUARTER_POINT_SPREAD,
    ("SPREAD", "2Q"): MarketType.SECOND_QUARTER_POINT_SPREAD,
    ("SPREAD", "3Q"): MarketType.THIRD_QUARTER_POINT_SPREAD,
    ("SPREAD", "4Q"): MarketType.FOURTH_QUARTER_POINT_SPREAD,
    ("TOTAL", "1H"): MarketType.FIRST_HALF_TOTAL,
    ("TOTAL", "2H"): MarketType.SECOND_HALF_TOTAL,
    ("TOTAL", "1Q"): MarketType.FIRST_QUARTER_TOTAL,
    ("TOTAL", "2Q"): MarketType.SECOND_QUARTER_TOTAL,
    ("TOTAL", "3Q"): MarketType.THIRD_QUARTER_TOTAL,
    ("TOTAL", "4Q"): MarketType.FOURTH_QUARTER_TOTAL,
}
FOOTBALL_NCAAF: dict[tuple[str, str], MarketType] = {
    **_GAME_LINES,
    ("TEAMTOTAL", ""): MarketType.TEAM_TOTAL,
    **_FOOTBALL_PERIODS,
}
FOOTBALL_NFL: dict[tuple[str, str], MarketType] = {
    **_GAME_LINES,
    ("TEAMTOTAL", ""): MarketType.TEAM_TOTAL,
    **_FOOTBALL_PERIODS,
    ("PASSYDS", ""): MarketType.PLAYER_PASSING_YARDS,
    ("PASSTD", ""): MarketType.PLAYER_PASSING_TOUCHDOWNS,
    ("RECYDS", ""): MarketType.PLAYER_RECEIVING_YARDS,
    ("REC", ""): MarketType.PLAYER_RECEPTIONS,
    ("RUSHYDS", ""): MarketType.PLAYER_RUSHING_YARDS,
    ("PASSATT", ""): MarketType.PLAYER_PASSING_ATTEMPTS,
    ("PASSCOM", ""): MarketType.PLAYER_PASSING_COMPLETIONS,
    ("PASSINT", ""): MarketType.PLAYER_INTERCEPTIONS,
    ("PASSLNG", ""): MarketType.PLAYER_LONGEST_PASSING_COMPLETION,
    ("RECLNG", ""): MarketType.PLAYER_LONGEST_RECEPTION,
    ("RUSHATT", ""): MarketType.PLAYER_RUSHING_ATTEMPTS,
    ("RUSHLNG", ""): MarketType.PLAYER_LONGEST_RUSH,
    ("FGM", ""): MarketType.PLAYER_FIELD_GOALS_MADE,
    ("TD", ""): MarketType.PLAYER_TOUCHDOWNS,
    ("FIRSTTD", ""): MarketType.FIRST_TOUCHDOWN_SCORER,
}

# SPREAD is the games handicap ("wins at least 2.5 more games"), Optic's ``game_spread``.
_TENNIS: dict[tuple[str, str], MarketType] = {
    ("MATCHWIN", ""): MarketType.MONEYLINE,
    ("TOTAL", ""): MarketType.MATCH_TOTAL_GAMES,
    ("SPREAD", ""): MarketType.POINT_SPREAD,
}

_SOCCER: dict[tuple[str, str], MarketType] = {
    ("GAMEWIN", ""): MarketType.MONEYLINE_3WAY,
    ("SPREAD", ""): MarketType.POINT_SPREAD,
    ("TOTAL", ""): MarketType.GAME_TOTAL,
    ("BTTS", ""): MarketType.BTTS,
    ("GAMEWIN", "1H"): MarketType.FIRST_HALF_WINNER_3WAY,
    ("SPREAD", "1H"): MarketType.FIRST_HALF_POINT_SPREAD,
    ("TOTAL", "1H"): MarketType.FIRST_HALF_TOTAL,
}


_UFC: dict[tuple[str, str], MarketType] = {
    ("FIGHTWIN", ""): MarketType.MONEYLINE,
}

BY_VENUE_LEAGUE: dict[str, dict[tuple[str, str], MarketType]] = {
    "NFL": FOOTBALL_NFL,
    "NCAAMFB": FOOTBALL_NCAAF,
    "NBA": NBA,
    "MLB": BASEBALL,
    "WNBA": BASKETBALL,
    "ATP": _TENNIS,
    "ATPCHL": _TENNIS,
    "WTA": _TENNIS,
    "ITFMEN": _TENNIS,
    "ITFWOMEN": _TENNIS,
    "MLS": _SOCCER,
    "LIGAMX": _SOCCER,
    "UNL": _SOCCER,
    "FIFA": _SOCCER,
    "BRASILA": _SOCCER,
    "SAUDIPRO": _SOCCER,
    "ARGNAC": _SOCCER,
    "UCL": _SOCCER,
    "UEL": _SOCCER,
    "EPL": _SOCCER,
    "LALIGA": _SOCCER,
    "SERIEA": _SOCCER,
    "BUNDESLIGA": _SOCCER,
    "LIGUE1": _SOCCER,
    "ARGPREM": _SOCCER,
    "BRASILB": _SOCCER,
    "NHL": HOCKEY,
    "UFC": _UFC,
}

VENUE_TOKEN_TO_LEAGUE_SLUG: dict[str, str] = {
    "NFL": "nfl",
    "MLB": "mlb",
    "WNBA": "wnba",
    "NBA": "nba",
    "NCAAMFB": "ncaaf",
    "ATP": "atp",
    "ATPCHL": "atp_challenger",
    "WTA": "wta",
    "ITFMEN": "itf_men",
    "ITFWOMEN": "itf_women",
    "MLS": "mls",
    "LIGAMX": "liga_mx",
    "UNL": "uefa_nations_league",
    "FIFA": "international_friendlies",
    "BRASILA": "brazil_serie_a",
    "SAUDIPRO": "saudi_pro_league",
    "ARGNAC": "argentina_primera_nacional",
    "UCL": "ucl",
    "UEL": "europa_league",
    "EPL": "epl",
    "LALIGA": "la_liga",
    "SERIEA": "italy_serie_a",
    "BUNDESLIGA": "germany_bundesliga",
    "LIGUE1": "france_ligue_1",
    "ARGPREM": "argentina_primera",
    "BRASILB": "brazil_serie_b",
    "NHL": "nhl",
    "UFC": "ufc",
}

UNDERDOG_SLUG_TO_VENUE_TOKEN: dict[str, str] = {
    slug: token for token, slug in VENUE_TOKEN_TO_LEAGUE_SLUG.items()
}
#: Venue tokens whose league set and market types are code decisions; tip
#: ``underdog`` rules cannot add to or override them (``overlay_underdog``).
CODE_OWNED_VENUE_TOKENS: frozenset[str] = frozenset(VENUE_TOKEN_TO_LEAGUE_SLUG)


def market_type_for_venue(
    venue_league: str,
    product: str,
    period: str,
) -> MarketType | None:
    """Canonical market type for a UDX (product, period) slice, or None."""
    table = BY_VENUE_LEAGUE.get(venue_league.strip().upper())
    if table is None:
        return None
    key = (product.strip().upper(), period.strip().upper())
    return table.get(key)
