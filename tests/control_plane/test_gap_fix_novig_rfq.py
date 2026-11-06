"""Novig RFQ inventory ledger skips."""

from __future__ import annotations

from mappers.control_plane.gap_fix_novig_rfq import harvest_novig_rfq_inventory
from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.gap_inventory_league import _NOVIG_FRESH, _NOVIG_SQL


def test_novig_lookup_reads_the_optic_entity_id() -> None:
    assert "$.competitor.opticOddsId" in _NOVIG_SQL
    assert "$.player.opticOddsId" in _NOVIG_SQL
    assert "as market_type" in _NOVIG_SQL


def test_novig_snapshot_reads_repeat_the_pick_bound_so_they_prune() -> None:
    sql = _NOVIG_SQL.format(project="proj")
    assert "`proj.raw_ingestion_us.novig_raw`" in sql
    assert sql.count(_NOVIG_FRESH) == 3
    assert sql.count(f"r.{_NOVIG_FRESH}") == 2
    assert sql.count("r.insert_time = snap.s") == 2


def test_novig_inventory_records_needs_probe() -> None:
    skipped: list[dict[str, str]] = []
    harvest_novig_rfq_inventory(
        [RfqGapItem("novig", "uuid-market-ticker", 12)],
        skipped,
    )
    assert skipped == [{"book": "novig", "key": "uuid-market-ticker", "reason": "needs_probe"}]
