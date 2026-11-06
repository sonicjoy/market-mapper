"""Override lane: crypto.com / Polymarket (USA) overrides into market_mapping stage rows (no BQ)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from BigQuery import override_lane as lane
from BigQuery.load_mappings import KEY_COLUMNS, _row_merge_key

COLUMNS = {
    *KEY_COLUMNS,
    "game_id",
    "fixture_id",
    "market_id",
    "selection",
    "selection_line",
    "points",
    "grouping_key",
    "source_ids",
    "last_updated",
    "market_match_method",
    "fixture_match_method",
    "verify_tier",
    "mapping_audit_event_id",
    "mapped_at",
}


def _row(book: str, selection: str, side: str, source_ids: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "sport": "soccer",
        "league": "uefa_nations_league",
        "start_date": "2026-09-27T18:45:00+00:00",
        "home": "MNE",
        "away": "CYP",
        "market_type": "moneyline_3way",
        "entity": None,
        "line": None,
        "side": side,
        "group_key": None,
        "sportsbook": book,
        "game_id": "30547-41571-2026-09-27",
        "fixture_id": "FX1",
        "market_id": "moneyline",
        "selection": selection,
        "selection_line": "",
        "points": 0.0,
        "grouping_key": "default",
        "source_ids": source_ids,
        "last_updated": "2026-09-26T00:00:00+00:00",
        **extra,
    }


def _batch() -> list[dict[str, Any]]:
    return [
        _row("DraftKings", "Montenegro", "MNE", {"id": "dk1"}),
        _row("DraftKings", "Cyprus", "CYP", {"id": "dk2"}),
        _row("DraftKings", "Draw", "_TIE", {"id": "dk3"}),
        # Mapper put symbol .1.1 on the WRONG selection (Draw).
        _row("crypto.com", "Draw", "_TIE", {"security_id": "SEC1", "symbol": "NX.F.OPT.UNL-8-260927-M.O.1.1"}),
        _row("Polymarket (USA)", "Montenegro", "MNE", {"market_id": "asc-unl-mne-cyp"}),
        _row("Polymarket (USA)", "Cyprus", "CYP", {"market_id": "asc-unl-mne-cyp"}),
    ]


def _ov(book: str, key: str, selection: str, *, side: str = "", when: int = 1) -> lane.LaneOverride:
    return lane.LaneOverride(
        sportsbook=book,
        venue_key=key,
        side=side,
        game_id="30547-41571-2026-09-27",
        market_id="moneyline",
        selection=selection,
        selection_line="",
        points=0.0,
        message_id=f"m{when}",
        publish_time=f"2026-09-26T0{when}:00:00+00:00",
    )


class _NoQueryClient:
    def query(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("lane OFF must not query BigQuery")


def test_lane_off_returns_rows_untouched_and_never_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(lane.LANE_ENV, raising=False)
    rows = _batch()
    out, report = lane.stage_override_lane(_NoQueryClient(), rows, COLUMNS)
    assert out is rows
    assert report is None
    ran: list[str] = []
    lane.supersede_override_rows(
        _NoQueryClient(), None, table="t", stage_table="s", cutoff="2026-01-01", run_dml=lambda _c, sql: ran.append(sql)
    )
    assert ran == []


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_lane_enabled_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(lane.LANE_ENV, value)
    assert lane.lane_enabled()
    monkeypatch.setenv(lane.LANE_ENV, "0")
    assert not lane.lane_enabled()


def test_parse_override_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(lane.LANE_ENV, "1")
    monkeypatch.setenv(lane.LANE_POLYUSA_ENV, "1")
    crypto = lane.parse_override(
        {
            "sportsbook": "crypto.com",
            "source_ids_json": json.dumps(json.dumps({"symbol": "NX.F.OPT.A"})),
            "publish_time": datetime(2026, 9, 26, tzinfo=UTC),
            "points": None,
        }
    )
    assert crypto is not None and crypto.venue_key == "NX.F.OPT.A" and crypto.points == 0.0
    usa = lane.parse_override(
        {"sportsbook": "Polymarket (USA)", "source_ids_json": '{"market_id": "asc-x", "selection_id": "YES"}'}
    )
    assert usa is not None and (usa.venue_key, usa.side) == ("asc-x", "yes")
    assert lane.parse_override({"sportsbook": "Kalshi", "source_ids_json": '{"market_id": "KX"}'}) is None
    assert lane.parse_override({"sportsbook": "crypto.com", "source_ids_json": '{"market_id": "x"}'}) is None


def test_crypto_override_replaces_wrong_mapper_row() -> None:
    sym = "NX.F.OPT.UNL-8-260927-M.O.1.1"
    out, report = lane.apply_override_lane(_batch(), [_ov("crypto.com", sym, "Cyprus")], COLUMNS)
    crypto = [r for r in out if r["sportsbook"] == "crypto.com"]
    assert len(crypto) == 1
    row = crypto[0]
    assert (row["selection"], row["side"], row["fixture_id"]) == ("Cyprus", "CYP", "FX1")
    assert row["source_ids"] == {"security_id": "SEC1", "symbol": sym}
    assert row["market_match_method"] == "override"
    assert row["mapping_audit_event_id"] == "m1"
    assert report.replaced == 1
    assert report.resolved == {"crypto.com": {sym}}


def test_override_row_keeps_crypto_cleanup_key() -> None:
    """_clean_stale_crypto_symbols keeps table rows whose (game_id, start_date, symbol) is staged."""
    sym = "NX.F.OPT.NEW"
    out, _ = lane.apply_override_lane(_batch(), [_ov("crypto.com", sym, "Montenegro")], COLUMNS)
    staged = {
        (r["game_id"], r["start_date"], r["source_ids"].get("symbol")) for r in out if r["sportsbook"] == "crypto.com"
    }
    assert ("30547-41571-2026-09-27", "2026-09-27T18:45:00+00:00", sym) in staged


def test_unresolved_override_writes_nothing() -> None:
    other = lane.LaneOverride(**{**_ov("crypto.com", "NX.F.OPT.Z", "Cyprus").__dict__, "game_id": "not-in-batch"})
    rows = _batch()
    out, report = lane.apply_override_lane(rows, [other], COLUMNS)
    assert out == rows
    assert report.unresolved == ["crypto.com|NX.F.OPT.Z|"]
    assert report.active == {"crypto.com": {"NX.F.OPT.Z"}}
    assert report.resolved == {}


def test_usa_override_defines_the_symbol_and_keeps_merge_keys_unique() -> None:
    sym = "asc-unl-mne-cyp"
    ovs = [
        _ov("Polymarket (USA)", sym, "Cyprus", side="yes", when=1),
        _ov("Polymarket (USA)", sym, "Montenegro", side="no", when=2),
    ]
    out, report = lane.apply_override_lane(_batch(), ovs, COLUMNS)
    usa = sorted((r["selection"], r["verify_tier"]) for r in out if r["sportsbook"] == "Polymarket (USA)")
    assert usa == [("Cyprus", "override"), ("Montenegro", "override")]
    assert report.replaced == 2
    keys = [_row_merge_key(r) for r in out]
    assert len(keys) == len(set(keys))


def test_usa_override_replaces_other_symbol_on_same_canonical_key() -> None:
    rows = _batch() + [_row("Polymarket (USA)", "Draw", "_TIE", {"market_id": "old-draw-ticker"})]
    out, _ = lane.apply_override_lane(rows, [_ov("Polymarket (USA)", "new-draw-ticker", "Draw", side="yes")], COLUMNS)
    draws = [r["source_ids"] for r in out if r["sportsbook"] == "Polymarket (USA)" and r["side"] == "_TIE"]
    assert draws == [{"market_id": "new-draw-ticker", "selection_id": "yes"}]


def test_usa_override_of_one_side_keeps_the_mapper_row_of_the_other() -> None:
    """A US symbol is two selections: overriding the YES must not reap the NO."""
    sym = "asc-unl-mne-cyp"
    rows = [
        r for r in _batch() if r["sportsbook"] != "Polymarket (USA)"
    ] + [
        _row("Polymarket (USA)", "Montenegro", "MNE", {"market_id": sym, "selection_id": "yes"}),
        _row("Polymarket (USA)", "Cyprus", "CYP", {"market_id": sym, "selection_id": "no"}),
    ]
    out, report = lane.apply_override_lane(
        rows, [_ov("Polymarket (USA)", sym, "Montenegro", side="yes")], COLUMNS)
    usa = sorted(
        (r["selection"], r["source_ids"]["selection_id"], r.get("verify_tier"))
        for r in out if r["sportsbook"] == "Polymarket (USA)"
    )
    assert usa == [("Cyprus", "no", None), ("Montenegro", "yes", "override")]
    assert report.replaced == 1


def test_provenance_only_for_present_columns() -> None:
    out, _ = lane.apply_override_lane(_batch(), [_ov("crypto.com", "NX.F.OPT.N", "Draw")], {*KEY_COLUMNS})
    row = next(r for r in out if r["source_ids"].get("symbol") == "NX.F.OPT.N")
    assert "market_match_method" not in row


def test_supersede_sql_scopes_and_escapes() -> None:
    report = lane.LaneReport(
        active={"crypto.com": {"NX.A", "NX'B"}},
        resolved={"crypto.com": {"NX.A"}},
    )
    sql = lane.supersede_sql(
        report, table="markets_us.market_mapping", stage_table="markets_us.stage", cutoff="2026-07-01"
    )
    assert "t.start_date >= TIMESTAMP('2026-07-01')" in sql
    assert "JSON_VALUE(t.source_ids, '$.symbol') IN ('NX.A')" in sql
    assert "NOT JSON_VALUE(t.source_ids, '$.symbol') IN ('NX''B', 'NX.A')" in sql
    assert "SELECT DISTINCT game_id FROM markets_us.stage" in sql
    # Polymarket (USA) has no overrides: its replace branch is FALSE, stale branch still reaps.
    assert "t.sportsbook = 'Polymarket (USA)' AND (FALSE OR" in sql
    assert "NOT FALSE" in sql


def test_stage_lane_on_uses_sink_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(lane.LANE_ENV, "1")
    sink = {
        "sportsbook": "crypto.com",
        "source_ids_json": '{"symbol": "NX.F.OPT.UNL-8-260927-M.O.1.1"}',
        "game_id": "30547-41571-2026-09-27",
        "market_id": "moneyline",
        "selection": "Montenegro",
        "selection_line": "",
        "points": 0.0,
        "message_id": "m9",
        "publish_time": "2026-09-26T09:00:00+00:00",
    }

    class _Row(dict):
        pass

    class _Client:
        def query(self, sql: str) -> Any:
            assert "mapping_override" in sql
            return type("J", (), {"result": lambda _self: [_Row(sink)]})()

    out, report = lane.stage_override_lane(_Client(), _batch(), COLUMNS)
    assert report is not None and report.resolved == {"crypto.com": {"NX.F.OPT.UNL-8-260927-M.O.1.1"}}
    assert [r["selection"] for r in out if r["sportsbook"] == "crypto.com"] == ["Montenegro"]
    ran: list[str] = []
    lane.supersede_override_rows(
        _Client(), report, table="t", stage_table="s", cutoff="2026-07-01", run_dml=lambda _c, sql: ran.append(sql)
    )
    assert len(ran) == 1 and "DELETE FROM t t" in ran[0]


def test_polymarket_usa_needs_its_own_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    usa_raw = {"sportsbook": "Polymarket (USA)", "source_ids_json": '{"market_id": "asc-x", "selection_id": "yes"}'}
    crypto_raw = {"sportsbook": "crypto.com", "source_ids_json": '{"symbol": "NX.F.OPT.A"}'}
    monkeypatch.delenv(lane.LANE_POLYUSA_ENV, raising=False)
    monkeypatch.setenv(lane.LANE_ENV, "1")
    assert lane.lane_sportsbooks() == (lane.CRYPTO,)
    assert lane.parse_override(usa_raw) is None
    assert lane.parse_override(crypto_raw) is not None
    monkeypatch.setenv(lane.LANE_POLYUSA_ENV, "1")
    assert lane.parse_override(usa_raw) is not None
    monkeypatch.setenv(lane.LANE_ENV, "0")
    assert lane.lane_sportsbooks() == ()
