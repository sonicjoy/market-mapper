"""Harvest walk: key-derived skips, eight-key windows, one mapping read."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mappers.control_plane.gap_fix_preprobe import try_crypto_offline_probe
from mappers.control_plane.gap_fix_slots import PinSlots, fill_crypto_slots
from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.gap_ledger import (
    HORIZON_OUTCOME,
    TERMINAL_OUTCOMES,
    build_outcomes,
    ledger_inventory_sql_suffix,
)
from mappers.control_plane.rows import LeagueRow
from tests.control_plane.gap_store_helpers import _fixtures, _store

_AUG_1 = datetime(2026, 8, 1, tzinfo=UTC)
_UNWIRED = [f"NX.F.OPT.ZZZ-0000{n}-260830-M.O.1.1" for n in range(3)]
_FAR = "NX.F.OPT.UFC-00011-261231-M.O.1.1.20261231"
_UFC = "NX.F.OPT.UFC-00011-260822-M.O.1.1.20260822"


def _unseen_catalogue(symbol: str) -> dict[str, Any]:
    return {"ok": True, "seen": False, "symbol": symbol}


def _crypto_store(optic: str = "ufc") -> Any:
    league = LeagueRow(
        league="ufc",
        sport="mma",
        optic_league_id=optic,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=168.0,
        enabled=True,
        output_order=[],
        exchanges=[{
            "sportsbook": "crypto.com",
            "enabled": True,
            "parser_profile": "crypto_generic_v1",
            "source_league_id": "UFC",
            "settings": {"league": "UFC", "sport_grouping": "MMA"},
        }],
    )
    return _store([], [league])


def test_crypto_unwired_token_goes_live_for_league_onboarding() -> None:
    fifa = "NX.F.OPT.FIFA-00001-260803-M.O.1.1"
    assert try_crypto_offline_probe(_crypto_store(), fifa, now=_AUG_1) is None


def test_crypto_league_without_optic_retires_the_sport() -> None:
    row = try_crypto_offline_probe(_crypto_store(optic=""), _UFC, now=_AUG_1)
    assert row is not None
    assert row["kind"] == "missing_optic"
    assert row["offline_dead"] is True


def test_crypto_far_kickoff_waits_and_close_kickoff_goes_live() -> None:
    row = try_crypto_offline_probe(_crypto_store(), _UFC, now=_AUG_1)
    assert row is not None
    assert row["kind"] == "outside_horizon"
    assert row["offline_dead"] is False
    close = "NX.F.OPT.UFC-00011-260803-M.O.1.1.20260803"
    assert try_crypto_offline_probe(_crypto_store(), close, now=_AUG_1) is None


def test_drain_walks_every_key_and_ignores_dead_bucket_ttl(monkeypatch: Any) -> None:
    """Drain keys each need a ledger outcome, so no series skip and no 24h TTL."""

    def no_ttl(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("drain must not touch the dead-bucket TTL")

    monkeypatch.setattr("mappers.control_plane.gap_fix_slots.load_dead_buckets", no_ttl)
    monkeypatch.setattr("mappers.control_plane.gap_fix_slots.save_dead_buckets", no_ttl)
    walked: set[tuple[str, str]] = set()
    _pins, _skipped = fill_crypto_slots(
        _crypto_store(), list(_UNWIRED), _unseen_catalogue, _fixtures,
        PinSlots(limit=10), walked=walked, drain=True,
    )
    assert walked == {("crypto", key) for key in _UNWIRED}


def test_yield_stops_between_keys_inside_a_window() -> None:
    calls = {"n": 0}

    def yield_fn() -> bool:
        calls["n"] += 1
        return calls["n"] >= 3

    walked: set[tuple[str, str]] = set()
    fill_crypto_slots(
        _crypto_store(), list(_UNWIRED), _unseen_catalogue, _fixtures, PinSlots(limit=10),
        yield_fn=yield_fn, walked=walked,
    )
    assert walked == {("crypto", _UNWIRED[0])}


def test_horizon_wait_is_a_timed_exclusion_not_terminal() -> None:
    item = RfqGapItem("crypto", _FAR, 5)
    skipped = [{"book": "crypto", "key": _FAR, "reason": "outside_horizon"}]
    [outcome] = build_outcomes([item], [], skipped, walked_keys={("crypto", _FAR)})
    assert outcome.outcome == HORIZON_OUTCOME
    assert HORIZON_OUTCOME not in TERMINAL_OUTCOMES
    cte, _predicate = ledger_inventory_sql_suffix(project="p", enabled=True)
    assert f"l.outcome = '{HORIZON_OUTCOME}'" in cte
    assert "interval 24 hour" in cte
