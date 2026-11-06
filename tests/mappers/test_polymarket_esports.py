"""Tests for the shared esports matcher (LoL + CS2 + Dota 2).

Covers the two market forms added on 2026-08-11 alongside the pre-existing
series moneyline -- map/game handicap and map/game totals -- plus the CS2 and
Dota 2 league wiring. LoL's own wiring and its live moneyline corpus stay in
tests/mappers/test_polymarket_lol.py.

Every question below is BYTE-EXACT from the live
raw_ingestion_us.polymarket_position_token_bridge (2026-08-11), paired with the
outcome labels that row actually carried -- not synthesized. That pairing is
the point of this module: the handicap questions ABBREVIATE one team while the
outcome labels spell both out, and which of the two the rule captures is the
difference between a mapped market and a silently dropped one.
"""

import os

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from fetch.optic import SUPPORTED_LEAGUES  # noqa: E402
from fetch.tip import optic_api_key_secret  # noqa: E402
from mappers.exchanges import polymarket as pm  # noqa: E402
from mappers.market_types import MarketType, Scope, Shape  # noqa: E402
from mappers.run import LEAGUES  # noqa: E402
from mappers.sport import Sport
from mappers.vocab.esports_markets import ESPORTS_OPTIC_TABLE_TYPES  # noqa: E402
from tests.mappers._require import require  # noqa: E402

LOL_POLY = require(LEAGUES["lol"].POLYMARKET)
CS2_POLY = require(LEAGUES["cs2"].POLYMARKET)
DOTA_POLY = require(LEAGUES["dota_2"].POLYMARKET)

ESPORTS_SLUGS = ("lol", "cs2", "dota_2")
ESPORTS_LEAGUES = tuple(LEAGUES[slug] for slug in ESPORTS_SLUGS)

# (question, expected entity, expected line) — the entity is the team the
# signed line binds to. Note it is the SECOND name in every question: the
# first is an abbreviation ("GZ", "FEC", "TS.A") that matches no fixture name.
LIVE_HANDICAPS: list[tuple[str, str, float]] = [
    ("Game Handicap: FEC (-1.5) vs mCon esports (+1.5)", "mcon esports", 1.5),
    ("Game Handicap: RE (-1.5) vs MOUZ (+1.5)", "mouz", 1.5),
    ("Game Handicap: TS.A (-1.5) vs No Hoodwink (+1.5)", "no hoodwink", 1.5),
    ("Game Handicap: Na`Vi (-1.5) vs Level UP (+1.5)", "level up", 1.5),
    ("Game Handicap: AL (-1.5) vs Top Esports (+1.5)", "top esports", 1.5),
    ("Game Handicap: BAR (-1.5) vs UB Alma Mater (+1.5)", "ub alma mater", 1.5),
    ("Map Handicap: GZ (-1.5) vs Abyssal (+1.5)", "abyssal", 1.5),
    ("Map Handicap: VIT.A (-1.5) vs Eternal Fire Academy (+1.5)",
     "eternal fire academy", 1.5),
    ("Map Handicap: paiN.A (-1.5) vs Keyd (+1.5)", "keyd", 1.5),
    ("Map Handicap: GLS (-1.5) vs BORRACHEIROS (+1.5)", "borracheiros", 1.5),
]

LIVE_TOTALS: list[tuple[str, float]] = [
    ("Games Total: O/U 2.5", 2.5),   # LoL / Dota 2 wording
    ("Maps Total: O/U 2.5", 2.5),    # CS2 wording
]

LIVE_MONEYLINES: list[tuple[str, str, str]] = [
    ("Counter-Strike: Vitality vs 100 Thieves (BO1) - Esports World Cup Group C",
     "vitality", "100 thieves"),
    ("Dota 2: Aurora vs GamerLegion (BO3) - The International Group Stage",
     "aurora", "gamerlegion"),
    ("LoL: BNK FearX Youth vs HANJIN BRION Challengers (BO3) - LCK Challengers "
     "League Rounds 3-4 Trial Group",
     "bnk fearx youth", "hanjin brion challengers"),
    ("Honor of Kings: JLY vs Koala Game (BO5) - Honor of Kings World Championship",
     "jly", "koala game"),
    ("Mobile Legends Bang Bang: Team Spirit vs Cyber Hero (BO5) - MSC",
     "team spirit", "cyber hero"),
    ("Rainbow Six Siege: Elevate Academy APAC vs Weibo Gaming (BO1) - "
     "Asia Pacific League Asia - Stage 2 Group Stage",
     "elevate academy apac", "weibo gaming"),
]

