"""Crypto league_not_wired → mapping_league onboard from RFQ demand."""

from __future__ import annotations

from unittest.mock import patch

from mappers.control_plane.gap_fix_crypto_onboard import try_crypto_league_onboard
from tests.control_plane.gap_store_helpers import _soccer_store


def test_crypto_onboard_drafts_league_when_optic_unique() -> None:
    store = _soccer_store()
    row = {
        "symbol": "NX.F.OPT.UNL-00002-260925-M.O.1.1.20261230",
        "catalogue": {
            "ok": True,
            "meta_name": "France @ Türkiye",
            "meta_event_date": "2026-09-25",
        },
    }
    pins: list[dict] = []
    skipped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    rule_set_id = store.current_rule_set_id
    assert rule_set_id
    rows = list(store.leagues_for(rule_set_id))
    with patch(
        "mappers.control_plane.gap_fix_crypto_onboard.discover_optic_league_id",
        return_value="uefa_-_nations_league",
    ):
        ok = try_crypto_league_onboard(
            store, row, pins, skipped, seen, rows, None, {},
        )
    assert ok is True
    assert len(pins) == 1
    assert pins[0]["league"] == "uefa_nations_league"
    assert pins[0]["harvest_book"] == "crypto"
