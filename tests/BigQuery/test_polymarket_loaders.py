"""Tests for the Polymarket bridge + token-resolution row builders — pure, no BQ/network.

Covers the behaviours that matter most:
  * bridge: position_id[i] <-> clob_token_id[i] <-> outcome[i] stay index-aligned;
    non-combinable and misaligned markets are dropped.
  * bridge universe: the combos-rfq-api catalog mixes past- and future-dated legs in
    no particular order (~half of a sample were already past-dated) with no
    server-side date filter -- filter_upcoming/_exclude_bridged are what guarantee
    every run's Gamma-enrichment budget goes to upcoming, not-yet-bridged legs
    instead of stale or already-covered ones.
  * token resolutions: settle prices are NOT binary — a normal [1,0] resolves
    WIN/LOSS, but a void/suspended/cancelled [0.5,0.5] resolves VOID_SPLIT (0.5, not
    a bool); open / out-of-window / ambiguous markets are skipped.
"""

from datetime import date

from BigQuery.load_polymarket_position_bridge import _exclude_bridged, filter_upcoming
from BigQuery.load_polymarket_position_bridge import build_rows as build_bridge_rows
from BigQuery.load_polymarket_token_resolutions import (
    _classify,
    is_decisively_settled,
)
from BigQuery.load_polymarket_token_resolutions import (
    build_rows as build_token_rows,
)
from fetch.polymarket_gamma import normalize_market

NOW = "2026-07-08T00:00:00+00:00"
SINCE = "2026-06-01T00:00:00Z"


# --- bridge (position_id <-> clob_token_id) ---


def _gamma_market(cid, pids, clobs, outcomes):
    """A normalized Gamma market as the bridge builder consumes it."""
    return {
        "condition_id": cid,
        "slug": "s-" + cid,
        "question": "Q " + cid,
        "position_ids": pids,
        "clob_token_ids": clobs,
        "outcomes": outcomes,
        "outcome_prices": [],
        "uma_resolution_statuses": [],
        "closed": False,
        "end_date": None,
        "game_start_time": "2026-08-06 01:40:00+00",
        "updated_at": None,
    }


def test_normalize_market_decodes_json_string_arrays():
    raw = {
        "conditionId": "0xA",
        "slug": "will-x",
        "question": "Will X?",
        "positionIds": '["100", "101"]',  # JSON-string-encoded
        "clobTokenIds": ["200", "201"],  # already a list
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["1", "0"]',
        "closed": True,
        "endDate": "2026-07-01T00:00:00Z",
        "gameStartTime": "2026-08-06 01:40:00+00",
    }
    m = normalize_market(raw)
    # Kickoff instant must survive normalization — it is the matcher's fixture key.
    assert m["game_start_time"] == "2026-08-06 01:40:00+00"
    assert m["position_ids"] == ["100", "101"]
    assert m["clob_token_ids"] == ["200", "201"]
    assert m["outcomes"] == ["Yes", "No"]
    assert m["outcome_prices"] == ["1", "0"]
    assert m["closed"] is True


def test_bridge_build_rows_alignment_and_skips():
    markets = [
        _gamma_market("0xA", ["p0", "p1"], ["c0", "c1"], ["Yes", "No"]),
        _gamma_market("0xNONE", [], [], []),  # non-combinable -> skip
        _gamma_market("0xBAD", ["p0", "p1"], ["c0"], ["Yes", "No"]),  # misaligned -> skip
    ]
    rows = build_bridge_rows(markets, NOW)
    by_pid = {r["position_id"]: r for r in rows}
    assert set(by_pid) == {"p0", "p1"}
    assert by_pid["p0"] == {
        "position_id": "p0",
        "clob_token_id": "c0",
        "condition_id": "0xA",
        "outcome_index": 0,
        "outcome_label": "Yes",
        "slug": "s-0xA",
        "question": "Q 0xA",
        "n_outcomes": 2,
        # Polymarket's own kickoff instant, carried so the matcher never has to
        # compare the slug's venue-local date against optic's UTC start_date.
        "game_start_time": "2026-08-06 01:40:00+00",
        "last_updated": NOW,
    }
    assert by_pid["p1"]["clob_token_id"] == "c1" and by_pid["p1"]["outcome_index"] == 1


