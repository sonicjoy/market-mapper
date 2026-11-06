"""The SX Bet AI-validation spec: dormant by default, the flipped taker outcome, its SQL."""

from __future__ import annotations

import importlib

import pytest

from BigQuery.ai_validation_exchanges import sx_bet


def _row(suffix: str) -> dict:
    return {"src_selection_id": f"0xabc|{suffix}", "sx_outcome_one": "Over 2.5", "sx_outcome_two": "Under 2.5",
            "sx_type": "2", "sx_line": "2.5", "sx_team_one": "SV Werder Bremen", "sx_team_two": "SC Paderborn 07"}


def test_the_maker_suffix_picks_the_takers_outcome() -> None:
    assert sx_bet.taker_outcome(_row("two")) == ("Over 2.5", "Under 2.5")
    assert sx_bet.taker_outcome(_row("one")) == ("Under 2.5", "Over 2.5")
    assert sx_bet.taker_outcome({"src_selection_id": "0xabc"}) == (None, None)


def test_line_and_text() -> None:
    line = sx_bet.SPEC.line(_row("one"))
    assert "sel='Under 2.5'" in line and "other='Over 2.5'" in line
    assert "type='Under/Over'" in line and "line=2.5" in line
    assert sx_bet.SPEC.has_text(_row("two"))
    assert not sx_bet.SPEC.has_text({"src_selection_id": "0xabc|two"})
    assert sx_bet.SPEC.text(_row("two")) == "Over 2.5 / other: Under 2.5"


def test_cte_reads_the_newest_snapshot_of_sxbet_fetch_raw() -> None:
    sql = sx_bet.SPEC.render_cte("rs-marketmaking")
    assert "`rs-marketmaking.raw_ingestion_us.sxbet_fetch_raw`" in sql
    assert "INTERVAL 1 DAY" in sql and "snapshot_id >=" in sql
    assert "m.sportsbook = 'SX Bet'" in sx_bet.SPEC.join_sql


@pytest.mark.parametrize(("flag", "registered"), [(None, False), ("1", True)])
def test_registered_only_when_switched_on(monkeypatch: pytest.MonkeyPatch, flag, registered: bool) -> None:
    import BigQuery.ai_validation_exchanges as registry

    if flag is None:
        monkeypatch.delenv("AI_VALIDATION_SXBET", raising=False)
    else:
        monkeypatch.setenv("AI_VALIDATION_SXBET", flag)
    try:
        reloaded = importlib.reload(registry)
        assert ("SX Bet" in reloaded.sportsbooks()) is registered
    finally:
        monkeypatch.delenv("AI_VALIDATION_SXBET", raising=False)
        importlib.reload(registry)
