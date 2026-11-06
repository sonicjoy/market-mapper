"""Per-question-form name-granularity mechanism (task TN2).

Tennis forms label players by SURNAME-only (last whitespace token of the
full name -- "Luca Van Assche" -> "Assche") for match_total_games/
set_handicap/set_games/set_winner, while moneyline/total_sets use full
names -- see .superpowers/sdd/wave-tennis-probe-findings.md section C.2.
This mechanism is per-question-form (ParsedMarket.name_granularity), not
per-league, since the granularity varies within the same league/config.

All fixtures/markets here are SYNTHETIC -- constructed directly, no
recognizer involved (recognizers are a separate later task).
"""

import dataclasses

from mappers.exchanges import polymarket as pm
from mappers.market_types import MarketType
from mappers.pipeline import _match_poly_fixture

TENNIS_CFG = pm.PolymarketConfig(
    slug_prefix="atp", optic_league_id="atp",
    market_types={}, question_style="tennis_prefix", market_rules=(),
)


class _FX:
    def __init__(self, home_name, away_name, start_date):
        self.home_name = home_name
        self.away_name = away_name
        self.start_date = start_date


def _bt(**kw):
    """build_rows with common tennis fixture kwargs; caller passes market+parsed."""
    base = {"home": "ASSCHE", "away": "BUSTA", "home_name": "Luca Van Assche",
            "away_name": "Pablo Carreno Busta", "start_date": "2026-07-23T14:00:00Z",
            "cfg": TENNIS_CFG, "league": "atp"}
    base.update(kw)
    return pm.build_rows(**base)


def _mkt(question, outcomes):
    return pm.PolyMarket(condition_id="0xtn2", slug="atp-assche-busta-2026-07-23",
                         question=question,
                         outcomes=[pm.PolyOutcome(**o) for o in outcomes])


# === ParsedMarket.name_granularity field ===


def test_parsed_market_defaults_to_full_granularity():
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE, team_a="a", team_b="b",
                             side_mode=pm.SideMode.TEAM_LABEL)
    assert parsed.name_granularity == "full"


def test_parsed_market_accepts_surname_granularity():
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE, team_a="a", team_b="b",
                             side_mode=pm.SideMode.TEAM_LABEL, name_granularity="surname")
    assert parsed.name_granularity == "surname"


# === _match_name helper: unit-level ===


def test_match_name_surname_matches_last_token_of_full_name():
    assert pm._match_name("assche", "Luca Van Assche", "tennis_prefix", "surname")
    assert pm._match_name("busta", "Pablo Carreno Busta", "tennis_prefix", "surname")


def test_match_name_surname_does_not_match_wrong_player():
    assert not pm._match_name("assche", "Pablo Carreno Busta", "tennis_prefix", "surname")


def test_match_name_surname_hyphenated_surname_stays_one_token():
    # normalize_player_name never splits on hyphens -- "Auger-Aliassime" stays
    # one token, so the surname-only label agrees with the last token exactly.
    assert pm._match_name("auger-aliassime", "Felix Auger-Aliassime", "tennis_prefix", "surname")


def test_match_name_full_is_byte_identical_to_name_match_call():
    # granularity="full" must reduce to the exact pre-existing call pattern:
    # _name_match(poly_value, _norm_name(fixture_name, style), style).
    style = "tennis_prefix"
    poly_value = pm._norm_name("Luca Van Assche", style)
    expected = pm._name_match(poly_value, pm._norm_name("Luca Van Assche", style), style)
    assert pm._match_name(poly_value, "Luca Van Assche", style, "full") == expected is True


def test_match_name_full_does_not_match_bare_surname():
    # proves granularity="full" never secretly loosens to surname matching.
    assert not pm._match_name("assche", "Luca Van Assche", "tennis_prefix", "full")


# === _match_poly_fixture (pipeline.py consumer) ===


def test_match_poly_fixture_surname_resolves_to_fixture():
    fixtures = [_FX("Luca Van Assche", "Pablo Carreno Busta", "2026-07-23T14:00:00Z")]
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE, team_a="assche", team_b="busta",
                             side_mode=pm.SideMode.TEAM_LABEL, date="2026-07-23",
                             name_granularity="surname")
    fx = _match_poly_fixture(parsed, fixtures, "tennis_prefix")
    assert fx is fixtures[0]


def test_match_poly_fixture_surname_resolves_either_orientation():
    fixtures = [_FX("Pablo Carreno Busta", "Luca Van Assche", "2026-07-23T14:00:00Z")]
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE, team_a="assche", team_b="busta",
                             side_mode=pm.SideMode.TEAM_LABEL, date="2026-07-23",
                             name_granularity="surname")
    fx = _match_poly_fixture(parsed, fixtures, "tennis_prefix")
    assert fx is fixtures[0]


