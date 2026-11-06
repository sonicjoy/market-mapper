"""Tests for the League of Legends (esports) matcher.

LoL is the first esports league wired into the mapper and the first
non-traditional Sport. It was moneyline-only for its first two weeks — Optic
shipped nothing else (24h of opticodds_prices for league="League of Legends"
yielded exactly one distinct market_id on 2026-07-28) — and now carries the
shared three-market esports taxonomy (moneyline / map_handicap / total_maps;
see leagues/esports_markets.py). The handicap and total forms are exercised in
tests/mappers/test_polymarket_esports.py, which covers all three games at once;
this module stays focused on LoL's own wiring and its live moneyline corpus.

The questions below are byte-exact from LIVE Polymarket gamma markets
(2026-07-28), resolved by clob_token_id from the token ids the Optic feed
carries in source_ids.selection_id — NOT synthesized. All 14 share the single
shape "LoL: <A> vs <B> (BO<n>) - <Tournament>" with slugs "lol-<a>-<b>-<date>",
which is why lol_moneyline_rule anchors group 2 on the literal "(" (UFC's
trick) rather than end-of-string.
"""

import os

os.environ.setdefault("GCP_PROJECT", "marketmaking-test")

from fetch.optic import SUPPORTED_LEAGUES  # noqa: E402
from fetch.tip import optic_api_key_secret  # noqa: E402
from mappers.exchanges import polymarket as pm  # noqa: E402
from mappers.market_types import MarketType, Scope, Shape  # noqa: E402
from mappers.run import LEAGUES  # noqa: E402
from mappers.sport import Sport, sport_for_league
from mappers.vocab.esports_markets import ESPORTS_OPTIC_TABLE_TYPES  # noqa: E402
from mappers.vocab.kalshi_scopes import scope_types  # noqa: E402
from tests.mappers._require import require  # noqa: E402

LOL_POLY = require(LEAGUES["lol"].POLYMARKET)

# Byte-exact live questions (gamma, 2026-07-28) -> expected (team_a, team_b)
# after _norm_name. BO1/BO3/BO5 and a tournament segment containing digits and
# a hyphen ("Rounds 3-4") are all represented.
LIVE_QUESTIONS: list[tuple[str, str, str]] = [
    ("LoL: 9z Globant vs Maze Gaming (BO5) - LRS Playoffs",
     "9z globant", "maze gaming"),
    ("LoL: DMG Esports vs 2 Massive (BO3) - NLC Regular Season",
     "dmg esports", "2 massive"),
    ("LoL: Disruptors vs One More Esports (BO3) - Arabian League Group Stage",
     "disruptors", "one more esports"),
    ("LoL: HMBLE vs Aeterna Esports (BO1) - LIT Regular Season",
     "hmble", "aeterna esports"),
    ("LoL: Karmine Corp Blue vs Galions (BO1) - LFL Regular Season",
     "karmine corp blue", "galions"),
    ("LoL: KT Rolster Challengers vs DN SOOPers Challengers (BO3) - "
     "LCK Challengers League Rounds 3-4 Challenge Group",
     "kt rolster challengers", "dn soopers challengers"),
    ("LoL: LEO vs Rich Gang (BO3) - NLC Regular Season",
     "leo", "rich gang"),
    ("LoL: Leviatan Esports vs paiN Gaming (BO3) - CBLOL Regular Season",
     "leviatan esports", "pain gaming"),
    ("LoL: Mental Rush vs Eterna (BO3) - Equal eSports Cup Playoffs",
     "mental rush", "eterna"),
    ("LoL: NRG Esports vs Winthrop University (BO3) - "
     "North American Challengers League Group Stage",
     "nrg esports", "winthrop university"),
    ("LoL: The Otter Side vs White Dragons (BO1) - LPLOL Group Stage",
     "the otter side", "white dragons"),
    ("LoL: VfB eSports vs G2 NORD (BO3) - Prime League 1st Division Group B",
     "vfb esports", "g2 nord"),
    ("LoL: ZeroZone Gaming vs Way Gaming Esports (BO1) - LPLOL Group Stage",
     "zerozone gaming", "way gaming esports"),
]


# === Wiring: "lol" registration ===

def test_lol_registered_in_pipeline_registry():
    assert "lol" in LEAGUES
    assert LEAGUES["lol"] is LEAGUES['lol']


def test_lol_is_esports():
    assert sport_for_league("lol") is Sport.ESPORTS


def test_lol_fetch_coverage_and_secret():
    assert "lol" in SUPPORTED_LEAGUES
    assert SUPPORTED_LEAGUES["lol"].league_id == "league_of_legends"
    assert optic_api_key_secret("lol") == "opticodds_access_key"


