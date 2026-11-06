"""Tests for fetch.optic odds deduplication."""

import pytest

from fetch.optic import (
    deduplicate_odds,
    fixture_competitor_ids,
    process_fixture,
)

# Optic quoted this fighter under two competitor ids on 2026-07-29 — six
# of nine books used ORPHAN_TEAM_ID, which was not in the fight at all.
FIXTURE_TEAM_ID = "7E916A380D548EBC"
ORPHAN_TEAM_ID = "A0E8335CDA8A0F87"
OPPONENT_TEAM_ID = "F95CC128A0BE"


def _odd_entry(sportsbook: str, clean_id: str, source_ids: dict | None,
               team_id: str | None = None, name: str | None = None,
               selection: str = "Team A"):
    entry = {
        "id": f"game:{sportsbook.lower()}:{clean_id}",
        "sportsbook": sportsbook,
        "market_id": "moneyline",
        "selection": selection,
        "grouping_key": "default",
        "source_ids": source_ids,
    }
    if team_id is not None:
        entry["team_id"] = team_id
    if name is not None:
        entry["name"] = name
    return entry


def test_deduplicate_preserves_prediction_market_source_ids():
    clean_id = "moneyline:team_a"
    odds = [
        _odd_entry("DraftKings", clean_id, None),
        _odd_entry(
            "Polymarket",
            clean_id,
            {"selection_id": "poly-token"},
        ),
        _odd_entry(
            "Novig",
            clean_id,
            {"selection_id": "novig-token"},
        ),
        _odd_entry(
            "Polymarket (USA)",
            clean_id,
            {"selection_id": "poly-usa-token"},
        ),
    ]

    result = deduplicate_odds(odds)
    assert len(result) == 1
    src = result[0]["source_ids"]
    assert src["Polymarket"] == {"selection_id": "poly-token"}
    assert src["Novig"] == {"selection_id": "novig-token"}
    assert src["Polymarket (USA)"] == {"selection_id": "poly-usa-token"}
    assert "DraftKings" not in src


def test_deduplicate_preserves_crypto_com_source_ids():
    clean_id = "moneyline:team_a"
    odds = [
        _odd_entry("DraftKings", clean_id, None),
        {
            **_odd_entry(
                "crypto.com",
                clean_id,
                {"market_id": "MLB-00001-260727-M-ML-O11_261130-2300_1_PM.NPO"},
            ),
            "timestamp": 1700000000.5,
        },
    ]

    result = deduplicate_odds(odds)
    assert len(result) == 1
    src = result[0]["source_ids"]
    assert src["crypto.com"]["market_id"].endswith("PM.NPO")
    assert "DraftKings" not in src
    assert result[0]["timestamp"] == 1700000000.5


def test_deduplicate_still_preserves_kalshi_and_prophet_x():
    clean_id = "moneyline:team_a"
    odds = [
        _odd_entry(
            "Kalshi",
            clean_id,
            {"market_id": "KXTEST", "selection_id": "yes"},
        ),
        _odd_entry(
            "Prophet X",
            clean_id,
            {"event_id": "123", "selection_id": "abc"},
        ),
    ]

    result = deduplicate_odds(odds)
    src = result[0]["source_ids"]
    assert src["Kalshi"]["market_id"] == "KXTEST"
    assert src["Prophet X"]["event_id"] == "123"


@pytest.mark.parametrize("first,second", [
    (ORPHAN_TEAM_ID, FIXTURE_TEAM_ID),
    (FIXTURE_TEAM_ID, ORPHAN_TEAM_ID),
])
def test_conflicting_team_id_resolves_to_the_fixture_competitor(
        first, second, capsys):
    clean_id = "moneyline:nigma_galaxy"
    odds = [
        _odd_entry("DraftKings", clean_id, None, first),
        _odd_entry("Kalshi", clean_id, {"market_id": "KXTEST"}, second),
    ]

    result = deduplicate_odds(
        odds, frozenset({FIXTURE_TEAM_ID, OPPONENT_TEAM_ID}))
    assert len(result) == 1
    assert result[0]["team_id"] == FIXTURE_TEAM_ID
    out = capsys.readouterr().out
    assert "ALERT" not in out
    assert "kept fixture competitor" in out


def test_conflicting_team_id_raises_when_neither_is_in_the_fixture():
    clean_id = "moneyline:team_a"
    odds = [
        _odd_entry("DraftKings", clean_id, None, ORPHAN_TEAM_ID),
        _odd_entry("Kalshi", clean_id, None, "0123456789ABCDEF"),
    ]

    with pytest.raises(AssertionError):
        deduplicate_odds(odds, frozenset({OPPONENT_TEAM_ID}))


