"""Gap harvest outcome ledger helpers."""

from __future__ import annotations

from mappers.control_plane.gap_fix_walk import ALIASES_COMPLETE, WALK_WITHOUT_OUTCOME
from mappers.control_plane.gap_inventory import RfqGapItem
from mappers.control_plane.gap_ledger import GapOutcome, build_outcomes, summarize_outcomes


def test_build_outcomes_classifies_pin_skip_and_not_walked() -> None:
    inventory = [
        RfqGapItem("crypto", "NX.F.OPT.UNL-1", 100),
        RfqGapItem("kalshi", "KXNEW-1", 50),
    ]
    pins = [{"harvest_book": "crypto", "harvest_key": "NX.F.OPT.UNL-1"}]
    skipped = [{"book": "kalshi", "key": "KXNEW-1", "reason": "league_not_wired"}]
    outcomes = build_outcomes(
        inventory, pins, skipped, walked_keys={("kalshi", "KXNEW-1")},
    )
    by_key = {(o.book, o.key): o.outcome for o in outcomes}
    assert by_key[("crypto", "NX.F.OPT.UNL-1")] == "pinned"
    assert by_key[("kalshi", "KXNEW-1")] == "needs_league"


def test_walked_without_skip_uses_walk_without_outcome_not_no_pin() -> None:
    inventory = [RfqGapItem("kalshi", "KXITF-1", 1)]
    outcomes = build_outcomes(inventory, [], [], walked_keys={("kalshi", "KXITF-1")})
    assert outcomes[0].outcome == "skipped"
    assert outcomes[0].reason == WALK_WITHOUT_OUTCOME
    assert outcomes[0].reason != "no_pin"


def test_reconcile_walked_skips_fills_gap_before_ledger() -> None:
    from mappers.control_plane.gap_fix_walk import reconcile_walked_skips

    walked = {("novig", "uuid-1")}
    skipped: list[dict[str, str]] = []
    reconcile_walked_skips(walked, [], skipped)
    assert skipped == [{"book": "novig", "key": "uuid-1", "reason": WALK_WITHOUT_OUTCOME}]


def test_folded_harvest_key_counts_as_pinned() -> None:
    inventory = [
        RfqGapItem("kalshi", "KX-A", 1),
        RfqGapItem("kalshi", "KX-B", 1),
    ]
    pins = [{
        "harvest_book": "kalshi",
        "harvest_key": "KX-A",
        "harvest_keys": ["KX-A", "KX-B"],
    }]
    outcomes = build_outcomes(inventory, pins, [], walked_keys={("kalshi", "KX-A"), ("kalshi", "KX-B")})
    assert {o.key: o.outcome for o in outcomes} == {"KX-A": "pinned", "KX-B": "pinned"}


def test_stamp_residual_and_out_of_scope_are_expected() -> None:
    inventory = [
        RfqGapItem("polymarket", "nfl", 1),
        RfqGapItem("polymarket", "mlb", 1),
        RfqGapItem("kalshi", "KXBTC15M-1", 1),
    ]
    skipped = [
        {"book": "polymarket", "key": "nfl", "reason": "prefix_satisfied"},
        {"book": "polymarket", "key": "mlb", "reason": "stamp_residual"},
        {"book": "kalshi", "key": "KXBTC15M-1", "reason": "out_of_scope"},
    ]
    outcomes = build_outcomes(inventory, [], skipped, walked_keys={
        ("polymarket", "nfl"), ("polymarket", "mlb"), ("kalshi", "KXBTC15M-1"),
    })
    assert {o.key: o.outcome for o in outcomes} == {
        "nfl": "expected_residual",
        "mlb": "expected_residual",
        "KXBTC15M-1": "expected_residual",
    }


def test_ensure_walk_recorded_ignores_a_different_key() -> None:
    from mappers.control_plane.gap_fix_walk import ensure_walk_recorded

    pins = [{"harvest_book": "kalshi", "harvest_key": "KX-OTHER"}]
    skipped: list[dict[str, str]] = []
    ensure_walk_recorded("kalshi", "KX-THIS", pins, skipped, 0, 0, row={"kind": "title_miss"})
    assert skipped == [{"book": "kalshi", "key": "KX-THIS", "reason": "title_miss"}]


def test_ensure_walk_recorded_when_collect_is_silent() -> None:
    from mappers.control_plane.gap_fix_walk import ensure_walk_recorded

    pins: list[dict[str, object]] = []
    skipped: list[dict[str, str]] = []
    row = {"kind": "", "event_ticker": "KXTEST-1"}
    ensure_walk_recorded("kalshi", "KXTEST-1", pins, skipped, 0, 0, row=row)
    assert skipped == [{"book": "kalshi", "key": "KXTEST-1", "reason": ALIASES_COMPLETE}]


def test_summarize_outcomes_counts() -> None:
    text = summarize_outcomes([
        GapOutcome("crypto", "a", 1, "pinned"),
        GapOutcome("crypto", "b", 2, "pinned"),
    ])
    assert "pinned=2" in text