# --- combo-leg universe filtering (upcoming + not-already-bridged) ---


def _combo_market(cid, slug):
    """A raw combos-rfq-api market, as filter_upcoming consumes it (pre-Gamma-enrichment)."""
    return {"condition_id": cid, "slug": slug, "position_ids": [], "outcomes": []}


def test_filter_upcoming_drops_past_dated_slugs():
    markets = [
        _combo_market("0xOLD", "mlb-bos-nyy-2026-06-06"),
        _combo_market("0xNEW", "mlb-lad-sf-2026-07-22"),
    ]
    kept, dropped = filter_upcoming(markets, min_date=date(2026, 7, 21))
    assert [m["condition_id"] for m in kept] == ["0xNEW"]
    assert dropped == 1


def test_filter_upcoming_keeps_exact_min_date():
    markets = [_combo_market("0xTODAY", "atp-zhou-pavlovi-2026-07-22")]
    kept, dropped = filter_upcoming(markets, min_date=date(2026, 7, 22))
    assert len(kept) == 1
    assert dropped == 0


def test_filter_upcoming_keeps_slugs_with_no_parseable_date():
    """Fail open: a slug we can't date must not be dropped just because we can't
    classify it -- silently dropping unknowns is exactly the bug (unsorted pagination
    truncation) that made the original coverage gap invisible."""
    markets = [_combo_market("0xMYSTERY", "some-weird-combo-slug")]
    kept, dropped = filter_upcoming(markets, min_date=date(2026, 7, 22))
    assert len(kept) == 1
    assert dropped == 0


def test_exclude_bridged_drops_already_mapped_condition_ids():
    kept, skipped = _exclude_bridged(["0xA", "0xB", "0xC"], {"0xB"})
    assert kept == ["0xA", "0xC"]
    assert skipped == 1


def test_exclude_bridged_noop_when_no_bridged_set():
    kept, skipped = _exclude_bridged(["0xA", "0xB"], None)
    assert kept == ["0xA", "0xB"]
    assert skipped == 0


# --- bridge fail-closed cross-checks (a mispaired position<->token flips the traded side) ---


def test_bridge_drops_market_when_optic_side_contradicts_outcome_label():
    """Tier 2: OpticOdds independently maps each clob_token_id to its over/under side.
    If that contradicts the Gamma outcome_label the token is paired with, Gamma's arrays
    are misordered -> emitting would flip the side. Fail closed: drop the whole market."""
    markets = [_gamma_market("0xF", ["p0", "p1"], ["c0", "c1"], ["Over", "Under"])]
    # Gamma paired c0<->Over, c1<->Under; optic ground truth says the opposite.
    optic_side_by_clob = {"c0": "under", "c1": "over"}
    rows = build_bridge_rows(markets, NOW, optic_side_by_clob=optic_side_by_clob)
    assert rows == []


def test_bridge_emits_when_optic_side_agrees_with_outcome_label():
    markets = [_gamma_market("0xOK", ["p0", "p1"], ["c0", "c1"], ["Over", "Under"])]
    optic_side_by_clob = {"c0": "over", "c1": "under"}
    rows = build_bridge_rows(markets, NOW, optic_side_by_clob=optic_side_by_clob)
    by_pid = {r["position_id"]: r for r in rows}
    assert set(by_pid) == {"p0", "p1"}
    assert by_pid["p0"]["clob_token_id"] == "c0" and by_pid["p0"]["outcome_label"] == "Over"


