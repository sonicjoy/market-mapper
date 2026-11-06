"""Explore → Venue gaps: catalogue rollup, league status, node Why / stage (no BQ)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mappers.control_plane import gap_optic_census
from mappers.control_plane.console_unmapped_fixes import summarize_mappable_items
from mappers.control_plane.console_venue_gaps import (
    NO_LEAGUE,
    build_venue_gap_tree,
    get_venue_gap_fixture,
    list_venue_gaps,
    rollup_rows,
)
from mappers.control_plane.console_venue_gaps_fix import (
    _split_blind,
    leg_rows,
    stage_venue_gap_node,
    why_venue_gap_node,
)
from mappers.control_plane.console_venue_gaps_league import crypto_league_index, league_status
from mappers.control_plane.console_venue_gaps_sql import CATALOG_SQL, DEMAND_SQL
from mappers.control_plane.http_console_venue_gaps import register_venue_gap_routes
from mappers.control_plane.league_cfg_memo import effective_league_cfg, league_cfg_memo
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.store import InMemoryStore

if TYPE_CHECKING:
    from mappers.control_plane.service import ProposalService

_CRYPTO_NFL = {
    "sportsbook": "crypto.com",
    "enabled": True,
    "parser_profile": "crypto_generic_v1",
    "source_league_id": "NFL",
    "settings": {"league": "NFL", "sport_grouping": "NFL", "period_type": "Full Game"},
}


def _league(slug: str, exchanges: list[dict[str, Any]], *, sport: str = "football") -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport=sport,
        optic_league_id=slug,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=exchanges,
    )


def _store(leagues: list[LeagueRow], entities: list[EntityRow] | None = None) -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_venue_gaps",
        entities=entities or [],
        leagues=leagues,
        market_rules=[],
        activate=True,
    )
    return store


def _nfl_store(entities: list[EntityRow] | None = None) -> InMemoryStore:
    return _store([_league("nfl", [dict(_CRYPTO_NFL)])], entities)


def _rollup(meta: str, key: str, hours: float, total: int, mapped: int, **extra: Any) -> dict[str, Any]:
    return {
        "meta_league": meta,
        "sport_grouping": extra.get("grouping", meta),
        "fixture_key": key,
        "fixture_name": extra.get("name", key),
        "start_at": datetime.now(UTC) + timedelta(hours=hours),
        "total": total,
        "mapped": mapped,
        "demand": extra.get("demand", 0),
    }


# ---- rollup tree ---------------------------------------------------------------------------


def test_tree_groups_by_league_and_marks_tip_status() -> None:
    rows = [
        _rollup("NFL", "NX.F.OPT.NFL-00001-260927", 30, 100, 80, demand=5),
        _rollup("NFL", "NX.F.OPT.NFL-00002-260927", 40, 50, 50),
        _rollup("EPL", "NX.F.OPT.EPL-00001-260927", 30, 10, 0, grouping="SOCCER"),
    ]
    leagues = build_venue_gap_tree(rows, _nfl_store(), phase="pre")
    by_meta = {league["meta_league"]: league for league in leagues}
    assert by_meta["NFL"]["tip"]["status"] == "in_tip"
    assert by_meta["NFL"]["tip"]["league"] == "nfl"
    assert (by_meta["NFL"]["total"], by_meta["NFL"]["mapped"], by_meta["NFL"]["demand"]) == (150, 130, 5)
    assert by_meta["EPL"]["tip"]["status"] == "not_in_tip"
    assert by_meta["EPL"]["tip"]["fix"]["action"] == "create"
    # Biggest gap first.
    assert [league["meta_league"] for league in leagues] == ["NFL", "EPL"]


def test_tree_phase_and_search_filters() -> None:
    rows = [
        _rollup("NFL", "live-fx", -1, 10, 0, name="Jets @ Bills"),
        _rollup("NFL", "pre-fx", 30, 10, 0, name="Chiefs @ Dolphins"),
    ]
    live = build_venue_gap_tree(rows, _nfl_store(), phase="live")
    assert [fx["fixture_key"] for fx in live[0]["fixtures"]] == ["live-fx"]
    pre = build_venue_gap_tree(rows, _nfl_store(), phase="pre", q="chiefs")
    assert [fx["fixture_key"] for fx in pre[0]["fixtures"]] == ["pre-fx"]
    assert build_venue_gap_tree(rows, _nfl_store(), phase="pre", q="nothing-matches") == []


def test_tree_no_league_offers_no_fix() -> None:
    leagues = build_venue_gap_tree([_rollup("", "x|y", 30, 3, 0)], _nfl_store(), phase="pre")
    assert leagues[0]["meta_league"] == NO_LEAGUE
    assert leagues[0]["tip"]["fix"] is None


def _cat(symbol: str, fixture_key: str, mapped: bool, *, hours: float = 30, meta: str = "NFL") -> dict[str, Any]:
    return {
        "symbol": symbol,
        "meta_league": meta,
        "sport_grouping": meta,
        "fixture_key": fixture_key,
        "fixture_name": fixture_key,
        "event_at": datetime.now(UTC) + timedelta(hours=hours),
        "is_mapped": mapped,
    }


def _catalogue_fn(rows: list[dict[str, Any]], demand: dict[str, int], calls: list[str] | None = None) -> Any:
    def fake(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        if calls is not None:
            calls.append(sql)
        if sql == CATALOG_SQL:
            return rows
        assert sql == DEMAND_SQL
        return [{"symbol": sym, "demand": n} for sym, n in demand.items()]

    return fake


def test_list_venue_gaps_totals_and_errors() -> None:
    rows = [_cat(f"a{i}", "a", True) for i in range(10)] + [_cat(f"b{i}", "b", False) for i in range(5)]
    calls: list[str] = []
    out = list_venue_gaps(phase="pre", store=_nfl_store(), query_fn=_catalogue_fn(rows, {"b1": 4}, calls))
    assert calls == [CATALOG_SQL, DEMAND_SQL]
    assert out["error"] is None
    assert out["totals"]["selections"] == 15
    assert out["totals"]["fixtures_unmapped"] == 1
    fixtures = {fx["fixture_key"]: fx for fx in out["leagues"][0]["fixtures"]}
    assert (fixtures["b"]["total"], fixtures["b"]["mapped"], fixtures["b"]["demand"]) == (5, 0, 4)

    def boom(_sql: str, _params: dict[str, Any]) -> list[dict[str, Any]]:
        raise RuntimeError("bq down")

    assert list_venue_gaps(store=_nfl_store(), query_fn=boom)["error"] == "bq down"
    assert "crypto only" in list_venue_gaps(platform="kalshi")["error"]


def test_rollup_rows_keeps_earliest_start() -> None:
    early = _cat("x1", "fx", False, hours=5)
    late = _cat("x2", "fx", True, hours=9)
    (row,) = rollup_rows([late, early], {"x1": 2, "x2": 1})
    assert row["start_at"] == early["event_at"]
    assert (row["total"], row["mapped"], row["demand"]) == (2, 1, 3)


def test_catalog_and_demand_sql_render() -> None:
    sql = CATALOG_SQL.format(project="p")
    assert "[0-9]{6}" in sql
    assert "`p.processed_upstream_us.crypto_underlying_securities`" in sql
    demand = DEMAND_SQL.format(project="p")
    assert demand.startswith("with ") and "status = 'failed'" in demand
    assert "interval 51 hour" in demand  # 48h demand window + publish lag


# ---- fixture drill-down --------------------------------------------------------------------


def _sel(symbol: str, market_id: str, contract: str, **extra: Any) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "meta_league": "NFL",
        "sport_grouping": "NFL",
        "fixture_name": "Chiefs @ Dolphins",
        "market_id": market_id,
        "market_group": extra.get("group", "Game Line"),
        "contract_type": contract,
        "period_type": extra.get("period", "Full-Game"),
        "outcome": extra.get("outcome", symbol),
        "participant": extra.get("participant"),
        "is_mapped": extra.get("mapped", False),
        "fixture_key": extra.get("fixture_key", "NX.F.OPT.NFL-00001-260927"),
    }


def test_fixture_groups_markets_with_period_and_player_labels() -> None:
    rows = [
        _sel("s1", "m1", "Moneyline", mapped=True),
        _sel("s2", "m1", "Moneyline"),
        _sel("s3", "m2", "Moneyline", period="1st Half"),
        _sel("s4", "m3", "Total Receiving Yards", group="Player Prop", participant="Tyreek Hill"),
        _sel("other", "m9", "Moneyline", fixture_key="NX.F.OPT.NFL-00002-260927"),
    ]
    out = get_venue_gap_fixture(
        fixture_key="NX.F.OPT.NFL-00001-260927",
        store=_nfl_store(),
        query_fn=_catalogue_fn(rows, {"s2": 2}),
    )
    assert "m9" not in {m["market_id"] for m in out["markets"]}
    assert out["league"] == "nfl"
    labels = {m["market_id"]: m["label"] for m in out["markets"]}
    assert labels == {
        "m1": "Moneyline",
        "m2": "Moneyline · 1st Half",
        "m3": "Tyreek Hill · Total Receiving Yards",
    }
    m1 = next(m for m in out["markets"] if m["market_id"] == "m1")
    assert (m1["total"], m1["mapped"], m1["unmapped"], m1["demand"]) == (2, 1, 1, 2)


# ---- league status / Editor prefill --------------------------------------------------------


def test_league_status_disabled_pin_amends_and_enables() -> None:
    off = {**_CRYPTO_NFL, "enabled": False}
    store = _store([_league("nfl", [{"sportsbook": "kalshi", "source_league_id": "KXNFL"}, off])])
    status = league_status("NFL", "NFL", crypto_league_index(store))
    assert status["status"] == "disabled"
    state = status["fix"]["entry_state"]
    assert (state["tab"], state["mode"], state["league"]) == ("league", "amend", "nfl")
    crypto = [ex for ex in state["exchanges"] if ex["sportsbook"] == "crypto.com"]
    assert len(crypto) == 1 and crypto[0]["enabled"] is True
    assert crypto[0]["settings"]["period_type"] == "Full Game"
    assert any(ex["sportsbook"] == "kalshi" for ex in state["exchanges"])


def test_league_status_name_match_adds_crypto_pin() -> None:
    store = _store([_league("epl", [{"sportsbook": "kalshi", "source_league_id": "KXEPL"}], sport="soccer")])
    status = league_status("EPL", "SOCCER", crypto_league_index(store))
    assert status["status"] == "not_in_tip"
    state = status["fix"]["entry_state"]
    assert state["mode"] == "amend" and state["league"] == "epl"
    crypto = next(ex for ex in state["exchanges"] if ex["sportsbook"] == "crypto.com")
    assert crypto["settings"] == {"league": "EPL", "sport_grouping": "SOCCER"}
    assert crypto["parser_profile"] == "crypto_generic_v1"


def test_league_status_unknown_league_creates() -> None:
    status = league_status("UEFA", "SOCCER", crypto_league_index(_nfl_store()))
    assert status["status"] == "not_in_tip"
    assert status["fix"]["action"] == "create"
    state = status["fix"]["entry_state"]
    assert state["mode"] == "create" and state["sport"] == "soccer"
    assert state["exchanges"][0]["source_league_id"] == "UEFA"


# ---- node Why / stage ---------------------------------------------------------------------


def _catalogue(_syms: Any) -> dict[str, dict[str, Any]]:
    return {
        "NX.F.OPT.NFL-00001-260927-M.O.1.1": {
            "home_id": "16",
            "home_name": "Miami Dolphins",
            "away_id": "19",
            "away_name": "Kansas City Chiefs",
        }
    }


def _node_row(**extra: Any) -> dict[str, Any]:
    return {
        "key": "NX.F.OPT.NFL-00001-260927-M.O.1.1",
        "description": "Kansas City Chiefs",
        "league": "nfl",
        "fixture": "Chiefs @ Dolphins",
        "sport": "football",
        "contract_type": "Moneyline",
        "market_group": "Game Line",
        **extra,
    }


def test_leg_rows_carry_real_crypto_ids_and_names() -> None:
    legs = leg_rows([_node_row(), {"key": ""}], _nfl_store(), catalogue_fn=_catalogue)
    assert len(legs) == 1
    assert legs[0]["crypto_ids"] == ["16", "19"]
    assert legs[0]["crypto_names"]["19"] == "Kansas City Chiefs"


def test_why_node_names_aliases_and_drops_symbol_fallback(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.gap_market_bind.cached_optic_fixtures",
        lambda *_a, **_k: [{"id": "fx", "odds": [{"market_id": "moneyline"}]}],
    )
    out = why_venue_gap_node(_nfl_store(), [_node_row()], catalogue_fn=_catalogue)
    aliases = {i["id"]: i for i in out["mappable_items"] if i["kind"] == "alias"}
    assert aliases["alias:19"]["label"] == "Kansas City Chiefs · 19"
    assert aliases["alias:19"]["fixable"]
    # Without catalogue ids the Unmapped fallback would offer the symbol itself as an alias.
    bare = why_venue_gap_node(_nfl_store(), [_node_row()], catalogue_fn=lambda _s: {})
    assert not [i for i in bare["mappable_items"] if i["kind"] == "alias"]
    assert "cart" not in aliases["alias:19"]


def test_why_node_external_id_alias_counts_as_mapped(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.gap_market_bind.cached_optic_fixtures",
        lambda *_a, **_k: [],
    )
    chiefs = EntityRow(
        league="nfl",
        entity_type="team",
        canonical_key="KC",
        canonical_name="Kansas City Chiefs",
        aliases=[{"sportsbook": "crypto.com", "alias_kind": "external_id", "alias_value": "19"}],
    )
    out = why_venue_gap_node(_nfl_store([chiefs]), [_node_row()], catalogue_fn=_catalogue)
    aliases = {i["id"]: i for i in out["mappable_items"] if i["kind"] == "alias"}
    assert aliases["alias:19"]["mapped"] is True
    assert aliases["alias:16"]["mapped"] is False


def test_unmapped_summarize_accepts_external_id_for_crypto() -> None:
    chiefs = EntityRow(
        league="nfl",
        entity_type="team",
        canonical_key="KC",
        canonical_name="Kansas City Chiefs",
        aliases=[{"sportsbook": "crypto.com", "alias_kind": "external_id", "alias_value": "19"}],
    )
    row = {"platform": "crypto", "key": "NX.F.OPT.NFL-1", "league": "nfl", "crypto_ids": ["19"]}
    items = summarize_mappable_items(row, _nfl_store([chiefs]))
    alias = next(i for i in items if i["kind"] == "alias")
    assert alias["mapped"] is True


def test_split_blind_routes_self_named_pins_to_editor() -> None:
    blind = {
        "kind": "entity_alias",
        "label": "Pin 19 (nfl)",
        "payload": {
            "league": "nfl",
            "canonical_key": "19",
            "aliases": [{"sportsbook": "crypto.com", "alias_kind": "crypto_id", "alias_value": "19"}],
        },
    }
    real = {"kind": "mapping_market_rules", "label": "rule", "payload": {"league": "nfl"}}
    legs = [{"crypto_names": {"19": "Kansas City Chiefs"}}]
    kept, editor = _split_blind([real, blind, dict(blind)], legs)
    assert kept == [real]
    assert len(editor) == 1
    state = editor[0]["entry_state"]
    assert editor[0]["label"] == "Kansas City Chiefs · 19"
    assert (state["tab"], state["code"], state["alias_kind"], state["entity_name"]) == (
        "alias",
        "19",
        "external_id",
        "Kansas City Chiefs",
    )


def test_stage_node_requires_items() -> None:
    out = stage_venue_gap_node(_nfl_store(), [_node_row()], [], catalogue_fn=_catalogue)
    assert out["ok"] is False and out["cart_items"] == [] and out["needs_editor"] == []


# ---- caches / memo ------------------------------------------------------------------------


def test_census_cache_reuses_and_expires_empty(monkeypatch: Any) -> None:
    gap_optic_census.clear_census_cache()
    calls: list[list[str]] = []
    answers = iter([{"moneyline"}, set(), {"total"}])

    def fetch(ids: list[str], *, horizon_hours: float = 96.0) -> set[str]:
        calls.append(ids)
        return next(answers)

    monkeypatch.setattr(gap_optic_census, "fetch_optic_market_ids", fetch)
    assert gap_optic_census.cached_optic_market_ids(["nfl"]) == {"moneyline"}
    assert gap_optic_census.cached_optic_market_ids(["nfl"]) == {"moneyline"}
    assert len(calls) == 1
    assert gap_optic_census.cached_optic_market_ids(["nba"]) == set()
    monkeypatch.setattr(gap_optic_census, "CENSUS_EMPTY_TTL_SECONDS", 0.0)
    assert gap_optic_census.cached_optic_market_ids(["nba"]) == {"total"}
    gap_optic_census.clear_census_cache()


def test_league_cfg_memo_scoped_to_block() -> None:
    store = _nfl_store()
    with league_cfg_memo():
        first = effective_league_cfg(store, "nfl")
        assert effective_league_cfg(store, "nfl") is first
    assert effective_league_cfg(store, "nfl") is not first


# ---- routes -------------------------------------------------------------------------------


class _FakeControl:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def console_venue_gaps(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("list", kw))
        return {"leagues": []}

    def console_venue_gap_fixture(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("fixture", kw))
        return {"markets": []}

    def console_venue_gap_why(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("why", kw))
        return {"mappable_items": []}

    def console_venue_gap_stage(self, **kw: Any) -> dict[str, Any]:
        self.calls.append(("stage", kw))
        return {"ok": True, "cart_items": []}


def test_routes_forward_to_service() -> None:
    fake = _FakeControl()
    app = FastAPI()
    register_venue_gap_routes(app, service=lambda: cast("ProposalService", fake), call=lambda fn: fn())
    client = TestClient(app)
    assert client.get("/console/venue-gaps", params={"phase": "pre", "q": "nfl"}).status_code == 200
    assert client.get("/console/venue-gaps/fixture", params={"fixture_key": "k"}).status_code == 200
    row = {"key": "NX.1", "league": "nfl", "contract_type": "Moneyline"}
    assert client.post("/console/venue-gaps/why", json={"rows": [row]}).status_code == 200
    body = {"rows": [row], "item_ids": ["alias:19"]}
    assert client.post("/console/venue-gaps/stage", json=body).status_code == 200
    kinds = [name for name, _ in fake.calls]
    assert kinds == ["list", "fixture", "why", "stage"]
    assert fake.calls[0][1] == {
        "platform": "crypto",
        "phase": "pre",
        "q": "nfl",
        "kickoff_from": None,
        "kickoff_to": None,
        "markets": None,
    }
    assert fake.calls[2][1]["rows"][0]["key"] == "NX.1"
    assert fake.calls[3][1]["item_ids"] == ["alias:19"]


# ---- kickoff window + market-name filter -----------------------------------------------------


def _contract_rows() -> list[dict[str, Any]]:
    """One fixture split over two contract types, plus a later fixture."""
    return [
        {**_rollup("NFL", "fx-1", 5, 10, 2), "contract_type": "Moneyline"},
        {**_rollup("NFL", "fx-1", 5, 30, 0), "contract_type": "Passing Yards"},
        {**_rollup("NFL", "fx-2", 50, 20, 20), "contract_type": "Moneyline"},
    ]


def test_tree_folds_contract_rows_into_fixtures() -> None:
    leagues = build_venue_gap_tree(_contract_rows(), _nfl_store(), phase="pre")
    fixtures = {fx["fixture_key"]: fx for fx in leagues[0]["fixtures"]}
    assert (fixtures["fx-1"]["total"], fixtures["fx-1"]["mapped"]) == (40, 2)
    assert leagues[0]["total"] == 60


def test_tree_market_filter_keeps_only_picked_contracts() -> None:
    leagues = build_venue_gap_tree(_contract_rows(), _nfl_store(), phase="pre", markets=["passing yards"])
    assert [(fx["fixture_key"], fx["total"]) for fx in leagues[0]["fixtures"]] == [("fx-1", 30)]


def test_tree_kickoff_window_drops_outside_fixtures() -> None:
    now = datetime.now(UTC)
    leagues = build_venue_gap_tree(
        _contract_rows(),
        _nfl_store(),
        phase="pre",
        kickoff_from=now + timedelta(hours=1),
        kickoff_to=now + timedelta(hours=10),
    )
    assert [fx["fixture_key"] for fx in leagues[0]["fixtures"]] == ["fx-1"]


def _contract_catalogue() -> list[dict[str, Any]]:
    """Catalogue rows: fx-1 (5h) Moneyline 10 (2 mapped) + Passing Yards 30; fx-2 (50h) Moneyline 20 mapped."""
    rows = [{**_cat(f"m1-{i}", "fx-1", i < 2, hours=5), "contract_type": "Moneyline"} for i in range(10)]
    rows += [{**_cat(f"py-{i}", "fx-1", False, hours=5), "contract_type": "Passing Yards"} for i in range(30)]
    rows += [{**_cat(f"m2-{i}", "fx-2", True, hours=50), "contract_type": "Moneyline"} for i in range(20)]
    return rows


def test_rollup_rows_by_contract_splits_each_fixture() -> None:
    rows = rollup_rows(_contract_catalogue(), {}, by_contract=True)
    counts = {(r["fixture_key"], r["contract_type"]): (r["total"], r["mapped"]) for r in rows}
    assert counts == {
        ("fx-1", "Moneyline"): (10, 2),
        ("fx-1", "Passing Yards"): (30, 0),
        ("fx-2", "Moneyline"): (20, 20),
    }
    assert len(rollup_rows(_contract_catalogue(), {})) == 2


def test_list_venue_gaps_market_options_rank_biggest_gap_first() -> None:
    out = list_venue_gaps(
        phase="pre",
        markets=["Moneyline"],
        store=_nfl_store(),
        query_fn=_catalogue_fn(_contract_catalogue(), {}),
    )
    # Facet ignores its own selection; Passing Yards (30 unmapped) outranks Moneyline (8).
    assert [(o["name"], o["unmapped"], o["fixtures"]) for o in out["market_options"]] == [
        ("Passing Yards", 30, 1),
        ("Moneyline", 8, 2),
    ]
    assert out["totals"]["selections"] == 30


def test_list_venue_gaps_window_bound_as_string_and_bad_bound() -> None:
    now = datetime.now(UTC)
    out = list_venue_gaps(
        phase="pre",
        kickoff_from=(now + timedelta(hours=20)).replace(tzinfo=None).isoformat(timespec="minutes"),
        store=_nfl_store(),
        query_fn=_catalogue_fn(_contract_catalogue(), {}),
    )
    assert [fx["fixture_key"] for fx in out["leagues"][0]["fixtures"]] == ["fx-2"]
    assert [o["name"] for o in out["market_options"]] == ["Moneyline"]
    bad = list_venue_gaps(kickoff_to="soon", store=_nfl_store(), query_fn=_catalogue_fn(_contract_catalogue(), {}))
    assert "kickoff_to" in (bad["error"] or "")
    assert bad["leagues"] == []


def test_venue_gaps_route_passes_repeated_market_params() -> None:
    seen: dict[str, Any] = {}

    class _Svc:
        def console_venue_gaps(self, **kwargs: Any) -> dict[str, Any]:
            seen.update(kwargs)
            return {"ok": True}

    app = FastAPI()
    register_venue_gap_routes(app, service=lambda: cast("ProposalService", _Svc()), call=lambda fn: fn())
    res = TestClient(app).get(
        "/console/venue-gaps",
        params=[("market", "Moneyline"), ("market", "Total Points"), ("kickoff_from", "2026-09-26T12:00")],
    )
    assert res.status_code == 200
    assert seen["markets"] == ["Moneyline", "Total Points"]
    assert seen["kickoff_from"] == "2026-09-26T12:00"
