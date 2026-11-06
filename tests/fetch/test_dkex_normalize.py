"""DKEX fetch normalization (REST metadata shape)."""

from __future__ import annotations

from datetime import UTC, datetime

from fetch.dkex import normalize


def test_normalize_api_uses_competition_start() -> None:
    raw = {
        "ticker": "NFL-WIN-FG-01O0F7PEVSSRVBG-DEOS024",
        "status": "active",
        "marketCloseTimestamp": "2026-04-11T13:00:00Z",
        "metadata": {
            "competitionStartTime": "2026-04-11T01:00:00Z",
            "competitionName": "DEN @ KC",
            "participants": [{"id": "DKT_1", "name": "DEN Broncos"}],
        },
        "parameters": {"participant": "DKT_1"},
    }
    row = normalize(raw, "api")
    assert row["status"] == "active"
    assert row["event_start"] == "2026-04-11T01:00:00+00:00"
    assert row["participant_name"] == "DEN Broncos"


def test_normalize_reports_derives_start_from_maturity() -> None:
    close = datetime(2026, 4, 11, 13, 0, tzinfo=UTC)
    raw = {
        "ticker": "NFL-WIN-FG-EV-TEAM1",
        "status": "Open",
        "marketCloseTimestamp": close.isoformat(),
    }
    row = normalize(raw, "reports")
    assert row["event_start"].startswith("2026-03-12")


def _staging(ticker: str) -> dict:
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "fixtures" / "dkex" / "staging_markets_2026-09-28.json"
    return next(r for r in json.loads(path.read_text(encoding="utf-8")) if r["ticker"] == ticker)


def test_normalize_keeps_the_typed_identity_fields() -> None:
    """The brief's example row, straight from staging."""
    row = normalize(_staging("BSA-MOVY-FG-02L4HV50HIO28DG-SALO008-GTE-P00035"), "api")
    assert row["stat_achievement"] == "MOVY"
    assert row["time_period"] == "FG"
    assert row["strike_price"] == 3.5
    assert row["outcome_type"] == "GTE"
    assert row["competition_id"] == "02L4HV50HIO28DG"
    assert row["sub_topic"] == "Brazil - Serie A"
    assert row["league_name"] == "Brazil - Serie A"
    assert row["intake_event_id"]
    assert row["participant_id"] == "DKT_0122GRI10PFAO"
    assert row["participants"] == [
        {"id": "DKT_0122GRI10PFAO", "name": "Sao Paulo", "role": "away"},
    ]


def test_normalize_player_prop_participant_has_no_role() -> None:
    row = normalize(_staging("NFL-PREY-FG-01S2LVEPIUCM13O-DEON230-GTE-P00195"), "api")
    assert row["participants"][0]["role"] is None
    assert row["participant_name"] == "Denzel Boston"
    assert row["strike_price"] == 19.5


def test_normalize_game_total_has_no_participant() -> None:
    row = normalize(_staging("NFL-TPTS-FG-01S2KTKBIUCN390-GTE-P00605"), "api")
    assert row["participant_id"] is None
    assert row["participants"] == []
    assert row["strike_price"] == 60.5


def test_normalize_reports_row_leaves_typed_fields_empty() -> None:
    """The CSV seed has only the symbol; nothing is sliced out of it."""
    row = normalize({"ticker": "NFL-MOVY-FG-01S2KTKBIUCN390-SFRS000-GTE-P00035",
                     "status": "Open"}, "reports")
    for key in ("stat_achievement", "time_period", "strike_price", "outcome_type",
                "competition_id", "sub_topic", "league_name"):
        assert row[key] is None, key
    assert row["participants"] == []