# Forms Optic prices NO market for. Each MUST stay unrecognized: a rule that
# accepted one would manufacture rows that attach_polymarket_row then drops at
# guard #3 (harmless but noisy) -- or, for the map-winner forms, would stamp a
# per-map market onto the SERIES moneyline's odds, which is a mis-price.
UNMAPPABLE: list[str] = [
    "LoL: Kits Esports vs SDM Tigres - Game 2 Winner",
    "Counter-Strike: Bushido Wildcats vs Eternal Fire Academy - Map 2 Winner",
    "Dota 2: Team Falcons vs LGD Gaming - Game 2 Winner",
    # Same, but with the "(BO<n>)" parenthetical the live samples happen to
    # lack -- this is the case _Q_ESPORTS_MAP_WINNER exists to catch, since the
    # moneyline regex would otherwise match it.
    "LoL: Kits Esports vs SDM Tigres (BO3) - Game 2 Winner",
    "Counter-Strike: Vitality vs 100 Thieves (BO1) - Map 3 Winner",
    "Map 1 Total Rounds: Over/Under 21.5",
    "Map 1 Rounds Handicap: Team Falcons (-6.5) vs K27 (+6.5)",
    "Game 1: Any Player Rampage?",
    "Game 2: Odd/Even Total Kills?",
    "Game 2: Any Player Penta Kill?",
    "Game 2: Both Teams Slay Baron Nashor?",
]


# === Shared taxonomy ===

def test_all_three_leagues_share_one_taxonomy():
    for mod in ESPORTS_LEAGUES:
        assert mod.OPTIC.table_types == ESPORTS_OPTIC_TABLE_TYPES, mod.league
        assert mod.POLYMARKET is not None
        assert mod.POLYMARKET.market_types == pm.ESPORTS_MARKET_TYPES, mod.league


def test_market_type_shapes():
    # map_handicap is byte-identical in row shape to soccer's asian_handicap
    # (selection=team, points=+-1.5), total_maps to tennis TOTAL_SETS.
    assert MarketType.MAP_HANDICAP.scope is Scope.GAME
    assert MarketType.MAP_HANDICAP.shape is Shape.SPREAD
    assert MarketType.TOTAL_MAPS.scope is Scope.GAME
    assert MarketType.TOTAL_MAPS.shape is Shape.TOTAL


def test_series_moneyline_is_two_way():
    # An esports series always has a winner -> plain MONEYLINE, never 3-way.
    assert pm.ESPORTS_MARKET_TYPES["moneyline"] is MarketType.MONEYLINE
    for mod in ESPORTS_LEAGUES:
        assert MarketType.MONEYLINE_3WAY not in mod.OUTPUT_ORDER, mod.league


# === Rules ===

def test_handicap_binds_the_named_team_to_its_own_line():
    # The captured team and the captured line come from the SAME parenthetical,
    # so the bound sign is right regardless of which side poly abbreviates.
    for mod in ESPORTS_LEAGUES:
        assert mod.POLYMARKET is not None
        for question, want_entity, want_line in LIVE_HANDICAPS:
            parsed = pm.parse_question(question, mod.POLYMARKET)
            assert parsed is not None, f"{mod.league}: dropped {question}"
            assert parsed.market_type is MarketType.MAP_HANDICAP, question
            assert parsed.side_mode is pm.SideMode.SPREAD_TEAM, question
            assert parsed.entity == want_entity, question
            assert parsed.line == want_line, question
            # team_a/team_b stay None: the fixture is resolved from the two
            # outcome LABELS by pipeline._match_poly_game_fixture, exactly as
            # for tennis set handicaps and MLB spreads.
            assert parsed.team_a is None and parsed.team_b is None, question


