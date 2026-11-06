"""Which DKEX leagues map, and under which venue token.

Split out of ``mappers/exchanges/dkex.py`` (which re-exports both
tables) so the league list can grow without touching the parser.
"""

from __future__ import annotations

#: DKEX ``subTopic`` -> the venue league token our tips carry
#: (``DkexConfig.league``, e.g. "NFL", "CFB").  Written out explicitly
#: because ``subTopic`` is a display string for many leagues ("Brazil -
#: Serie A"); a subTopic absent from this table is compared verbatim
#: (upper-cased), so leagues whose subTopic IS the token ("NFL", "MLB",
#: "WNBA", "NBA", "NHL", "UFC", "ATP", "WTA") need no entry.
#:
#: ``subTopic`` rather than ``metadata.leagueName``: the two agree for
#: every team sport, but for tennis ``leagueName`` is the tournament
#: ("ATP Chengdu") while ``subTopic`` is the tour.  Both FBS ("NCAAF")
#: and FCS ("NCAA FCS") are college football on one Optic league, so
#: both map to CFB.  Taken from the staging catalogue, 2026-09-28.
LEAGUE_TOKENS: dict[str, str] = {
    "NCAAF": "CFB",
    "NCAA FCS": "CFB",
    # Optic's nba league carries preseason games as ordinary fixtures, so
    # DKEX's preseason book is part of the same pass.
    "NBA Preseason": "NBA",
    "NFL Preseason": "NFLPRE",
    "NHL Preseason": "NHLPRE",
    # Optic's ufc league carries the Contender Series cards as ordinary
    # fixtures (season_type "Dana White's Contender Series: ...").  DKEX
    # spells the subTopic with a typographic apostrophe.
    "Dana White\u2019s Contender Series": "UFC",
    "Argentina - Liga Profesional": "LPA",
    "Brazil - Serie A": "BSA",
    "Champions League": "UCL",
    "Colombia - Primera": "CPL",
    "England - Championship": "EFLC",
    "England - Premier League": "EPL",
    "English Football League Cup": "ELC",
    "Europa Conference League": "UECL",
    "Europa League": "UEL",
    "France - Ligue 1": "LIGUE1",
    "Friendly": "FRIENDLYCLUB",
    "Germany - 1.Bundesliga": "BUNDESLIGA",
    "Italy - Serie A": "ISA",
    "Italy Cup": "COPPAIT",
    "Japan NPB": "NPB",
    "Mexico - Liga MX": "LIGAMX",
    "Netherlands - Eredivisie": "NER",
    "NASCAR Cup Series": "NASCAR",
    "Saudi Arabia - Premier": "SAPL",
    "South Korean KBO": "KBO",
    "Spain - La Liga": "LALIGA",
    "USA - MLS": "MLS",
    "USA - NWSL": "NWSL",
}

#: Tip league slug -> DKEX venue league token.  The mapper runs DKEX on
#: every slug here and on no other; a tip ``dkex`` exchange row is
#: ignored (``with_code_dkex``).  Which leagues map DKEX is a
#: code decision, made from DKEX's typed catalogue (``subTopic``), not a
#: console card.
VENUE_TOKEN_BY_SLUG: dict[str, str] = {
    "nfl": "NFL",
    "ncaaf": "CFB",
    "cfb": "CFB",
    "mlb": "MLB",
    # Japan NPB (subTopic "Japan NPB") and South Korean KBO (subTopic
    # "South Korean KBO"): the MLB market vocabulary.
    "npb": "NPB",
    "kbo": "KBO",
    "wnba": "WNBA",
    "nba": "NBA",
    # College basketball: subTopic and ticker prefix are both "NCAAB".
    "ncaab": "NCAAB",
    "nhl": "NHL",
    "ufc": "UFC",
    # Tennis: the token is a label only -- the tennis pass reads every
    # WIN/MTH event (DkexConfig.any_league) and matches on the players.
    "atp": "ATP",
    "wta": "WTA",
    "atp_challenger": "ATPCH",
    "itf_men": "ITFM",
    "itf_women": "ITFW",
    # Soccer: DKEX league token per tip slug (LEAGUE_TOKENS above
    # maps subTopic onto the same tokens).
    "epl": "EPL",
    "england_championship": "EFLC",
    "efl_cup": "ELC",
    "la_liga": "LALIGA",
    "ucl": "UCL",
    "europa_league": "UEL",
    "europa_conference_league": "UECL",
    "italy_serie_a": "ISA",
    "italy_coppa_italia": "COPPAIT",
    "germany_bundesliga": "BUNDESLIGA",
    "france_ligue_1": "LIGUE1",
    "brazil_serie_a": "BSA",
    "argentina_primera": "LPA",
    "mls": "MLS",
    "nwsl": "NWSL",
    "liga_mx": "LIGAMX",
    "international_club_friendlies": "FRIENDLYCLUB",
    # Tokens are DKEX's ticker prefixes for these subTopics (2026-11-03).
    "colombia_primera_a": "CPL",
    "saudi_pro_league": "SAPL",
    "netherlands_eredivisie": "NER",
}
