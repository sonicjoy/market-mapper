"""Soccer fixtures ask one extra, market-filtered batch for 1H first team to score."""

from __future__ import annotations

from typing import Any

import fetch.optic as optic


def _capture(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_get(url, headers, params=None):
        calls.append(params or {})
        return [{"id": "F1", "odds": [{"id": f"o{len(calls)}"}]}]

    monkeypatch.setattr(optic, "get_optic", fake_get)
    monkeypatch.setattr(optic, "sleep", lambda _s: None)
    return calls


def test_extra_tuple_batch_sends_its_market_filter(monkeypatch):
    calls = _capture(monkeypatch)
    out = optic.get_fixture_odds({}, "F1", [optic.SOCCER_1H_FTTS_BATCH])
    last = calls[-1]
    assert last["market"] == "1st_half_first_team_to_score"
    assert last["sportsbook"] == ["pinnacle", "bwin", "dafabet", "ladbrokes"]
    assert all("market" not in c for c in calls[:-1])
    assert len(out["odds"]) == len(calls)


def test_plain_list_batch_has_no_market_filter(monkeypatch):
    calls = _capture(monkeypatch)
    optic.get_fixture_odds({}, "F1", [optic.DARTS_SPORTSBOOK_BATCH])
    assert "market" not in calls[-1]


def test_soccer_fixture_gets_the_extra_batch_and_football_does_not(monkeypatch):
    seen: dict[str, list] = {}

    def fake(headers, fixture_id, extra=()):
        seen[fixture_id] = list(extra)
        return {"id": fixture_id, "odds": []}

    monkeypatch.setattr(optic, "get_fixture_odds", fake)
    monkeypatch.setattr(optic, "process_fixture", lambda f: f)
    optic.fetch_processed_fixture({}, {"id": "S", "sport": {"id": "soccer"}})
    optic.fetch_processed_fixture({}, {"id": "N", "sport": {"id": "football"}})
    assert seen["S"] == [optic.SOCCER_1H_FTTS_BATCH]
    assert seen["N"] == []
