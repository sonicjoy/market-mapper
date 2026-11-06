"""Which SX Bet leagues map, and onto which tip league slug.

SX's ``/markets/active`` rows carry a numeric ``leagueId`` (stable) and a
display ``leagueLabel`` (not unique across sports: "Premiership", "Serie
B").  The table is keyed on the id; the label is the comment.

Every entry was decided from evidence, never from the label alone
(2026-10-13, prod ``rs-marketmaking``, the live SX book against
``opticodds_us.opticodds_fixtures``):

* **Optic-linked** -- Optic's own ``source_ids["SX Bet"].event_id`` puts the
  league's live events on fixtures of that slug in
  ``markets_us.market_mapping``.
* **Kickoff + names** -- for leagues Optic never links, every live event's
  exact kickoff second plus a distinctive word of each team name landed on
  exactly one Optic fixture, and every such fixture sat in one Optic league
  whose slug the tip already runs (counts per row below).

Tennis tournaments get a new ``leagueId`` per event week, so tennis maps
by ``leagueLabel`` prefix instead (``TENNIS_PREFIXES``); the fixture match
(both players on one Optic fixture of that slug) still decides each match.

Not mapped, with the reason:

* 1516 "Women's World Cup" -- the women's World Cup qualifiers
  (``fifa_-_world_cup_qualifiers_women``, 15/16 events matched) are not on
  the tip: onboarding that league comes first.
* 1593 "Olympics Womens Soccer" -- 0 of 7 events land on any Optic fixture.
"""

from __future__ import annotations

from mappers.exchanges.sxbet import SxConfig
from mappers.vocab.sxbet_markets import BY_SPORT, IGNORED_TYPES

#: SX ``leagueId`` -> tip league slug.
SLUG_BY_LEAGUE_ID: dict[int, str] = {
    # US sports (Optic-linked).
    243: "nfl",                            # NFL
    246: "ncaaf",                          # NCAAF
    1: "nba",                              # NBA (kickoff + names: 24/24 on Optic nba)
    1117: "nba",                           # NBA Preseason (Optic nba carries preseason)
    3: "nhl",                              # NHL
    171: "mlb",                            # MLB
    34: "ufc",                             # UFC (kickoff + names: 6 on ufc)
    1063: "ufc",                           # DWCS (Optic ufc carries Contender Series cards)
    # Soccer, Optic-linked.
    1115: "mls",                           # Major League Soccer
    1313: "england_championship",          # The Championship
    30: "ucl",                             # Champions League_UEFA
    1309: "europa_conference_league",      # UEFA Conference League
    31: "europa_league",                   # Europa League_UEFA
    1114: "la_liga",                       # La Liga
    29: "epl",                             # English Premier League
    1113: "italy_serie_a",                 # Serie A
    1110: "brazil_serie_a",                # Campeonato Brasileiro
    1112: "france_ligue_1",                # Ligue 1
    1622: "korea_k1",                      # K1-League
    1623: "korea_k2",                      # K2-League
    1631: "conmebol_copa_libertadores",    # Copa Libertadores
    # Soccer, kickoff + names (events matched / live events).
    1788: "argentina_primera_nacional",    # Primera Nacional 11/18
    1777: "argentina_primera",             # Liga Profesional 15/15
    1780: "colombia_primera_a",            # Primera A 9/11
    1778: "brazil_serie_b",                # Brasileiro Serie B 7/10
    1439: "italy_serie_b",                 # Serie B 10/10
    1782: "czech_first_league",            # First League 8/9
    244: "germany_bundesliga",             # German Bundesliga 9/9
    1330: "netherlands_eredivisie",        # Eredivisie 9/9
    1331: "super_lig",                     # Super Lig 7/9
    1776: "liga_mx",                       # Liga MX 9/9
    1621: "sweden_superettan",             # Superettan 8/8
    239: "sweden_allsvenskan",             # Allsvenskan 7/8
    1181: "china_super_league",            # China Super League 7/8
    1785: "russia_premier_league",         # Russian Premier League 7/8
    1624: "norway_eliteserien",            # Eliteserien 6/8
    1784: "ecuador_serie_a",               # LigaPro 8/8
    1789: "bolivia_division_professional",  # Division Profesional 8/8
    1795: "austria_bundesliga",            # Austrian Bundesliga 6/6
    1783: "denmark_superliga",             # Superliga 3/6
    1786: "scotland_premiership",          # Premiership 6/6
    1626: "finland_veikkausliiga",         # Veikkausliiga 2/6
    1790: "canada_premier_league",         # Canadian Premier League 3/4
    1781: "conmebol_sudamericana",         # Copa Sudamericana 2/2
    1236: "portugal_primeira_liga",        # Portugal Primeira Liga 1/1
}

#: Tennis ``leagueLabel`` prefix -> tip slug, longest prefix first so
#: "ATP Challenger - Maia" is the Challenger tour, not the ATP.
TENNIS_PREFIXES: tuple[tuple[str, str], ...] = (
    ("ATP Challenger", "atp_challenger"),
    ("ATP", "atp"),
    ("WTA", "wta"),
)

TENNIS = "Tennis"


def slug_for(league_id: int | None, league_label: str, sport_label: str) -> str | None:
    """The tip slug an SX market belongs to, or None when SX's league is not mapped."""
    if sport_label == TENNIS:
        label = league_label.strip()
        for prefix, slug in TENNIS_PREFIXES:
            if label.startswith(prefix):
                return slug
        return None
    if league_id is None:
        return None
    return SLUG_BY_LEAGUE_ID.get(league_id)


def mapped_slugs() -> frozenset[str]:
    """Every slug the SX pass runs on (``with_code_sxbet``)."""
    return frozenset(SLUG_BY_LEAGUE_ID.values()) | {slug for _, slug in TENNIS_PREFIXES}


#: mmmapper ``Sport`` value -> SX ``sportLabel`` (SX's "Football" is American).
SX_SPORT_LABEL: dict[str, str] = {
    "soccer": "Soccer",
    "football": "Football",
    "basketball": "Basketball",
    "hockey": "Hockey",
    "baseball": "Baseball",
    "tennis": "Tennis",
    "mma": "Mixed Martial Arts",
}


def config_for(slug: str, sport: str) -> SxConfig | None:
    """The SX config of one tip slug, or None when SX does not map it.

    Which leagues map is this module's table; the market types are the
    sport's crosswalk (``mappers/vocab/sxbet_markets.py``).  Tennis and MMA
    sides resolve by person name, soccer by club name with SX's short forms.
    """
    key = slug.strip().casefold()
    label = SX_SPORT_LABEL.get(str(sport))
    if key not in mapped_slugs() or label is None or label not in BY_SPORT:
        return None
    return SxConfig(
        slug=key,
        market_types=dict(BY_SPORT[label]),
        ignored_types=IGNORED_TYPES,
        person_names=label in (TENNIS, "Mixed Martial Arts"),
        club_short_names=label == "Soccer",
    )