def test_bridge_not_dropped_when_optic_lacks_coverage():
    """Absence of an optic entry is a coverage gap, not a disagreement -> keep the row.
    (Legs with no optic mapping are never priced by the maker, so they can't flip.)"""
    markets = [_gamma_market("0xN", ["p0", "p1"], ["c0", "c1"], ["Over", "Under"])]
    rows = build_bridge_rows(markets, NOW, optic_side_by_clob={"cX": "over"})
    assert {r["position_id"] for r in rows} == {"p0", "p1"}


def test_bridge_drops_market_when_combos_outcome_disagrees():
    """Tier 1: combos-rfq-api is an INDEPENDENT source for position_id -> outcome.
    Disagreement with Gamma's outcome_label for a shared position_id -> fail closed."""
    markets = [_gamma_market("0xC", ["p0", "p1"], ["c0", "c1"], ["Over", "Under"])]
    combos_outcome_by_pid = {"p0": "Under", "p1": "Over"}
    rows = build_bridge_rows(markets, NOW, combos_outcome_by_pid=combos_outcome_by_pid)
    assert rows == []


def test_bridge_emits_when_combos_outcome_agrees_case_insensitive():
    markets = [_gamma_market("0xC2", ["p0", "p1"], ["c0", "c1"], ["Over", "Under"])]
    combos_outcome_by_pid = {"p0": "over", "p1": "UNDER"}  # label case must not matter
    rows = build_bridge_rows(markets, NOW, combos_outcome_by_pid=combos_outcome_by_pid)
    assert {r["position_id"] for r in rows} == {"p0", "p1"}


def test_bridge_cross_checks_skipped_when_maps_absent():
    """Backfill / uncovered legs: no maps => no cross-check, original behavior preserved."""
    markets = [_gamma_market("0xA", ["p0", "p1"], ["c0", "c1"], ["Over", "Under"])]
    rows = build_bridge_rows(markets, NOW)
    assert {r["position_id"] for r in rows} == {"p0", "p1"}


def test_bridge_norway_team_total_real_vectors_emit_correct_pairing():
    """The real Norway team_total leg (condition 0x2b284c): Over=token 11567.../position
    ...568, Under=93977.../...569. Agreeing combos + optic => emit the correct pairing."""
    over_pid = "573196889209517879766418006706147652448272567287474038410016011289853165568"
    under_pid = "573196889209517879766418006706147652448272567287474038410016011289853165569"
    over_clob = "11567424607224571241113011644989438727435889462957676113659658208725790226104"
    under_clob = "93977560133506035915203011382814763475199970490817347639993199275222576923305"
    markets = [
        _gamma_market(
            "0x2b284c", [over_pid, under_pid], [over_clob, under_clob], ["Over", "Under"]
        )
    ]
    rows = build_bridge_rows(
        markets,
        NOW,
        combos_outcome_by_pid={over_pid: "Over", under_pid: "Under"},
        optic_side_by_clob={over_clob: "over", under_clob: "under"},
    )
    by_pid = {r["position_id"]: r for r in rows}
    assert by_pid[over_pid]["clob_token_id"] == over_clob
    assert by_pid[over_pid]["outcome_label"] == "Over"
    assert by_pid[under_pid]["clob_token_id"] == under_clob
    assert by_pid[under_pid]["outcome_label"] == "Under"


# --- token resolutions ---


def _clob_market(cid, tokens, closed=True, end: str | None = "2026-07-01T00:00:00Z"):
    """A normalized CLOB market: tokens = list of (token_id, outcome, price)."""
    return {
        "condition_id": cid,
        "closed": closed,
        "end_date_iso": end,
        "is_50_50": False,
        "slug": "s-" + cid,
        "question": "Q " + cid,
        "tokens": [{"token_id": t, "outcome": o, "price": p, "winner": False} for (t, o, p) in tokens],
    }


def test_classify_boundaries():
    assert _classify(1.0) == "WIN"
    assert _classify(0.9999989) == "WIN"  # settled prices carry dust
    assert _classify(0.0) == "LOSS"
    assert _classify(0.005) == "LOSS"
    assert _classify(0.5) == "VOID_SPLIT"