def test_total_maps_names_no_competitor_and_defers_to_phase_b():
    for mod in ESPORTS_LEAGUES:
        assert mod.POLYMARKET is not None
        for question, want_line in LIVE_TOTALS:
            parsed = pm.parse_question(question, mod.POLYMARKET)
            assert parsed is not None, f"{mod.league}: dropped {question}"
            assert parsed.market_type is MarketType.TOTAL_MAPS, question
            assert parsed.side_mode is pm.SideMode.OVER_UNDER, question
            assert parsed.line == want_line, question
            assert parsed.team_a is None and parsed.team_b is None, question


def test_moneyline_parses_for_every_game_title():
    for mod in ESPORTS_LEAGUES:
        assert mod.POLYMARKET is not None
        for question, want_a, want_b in LIVE_MONEYLINES:
            parsed = pm.parse_question(question, mod.POLYMARKET)
            assert parsed is not None, f"{mod.league}: dropped {question}"
            assert parsed.market_type is MarketType.MONEYLINE, question
            assert parsed.side_mode is pm.SideMode.TEAM_LABEL, question
            assert (parsed.team_a, parsed.team_b) == (want_a, want_b), question


def test_unmappable_forms_stay_unrecognized():
    for mod in ESPORTS_LEAGUES:
        assert mod.POLYMARKET is not None
        for question in UNMAPPABLE:
            parsed = pm.parse_question(question, mod.POLYMARKET)
            assert parsed is None, f"{mod.league}: {question} -> {parsed}"


def test_map_winner_never_becomes_a_series_moneyline():
    # The mis-price this guard prevents: map 2's winner is not the series
    # winner, but both would stamp onto the same optic moneyline odds.
    q = "LoL: Kits Esports vs SDM Tigres (BO3) - Game 2 Winner"
    assert pm._Q_ESPORTS_MONEYLINE.match(q) is not None  # regex alone matches
    assert pm.parse_question(q, LOL_POLY) is None  # rule rejects it


def test_rules_are_mutually_disjoint():
    # Every rule anchors on a literal the others cannot carry, so ordering in
    # esports_market_rules is defensive rather than load-bearing.
    every = [q for q, _, _ in LIVE_HANDICAPS] + [q for q, _ in LIVE_TOTALS] \
        + [q for q, _, _ in LIVE_MONEYLINES]
    for question in every:
        hits = [r for r in pm.esports_market_rules
                if r(question, LOL_POLY) is not None]
        assert len(hits) == 1, f"{question} matched {[r.__name__ for r in hits]}"


# === League wiring ===

def test_cs2_and_dota2_registered():
    for slug in ("cs2", "dota_2"):
        assert slug in LEAGUES
        assert LEAGUES[slug].sport is Sport.ESPORTS
        assert slug in SUPPORTED_LEAGUES
        assert optic_api_key_secret(slug) == "opticodds_access_key"


def test_optic_league_ids_match_the_enum_values():
    # League slug MUST equal the optic league_id for these (bare "cs2" /
    # "dota_2"), the same convention mlb/npb/kbo follow.
    assert LEAGUES["cs2"].OPTIC.league_id == "cs2"
    assert LEAGUES["dota_2"].OPTIC.league_id == "dota_2"


def test_poly_slug_prefixes_pin_to_the_right_optic_league():
    # Only CS2 has prefix == league_id. Getting either field wrong is a SILENT
    # no-op, not a crash: pipeline.run filters bridge rows with
    # `slug.startswith(prefix + "-")`, so a wrong prefix matches zero markets.
    assert (CS2_POLY.slug_prefix, CS2_POLY.optic_league_id) \
        == ("cs2", "cs2")
    # poly "dota2" (no separator) vs optic "dota_2" -- the one disagreement.
    assert (DOTA_POLY.slug_prefix, DOTA_POLY.optic_league_id) \
        == ("dota2", "dota_2")
    assert (LOL_POLY.slug_prefix, LOL_POLY.optic_league_id) \
        == ("lol", "league_of_legends")


def test_slug_prefixes_are_distinct():
    prefixes = []
    for cfg in ESPORTS_LEAGUES:
        assert cfg.POLYMARKET is not None
        prefixes.append(cfg.POLYMARKET.slug_prefix)
    assert len(set(prefixes)) == len(prefixes), prefixes
