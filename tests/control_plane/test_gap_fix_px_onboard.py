"""ProphetX RFQ tournament onboard."""

from __future__ import annotations

from unittest.mock import patch

from mappers.control_plane.gap_fix_px_onboard import (
    harvest_px_rfq_onboard,
    try_px_league_onboard,
)
from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.rows import LeagueRow
from tests.control_plane.gap_store_helpers import _soccer_store


def test_px_onboard_drafts_league() -> None:
    store = _soccer_store()
    event = {
        "event_id": 60069572,
        "tournament_id": 648,
        "display_name": "North Carolina Tar Heels at Duke Blue Devils",
        "scheduled": "2026-03-07T23:30:00Z",
        "competitors": [
            {"side": "home", "display_name": "Duke Blue Devils"},
            {"side": "away", "display_name": "North Carolina Tar Heels"},
        ],
    }
    pins: list[dict] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    rule_set_id = store.current_rule_set_id
    assert rule_set_id
    rows = list(store.leagues_for(rule_set_id))
    with patch(
        "mappers.control_plane.gap_fix_px_onboard.discover_optic_league_id",
        return_value="ncaab",
    ):
        ok = try_px_league_onboard(
            store,
            "60069572",
            "60069572:line1",
            pins,
            skipped,
            seen,
            rows,
            {},
            event_lookup_fn=lambda _eid: event,
        )
    assert ok is True
    assert pins[0]["harvest_book"] == "prophetx"


def test_later_px_line_stays_on_the_event_pin() -> None:
    store = _soccer_store()
    event = {
        "event_id": 60069572,
        "tournament_id": 648,
        "display_name": "North Carolina Tar Heels at Duke Blue Devils",
        "scheduled": "2026-03-07T23:30:00Z",
        "competitors": [
            {"side": "home", "display_name": "Duke Blue Devils"},
            {"side": "away", "display_name": "North Carolina Tar Heels"},
        ],
    }
    pins: list[dict] = []
    skipped: list[dict[str, str]] = []
    rule_set_id = store.current_rule_set_id
    assert rule_set_id
    rows = list(store.leagues_for(rule_set_id))
    items = [
        RfqGapItem("prophetx", "60069572:line1", 4, meta={"px_event_id": "60069572"}),
        RfqGapItem("prophetx", "60069572:line2", 2, meta={"px_event_id": "60069572"}),
    ]
    with patch(
        "mappers.control_plane.gap_fix_px_onboard.discover_optic_league_id",
        return_value="ncaab",
    ):
        harvest_px_rfq_onboard(
            store, items, pins, skipped, set(), rows, {},
            event_lookup_fn=lambda _eid: event,
        )
    assert skipped == []
    assert len(pins) == 1
    covered = {str(pins[0].get("harvest_key") or "")}
    covered.update(str(item) for item in (pins[0].get("harvest_keys") or []))
    assert covered == {"60069572:line1", "60069572:line2"}


def test_px_without_an_event_is_not_needs_probe() -> None:
    pins: list[dict] = []
    skipped: list[dict[str, str]] = []
    harvest_px_rfq_onboard(
        _soccer_store(),
        [RfqGapItem("prophetx", "1:line", 1, meta={"px_event_id": "1"})],
        pins,
        skipped,
        set(),
        [],
        {},
        event_lookup_fn=lambda _eid: None,
    )
    assert pins == []
    assert skipped == [{"book": "prophetx", "key": "1:line", "reason": "no_source_league"}]


def test_wired_px_rfq_pins_the_name_bind() -> None:
    """A tournament already on the tip drafts the shared name bind on the RFQ key."""
    row = LeagueRow(
        league="ncaab",
        sport="basketball",
        optic_league_id="ncaab",
        extra_optic_league_ids=[],
        fixture_source="optic",
        fixture_horizon_hours=24,
        enabled=True,
        output_order=[],
        exchanges=[{
            "sportsbook": "px",
            "enabled": True,
            "settings": {"tournament_id": "648"},
        }],
    )

    class _Store:
        current_rule_set_id = "tip"

        def leagues_for(self, _rid: str) -> list[LeagueRow]:
            return [row]

        def entities_for(self, _rid: str) -> list[object]:
            return []

    event = {
        "event_id": 60069572,
        "tournament_id": 648,
        "scheduled": "2026-03-07T23:30:00Z",
        "competitors": [
            {"side": "home", "abbreviation": "HUL", "name": "Duke Blue Devils"},
            {"side": "away", "abbreviation": "TAR", "name": "North Carolina Tar Heels"},
        ],
    }
    game = {
        "start_date": "2026-03-07T23:30:00Z",
        "home_competitors": [{
            "abbreviation": "DUK", "name": "Duke Blue Devils", "id": "oid-duk",
        }],
        "away_competitors": [{
            "abbreviation": "UNC", "name": "North Carolina Tar Heels", "id": "oid-unc",
        }],
    }
    pins: list[dict] = []
    skipped: list[dict[str, str]] = []
    with patch(
        "mappers.control_plane.gap_fix_px_onboard.discover_optic_league_id",
        return_value="ncaab",
    ):
        harvest_px_rfq_onboard(
            _Store(),
            [RfqGapItem(
                "prophetx", "60069572:line1", 4, meta={"px_event_id": "60069572"},
            )],
            pins,
            skipped,
            set(),
            [row],
            {},
            event_lookup_fn=lambda _eid: event,
            fixtures_fn=lambda *_a, **_k: [game],
        )
    assert skipped == []
    assert pins[0]["harvest_key"] == "60069572:line1"
    assert pins[0]["harvest_book"] == "prophetx"