def test_is_decisively_settled():
    assert is_decisively_settled([1.0, 0.0]) is True
    assert is_decisively_settled([0.9999989, 1.01e-6]) is True  # crisp binary w/ dust
    assert is_decisively_settled([0.5, 0.5]) is True  # clean void
    assert is_decisively_settled([0.58, 0.42]) is False  # ambiguous mid-prices
    assert is_decisively_settled([0.0, 0.0]) is False  # sum != 1 (invalid)
    assert is_decisively_settled([0.3, 0.7]) is False  # not crisp, not void


def test_token_resolution_win_loss():
    markets = [_clob_market("0xA", [("t0", "Yes", "1"), ("t1", "No", "0")])]
    rows = build_token_rows(markets, SINCE, NOW)
    r0 = next(r for r in rows if r["clob_token_id"] == "t0")
    r1 = next(r for r in rows if r["clob_token_id"] == "t1")
    assert r0["resolved_price"] == 1.0 and r0["resolution_type"] == "WIN" and r0["won"] is True
    assert r0["winning_outcome_index"] == 0 and r0["outcome_label"] == "Yes"
    assert r1["resolved_price"] == 0.0 and r1["resolution_type"] == "LOSS" and r1["won"] is False
    assert r1["winning_outcome_index"] == 0  # market's winning index, not the token's


def test_token_resolution_void_split():
    # Suspended player / cancelled match: settles 0.5/0.5.
    markets = [_clob_market("0xV", [("t0", "Yes", "0.5"), ("t1", "No", "0.5")])]
    rows = build_token_rows(markets, SINCE, NOW)
    assert len(rows) == 2
    for r in rows:
        assert r["resolved_price"] == 0.5
        assert r["resolution_type"] == "VOID_SPLIT"
        assert r["won"] is False
        assert r["winning_outcome_index"] is None
        assert r["all_outcome_prices"] == "[0.5, 0.5]"


def test_token_resolution_skips_open_ambiguous_out_of_window_and_null_end():
    markets = [
        _clob_market("0xOPEN", [("t0", "Yes", "1"), ("t1", "No", "0")], closed=False),
        _clob_market("0xAMB", [("t0", "Yes", "0.58"), ("t1", "No", "0.42")]),  # not decisive
        _clob_market("0xOLD", [("t0", "Yes", "1"), ("t1", "No", "0")], end="2026-01-01T00:00:00Z"),  # before window
        _clob_market("0xNULL", [("t0", "Yes", "1"), ("t1", "No", "0")], end=None),  # unplaceable
    ]
    assert build_token_rows(markets, SINCE, NOW) == []


def test_token_resolution_default_since_is_a_rolling_window():
    from datetime import UTC, datetime

    from BigQuery.load_polymarket_token_resolutions import DEFAULT_WINDOW_DAYS, default_since

    now = datetime(2026, 10, 15, 4, 30, 7, tzinfo=UTC)
    assert DEFAULT_WINDOW_DAYS == 30
    assert default_since(now) == "2026-09-15T04:30:07Z"
    # Same string shape as end_date_iso, so build_rows' string comparison still orders correctly.
    assert default_since(now) > "2026-09-15T00:00:00Z"


def test_token_resolution_load_without_since_uses_the_window_not_june(monkeypatch):
    """The nightly cron passes no --since; it must not re-sweep every token since June."""
    import BigQuery.load_polymarket_token_resolutions as mod

    seen: dict[str, str] = {}

    def fake_build_rows(markets, since_iso, now_iso):
        seen["since"] = since_iso
        return []

    monkeypatch.setattr(mod.clob, "iter_markets", lambda **_kw: iter(()))
    monkeypatch.setattr(mod, "build_rows", fake_build_rows)
    mod.load()
    assert seen["since"][:10] == mod.default_since(mod.datetime.now(mod.UTC))[:10]

    mod.load(since="2026-06-01T00:00:00Z")
    assert seen["since"] == "2026-06-01T00:00:00Z"
