"""Canonical sport taxonomy. League identity lives on the BigQuery tip."""

from __future__ import annotations

from enum import StrEnum


class Sport(StrEnum):
    """Bounded sport set used by parser profiles and fetch."""

    BASEBALL = "baseball"
    BASKETBALL = "basketball"
    BOXING = "boxing"
    CRICKET = "cricket"
    DARTS = "darts"
    ESPORTS = "esports"
    FOOTBALL = "football"
    HOCKEY = "hockey"
    MMA = "mma"
    SOCCER = "soccer"
    TENNIS = "tennis"


# Tip rows carry ``sport``. This map is the fallback when a caller has only a
# slug (legacy tests, provenance). Unknown slugs default to soccer.
_SPORT_FOR_SLUG: dict[str, Sport] = {
    "argentina_primera": Sport.SOCCER,
    "atp": Sport.TENNIS,
    "atp_challenger": Sport.TENNIS,
    "boxing_matches": Sport.BOXING,
    "brazil_serie_a": Sport.SOCCER,
    "brazil_serie_b": Sport.SOCCER,
    "canada_nsl_women": Sport.SOCCER,
    "canada_premier_league": Sport.SOCCER,
    "caribbean_premier_league": Sport.CRICKET,
    "cfl": Sport.FOOTBALL,
    "china_super_league": Sport.SOCCER,
    "conmebol_sudamericana": Sport.SOCCER,
    "cricket_odi": Sport.CRICKET,
    "cricket_test": Sport.CRICKET,
    "cs2": Sport.ESPORTS,
    "davis_cup": Sport.TENNIS,
    "dota_2": Sport.ESPORTS,
    "ecuador_serie_a": Sport.SOCCER,
    "efl_cup": Sport.SOCCER,
    "england_community_shield": Sport.SOCCER,
    "epl": Sport.SOCCER,
    "estonia_premium_liiga": Sport.SOCCER,
    "europa_conference_league": Sport.SOCCER,
    "europa_league": Sport.SOCCER,
    "finland_veikkausliiga": Sport.SOCCER,
    "france_ligue_1": Sport.SOCCER,
    "georgia_erovnuli_liga": Sport.SOCCER,
    "germany_bundesliga": Sport.SOCCER,
    "iceland_besta_deild": Sport.SOCCER,
    "iceland_besta_deild_women": Sport.SOCCER,
    "india_uttar_pradesh_t20": Sport.CRICKET,
    "international_club_friendlies": Sport.SOCCER,
    "ireland_premier": Sport.SOCCER,
    "ireland_premier_women": Sport.SOCCER,
    "italy_serie_a": Sport.SOCCER,
    "itf_men": Sport.TENNIS,
    "itf_women": Sport.TENNIS,
    "kazakhstan_premier_league": Sport.SOCCER,
    "kbo": Sport.BASEBALL,
    "korea_k1": Sport.SOCCER,
    "korea_k2": Sport.SOCCER,
    "korea_wk_league": Sport.SOCCER,
    "la_liga": Sport.SOCCER,
    "latvia_virsliga": Sport.SOCCER,
    "leagues_cup": Sport.SOCCER,
    "liga_mx": Sport.SOCCER,
    "lnbp": Sport.BASKETBALL,
    "lol": Sport.ESPORTS,
    "mlb": Sport.BASEBALL,
    "mls": Sport.SOCCER,
    "mozambique_mocambola": Sport.SOCCER,
    "nba": Sport.BASKETBALL,
    "ncaab": Sport.BASKETBALL,
    "ncaaw": Sport.BASKETBALL,
    "ncaaf": Sport.FOOTBALL,
    "nfl": Sport.FOOTBALL,
    "nhl": Sport.HOCKEY,
    "norway_1_divisjon": Sport.SOCCER,
    "norway_eliteserien": Sport.SOCCER,
    "npb": Sport.BASEBALL,
    "nwsl": Sport.SOCCER,
    "ofc_champions_league": Sport.SOCCER,
    "paraguay_primera_division": Sport.SOCCER,
    "peru_primera_division": Sport.SOCCER,
    "rainbow_six_siege": Sport.ESPORTS,
    "sweden_allsvenskan": Sport.SOCCER,
    "sweden_damallsvenskan": Sport.SOCCER,
    "sweden_superettan": Sport.SOCCER,
    "ucl": Sport.SOCCER,
    "uefa_super_cup": Sport.SOCCER,
    "ufc": Sport.MMA,
    "usl_championship": Sport.SOCCER,
    "usl_league_one": Sport.SOCCER,
    "uzbekistan_super_league": Sport.SOCCER,
    "wnba": Sport.BASKETBALL,
    "world_cup": Sport.SOCCER,
    "wta": Sport.TENNIS,
}


def sport_for_league(league: str) -> Sport:
    """Sport for a league slug when the tip row is not in hand."""
    try:
        return Sport(str(league).lower())
    except ValueError:
        pass
    return _SPORT_FOR_SLUG.get(str(league), Sport.SOCCER)
