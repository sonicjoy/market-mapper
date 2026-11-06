"""NBA fixtures ask one extra, market-filtered batch for race to 30 points, when switched on."""

from __future__ import annotations

import fetch.optic as optic


def _seen(monkeypatch) -> dict[str, list]:
    seen: dict[str, list] = {}

    def fake(headers, fixture_id, extra=()):
        seen[fixture_id] = list(extra)
        return {"id": fixture_id, "odds": []}

    monkeypatch.setattr(optic, "get_fixture_odds", fake)
    monkeypatch.setattr(optic, "process_fixture", lambda f: f)
    basketball = {"id": "basketball"}
    optic.fetch_processed_fixture({}, {"id": "N", "sport": basketball, "league": {"id": "nba"}})
    optic.fetch_processed_fixture({}, {"id": "W", "sport": basketball, "league": {"id": "wnba"}})
    return seen


def test_race_batch_is_off_by_default(monkeypatch):
    monkeypatch.delenv("OPTIC_NBA_RACE_TO_30", raising=False)
    assert _seen(monkeypatch) == {"N": [], "W": []}


def test_switched_on_only_nba_gets_the_race_batch(monkeypatch):
    monkeypatch.setenv("OPTIC_NBA_RACE_TO_30", "1")
    assert _seen(monkeypatch) == {"N": [optic.NBA_RACE_TO_30_BATCH], "W": []}
    books, market = optic.NBA_RACE_TO_30_BATCH
    assert market == "race_to_30_points" and len(books) <= 5