def test_match_poly_fixture_full_granularity_default_rejects_surname_pair():
    # Backward-compat: a surname-shaped team_a/team_b under the DEFAULT
    # granularity ("full") must NOT match a fixture named by full names --
    # proving the default path did not secretly loosen to surname matching.
    fixtures = [_FX("Luca Van Assche", "Pablo Carreno Busta", "2026-07-23T14:00:00Z")]
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE, team_a="assche", team_b="busta",
                             side_mode=pm.SideMode.TEAM_LABEL, date="2026-07-23")
    assert parsed.name_granularity == "full"
    assert _match_poly_fixture(parsed, fixtures, "tennis_prefix") is None


def test_match_poly_fixture_collision_across_two_fixtures_drops():
    # Same surname pair matches TWO distinct fixtures on the same day (e.g. a
    # coincidental same-surname pairing on a different tournament) -> ambiguous,
    # must drop rather than guess (flip-safety).
    fixtures = [
        _FX("Luca Van Assche", "Pablo Carreno Busta", "2026-07-23T14:00:00Z"),
        _FX("Someone Else Assche", "Another Guy Busta", "2026-07-23T18:00:00Z"),
    ]
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE, team_a="assche", team_b="busta",
                             side_mode=pm.SideMode.TEAM_LABEL, date="2026-07-23",
                             name_granularity="surname")
    assert _match_poly_fixture(parsed, fixtures, "tennis_prefix") is None


def test_match_poly_fixture_within_fixture_surname_collision_drops():
    # Both competitors of the SAME fixture share the last-token surname (two
    # "Silva"s) -> that fixture is inherently ambiguous for surname matching,
    # must drop rather than guess which one is which.
    fixtures = [_FX("Thiago Silva", "Bruno Silva", "2026-07-23T14:00:00Z")]
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE, team_a="silva", team_b="silva",
                             side_mode=pm.SideMode.TEAM_LABEL, date="2026-07-23",
                             name_granularity="surname")
    assert _match_poly_fixture(parsed, fixtures, "tennis_prefix") is None


def test_match_poly_fixture_full_granularity_unchanged_for_existing_full_name_form():
    # Regression: the plain full-name path (moneyline/total_sets shape) must
    # keep resolving exactly as before this task.
    fixtures = [_FX("Luca Van Assche", "Pablo Carreno Busta", "2026-07-23T14:00:00Z")]
    parsed = pm.ParsedMarket(
        market_type=MarketType.MONEYLINE,
        team_a=pm._norm_name("Luca Van Assche", "tennis_prefix"),
        team_b=pm._norm_name("Pablo Carreno Busta", "tennis_prefix"),
        side_mode=pm.SideMode.TEAM_LABEL, date="2026-07-23",
    )
    fx = _match_poly_fixture(parsed, fixtures, "tennis_prefix")
    assert fx is fixtures[0]


# === build_rows TEAM_LABEL: outcome-label -> competitor resolution ===


def test_build_rows_team_label_surname_resolves_correct_side():
    m = _mkt("Assche vs. Busta: Set 1 Winner", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Assche", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "Busta", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE, team_a="assche", team_b="busta",
                             side_mode=pm.SideMode.TEAM_LABEL, name_granularity="surname")
    by = {r.polymarket_clob_token_id: r for r in _bt(market=m, parsed=parsed)}
    assert by["cA"].side == "ASSCHE"
    assert by["cB"].side == "BUSTA"


def test_build_rows_team_label_full_granularity_does_not_match_surname_label():
    # Backward-compat: the SAME surname outcome labels, under the DEFAULT
    # ("full") granularity, must NOT resolve -- proves default didn't loosen.
    m = _mkt("Assche vs. Busta: Set 1 Winner", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Assche", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "Busta", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE, team_a="assche", team_b="busta",
                             side_mode=pm.SideMode.TEAM_LABEL)
    assert parsed.name_granularity == "full"
    assert _bt(market=m, parsed=parsed) == []


def test_build_rows_team_label_full_granularity_unchanged_for_full_name_form():
    # Regression: full-name TEAM_LABEL (moneyline shape) resolves exactly as
    # before this task.
    m = _mkt("Luca Van Assche vs. Pablo Carreno Busta", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Luca Van Assche", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "Pablo Carreno Busta", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(
        market_type=MarketType.MONEYLINE,
        team_a=pm._norm_name("Luca Van Assche", "tennis_prefix"),
        team_b=pm._norm_name("Pablo Carreno Busta", "tennis_prefix"),
        side_mode=pm.SideMode.TEAM_LABEL,
    )
    by = {r.polymarket_clob_token_id: r for r in _bt(market=m, parsed=parsed)}
    assert by["cA"].side == "ASSCHE"
    assert by["cB"].side == "BUSTA"