@pytest.mark.parametrize("field", ["name", "selection"])
@pytest.mark.parametrize("fixture_name,other", [
    ("Kenny de Schepper", "Kenny De Schepper"),
    ("Santiago De la Fuente", "Santiago De La Fuente"),
    ("Andrea de Marchi", "Andrea De Marchi"),
])
@pytest.mark.parametrize("first_is_fixture", [True, False])
def test_conflicting_label_resolves_to_fixture_spelling(
        field, fixture_name, other, first_is_fixture, capsys):
    first, second = ((fixture_name, other) if first_is_fixture
                     else (other, fixture_name))
    clean_id = "moneyline:player_a"
    odds = [
        _odd_entry("DraftKings", clean_id, None, **{field: first}),
        _odd_entry("FanDuel", clean_id, None, **{field: second}),
    ]

    result = deduplicate_odds(odds, competitor_names=(fixture_name, "Opponent"))
    assert len(result) == 1
    assert result[0][field] == fixture_name
    out = capsys.readouterr().out
    assert "ALERT" not in out
    assert f"dropped duplicate {field}" in out
    assert fixture_name in out


@pytest.mark.parametrize("field", ["name", "selection"])
def test_conflicting_label_raises_when_not_case_only(field):
    clean_id = "moneyline:player_a"
    odds = [
        _odd_entry("DraftKings", clean_id, None, **{field: "Andrea de Marchi"}),
        _odd_entry("FanDuel", clean_id, None, **{field: "Andrea da Marchi"}),
    ]

    with pytest.raises(AssertionError):
        deduplicate_odds(odds, competitor_names=("Kenny de Schepper",))


@pytest.mark.parametrize("field", ["name", "selection"])
@pytest.mark.parametrize("first,second", [
    ("Kenny de Schepper", "Kenny De Schepper"),
    ("Kenny De Schepper", "Kenny de Schepper"),
])
def test_process_fixture_resolves_label_from_its_own_competitors(
        field, first, second):
    clean_id = "moneyline:player_a"
    fixture = {
        "id": "20260827E84AC2B9",
        "home_competitors": [
            {"id": "5444D8FF5A827CC7", "name": "Kenny de Schepper"}],
        "away_competitors": [
            {"id": "OPPONENT_ID", "name": "Yannik Kelm"}],
        "odds": [
            _odd_entry("DraftKings", clean_id, None, **{field: first}),
            _odd_entry("FanDuel", clean_id, None, **{field: second}),
        ],
    }

    result = process_fixture(fixture)
    assert len(result["odds"]) == 1
    assert result["odds"][0][field] == "Kenny de Schepper"


def test_process_fixture_resolves_team_id_from_its_own_competitors():
    clean_id = "moneyline:team_a"
    fixture = {
        "id": "20260801BA4BBFF1",
        "home_competitors": [
            {"id": FIXTURE_TEAM_ID, "name": "Marina Spasic"}],
        "away_competitors": [
            {"id": OPPONENT_TEAM_ID, "name": "Stephanie Luciano"}],
        "odds": [
            _odd_entry("DraftKings", clean_id, None, ORPHAN_TEAM_ID),
            _odd_entry("FanDuel", clean_id, None, ORPHAN_TEAM_ID),
            _odd_entry("Kalshi", clean_id, {"market_id": "KXUFC"},
                       FIXTURE_TEAM_ID),
        ],
    }

    assert fixture_competitor_ids(fixture) == {
        FIXTURE_TEAM_ID, OPPONENT_TEAM_ID}
    result = process_fixture(fixture)
    assert len(result["odds"]) == 1
    assert result["odds"][0]["team_id"] == FIXTURE_TEAM_ID
    assert result["odds"][0]["source_ids"]["Kalshi"]["market_id"] == "KXUFC"


def test_prediction_market_batches_respect_five_book_cap():
    from fetch.optic import _SPORTSBOOKS_PER_REQUEST, SPORTSBOOK_BATCHES
    from mappers.exchanges.optic import PREDICTION_MARKET_SPORTSBOOK_IDS

    assert "crypto_com" in PREDICTION_MARKET_SPORTSBOOK_IDS
    pred_batches = [
        b for b in SPORTSBOOK_BATCHES
        if any(sb in PREDICTION_MARKET_SPORTSBOOK_IDS for sb in b)
    ]
    assert pred_batches
    assert all(len(b) <= _SPORTSBOOKS_PER_REQUEST for b in pred_batches)
    assert any("crypto_com" in b for b in pred_batches)