# Optic shipped moneyline ALONE for LoL when this league was wired
# (2026-07-28 census); `total_maps` and `map_handicap` appeared by 2026-08-11
# and are wired now. Both sides read the one shared esports taxonomy, so this
# asserts equality against it rather than restating the three keys — a fourth
# esports market added to esports_markets.py must reach LoL automatically.
def test_lol_optic_config_uses_shared_esports_taxonomy():
    assert LEAGUES['lol'].OPTIC.league_id == "league_of_legends"
    assert LEAGUES['lol'].OPTIC.table_types == ESPORTS_OPTIC_TABLE_TYPES
    # OUTPUT_ORDER also carries every type Kalshi's esports scopes can emit.
    assert set(LEAGUES['lol'].OUTPUT_ORDER) == (
        set(ESPORTS_OPTIC_TABLE_TYPES.values())
        | set(scope_types(Sport.ESPORTS).values())
    )


def test_lol_poly_config():
    assert LOL_POLY.slug_prefix == "lol"
    assert LOL_POLY.optic_league_id == "league_of_legends"
    assert LOL_POLY.market_types == pm.ESPORTS_MARKET_TYPES


def test_optic_and_poly_agree_on_esports_market_types():
    # Every poly MarketType needs an optic counterpart to stamp onto
    # (pipeline.attach_polymarket_row guard #3). Optic may price more (the
    # per-map winners Polymarket does not map).
    assert set(LOL_POLY.market_types.values()) <= set(
        LEAGUES['lol'].OPTIC.table_types.values())


def test_moneyline_reuses_game_scope_2way_shape():
    # No draw in a LoL series -> plain MONEYLINE, never MONEYLINE_3WAY.
    mt = MarketType.MONEYLINE
    assert mt.scope is Scope.GAME
    assert mt.shape is Shape.MONEYLINE
    assert MarketType.MONEYLINE_3WAY not in LEAGUES['lol'].OUTPUT_ORDER


# === Rule: every live question parses to the right two teams ===

def test_every_live_question_parses():
    for question, want_a, want_b in LIVE_QUESTIONS:
        parsed = pm.parse_question(question, LOL_POLY)
        assert parsed is not None, f"dropped: {question}"
        assert parsed.market_type is MarketType.MONEYLINE, question
        assert parsed.side_mode is pm.SideMode.TEAM_LABEL, question
        assert (parsed.team_a, parsed.team_b) == (want_a, want_b), question


def test_word_joiner_and_diacritics_are_normalized():
    """Poly ships at least one name with a U+2060 WORD JOINER prefix.

    Left unstripped it would never match the Optic fixture name, so this
    pins _norm_name's behaviour rather than the rule's.
    """
    question = ("LoL: ⁠Movistar KOI Fénix vs FALKE Esports (BO3) - "
                "LES Regular Season")
    parsed = pm.parse_question(question, LOL_POLY)
    assert parsed is not None
    # Narrow Optional before the containment check: team_a is str | None, and
    # `in` against None is a type error (pyright reportOperatorIssue).
    assert parsed.team_a is not None
    assert "⁠" not in parsed.team_a
    assert parsed.team_a == "movistar koi fenix"
    assert parsed.team_b == "falke esports"


def test_bo_and_tournament_suffix_are_not_captured_into_team_b():
    parsed = pm.parse_question(
        "LoL: T1 vs Gen.G (BO5) - LCK Playoffs", LOL_POLY)
    assert parsed is not None
    # _norm_name maps "." to a space, so "Gen.G" normalizes to "gen g".
    assert parsed.team_a == "t1"
    assert parsed.team_b == "gen g"
    assert "bo5" not in parsed.team_b
    assert "lck" not in parsed.team_b


# === Guards: the rule is not a catch-all, and MLB's is not reusable ===

def test_mlb_moneyline_rule_cannot_serve_lol():
    """Why a LoL-specific rule exists: MLB's drops anything containing ":"."""
    question = "LoL: T1 vs Gen.G (BO5) - LCK Playoffs"
    assert pm.mlb_moneyline_rule(question, LOL_POLY) is None


def test_lol_rule_ignores_other_leagues_questions():
    for question in (
        "Chicago Cubs vs St. Louis Cardinals",                  # MLB moneyline
        "Arsenal vs. Chelsea: O/U 2.5",                         # soccer total
        "UFC 300: Alex Pereira vs. Jamahal Hill (Light Heavyweight, Main)",
    ):
        assert pm.lol_moneyline_rule(question, LOL_POLY) is None, question


def test_lol_rule_needs_the_parenthetical():
    # Defensive: a "LoL: A vs B" with no "(...)" is not a shape we have seen;
    # it must be dropped rather than silently swallowing the rest of the line.
    assert pm.lol_moneyline_rule(
        "LoL: T1 vs Gen.G", LOL_POLY) is None


def test_market_types_absent_means_no_parse():
    cfg = pm.PolymarketConfig(
        slug_prefix="lol",
        optic_league_id="league_of_legends",
        market_types={},
        market_rules=pm.lol_market_rules,
    )
    assert pm.lol_moneyline_rule(
        "LoL: T1 vs Gen.G (BO5) - LCK Playoffs", cfg) is None