def test_build_rows_team_label_surname_collision_drops():
    # Both fixture competitors share the last-token surname ("Silva") -- any
    # surname-based label resolution against this fixture is inherently
    # ambiguous -> drop whole market rather than guess.
    m = _mkt("Silva vs. Silva: Set 1 Winner", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Silva", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "Silva", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE, team_a="silva", team_b="silva",
                             side_mode=pm.SideMode.TEAM_LABEL, name_granularity="surname")
    rows = _bt(market=m, parsed=parsed, home_name="Thiago Silva", away_name="Bruno Silva")
    assert rows == []


# === build_rows SPREAD_TEAM: entity -> competitor resolution ===


def test_build_rows_spread_team_entity_surname_resolves():
    m = _mkt("Set Handicap: Assche (-1.5) vs Busta (+1.5)", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Assche", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "Busta", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.POINT_SPREAD, team_a="assche", team_b="busta",
                             side_mode=pm.SideMode.SPREAD_TEAM, entity="assche", line=-1.5,
                             name_granularity="surname")
    by = {r.polymarket_clob_token_id: r for r in _bt(market=m, parsed=parsed)}
    assert by["cA"].side == "ASSCHE" and by["cA"].line == -1.5
    assert by["cB"].side == "BUSTA" and by["cB"].line == 1.5


def test_build_rows_spread_team_full_granularity_does_not_match_surname_entity():
    # Backward-compat: the same surname entity/labels, under DEFAULT ("full")
    # granularity, must NOT resolve.
    m = _mkt("Set Handicap: Assche (-1.5) vs Busta (+1.5)", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Assche", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "Busta", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.POINT_SPREAD, team_a="assche", team_b="busta",
                             side_mode=pm.SideMode.SPREAD_TEAM, entity="assche", line=-1.5)
    assert parsed.name_granularity == "full"
    assert _bt(market=m, parsed=parsed) == []


def test_build_rows_spread_team_surname_collision_drops():
    m = _mkt("Set Handicap: Silva (-1.5) vs Silva (+1.5)", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Silva", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "Silva", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(market_type=MarketType.POINT_SPREAD, team_a="silva", team_b="silva",
                             side_mode=pm.SideMode.SPREAD_TEAM, entity="silva", line=-1.5,
                             name_granularity="surname")
    rows = _bt(market=m, parsed=parsed, home_name="Thiago Silva", away_name="Bruno Silva")
    assert rows == []


def test_build_rows_spread_team_full_granularity_unchanged_for_full_name_form():
    # Regression: full-name SPREAD_TEAM (existing MLB-shape usage elsewhere)
    # still resolves via tennis full names too, byte-identical dispatch.
    m = _mkt("Luca Van Assche -1.5 vs. Pablo Carreno Busta", [
        {"clob_token_id": "cA", "position_id": "pA", "outcome_label": "Luca Van Assche", "outcome_index": 0},
        {"clob_token_id": "cB", "position_id": "pB", "outcome_label": "Pablo Carreno Busta", "outcome_index": 1},
    ])
    parsed = pm.ParsedMarket(
        market_type=MarketType.POINT_SPREAD,
        team_a=pm._norm_name("Luca Van Assche", "tennis_prefix"),
        team_b=pm._norm_name("Pablo Carreno Busta", "tennis_prefix"),
        side_mode=pm.SideMode.SPREAD_TEAM,
        entity=pm._norm_name("Luca Van Assche", "tennis_prefix"), line=-1.5,
    )
    by = {r.polymarket_clob_token_id: r for r in _bt(market=m, parsed=parsed)}
    assert by["cA"].side == "ASSCHE" and by["cA"].line == -1.5
    assert by["cB"].side == "BUSTA" and by["cB"].line == 1.5


# === dataclasses.replace() sanity (pipeline's Phase-B pattern uses replace) ===


def test_dataclasses_replace_preserves_name_granularity():
    parsed = pm.ParsedMarket(market_type=MarketType.MONEYLINE, team_a="assche", team_b="busta",
                             side_mode=pm.SideMode.TEAM_LABEL, name_granularity="surname")
    replaced = dataclasses.replace(parsed, date="2026-07-23")
    assert replaced.name_granularity == "surname"
