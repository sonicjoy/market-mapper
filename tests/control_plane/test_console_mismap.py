"""Explore -> Mapping risk: signals, tiering, listing and flags (no BQ)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mappers.control_plane import console_mismap, console_mismap_sql
from mappers.control_plane.console_mismap import (
    FLAG_SOURCE,
    coverage_notes,
    flag_mapping,
    list_mapping_risk,
    resolve_flag,
)
from mappers.control_plane.console_mismap_score import (
    ai_flagged,
    key_multi_market,
    missing_fixture_id,
    name_mismatch,
    optic_disagrees,
    period_mismatch,
    price_gap,
    score_row,
    shared_selection,
    stale_game,
)
from mappers.control_plane.console_mismap_sql import MISMAP_SQL
from mappers.control_plane.http_console_mismap import register_mismap_routes
from mappers.control_plane.models import Actor, ActorRole, ForbiddenError, ValidationFailedError
from mappers.control_plane.store import InMemoryStore

if TYPE_CHECKING:
    from mappers.control_plane.service import ProposalService

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
PROPOSER = Actor(subject="trader@example.com", role=ActorRole.PROPOSER)
VIEWER = Actor(subject="viewer@example.com", role=ActorRole.VIEWER)


def _row(**over: Any) -> dict[str, Any]:
    """A clean Kalshi moneyline row that Optic corroborates; override one field per test."""
    canon = "g1|moneyline|new york mets||0.00"
    base: dict[str, Any] = {
        "sb": "kalshi",
        "book": "Kalshi",
        "src_key": "|KXMLBGAME-26SEP26NYMWSH-NYM|yes",
        "src_market": "KXMLBGAME-26SEP26NYMWSH-NYM",
        "src_selection": "yes",
        "canon": canon,
        "game_id": "g1",
        "fixture_id": "F1",
        "league": "mlb",
        "market_id": "moneyline",
        "selection": "New York Mets",
        "selection_line": None,
        "points": 0.0,
        "mapping_source": "GREG",
        "rank_class": "curated_greg",
        "is_rfq_winner": True,
        "start_date": NOW + timedelta(hours=6),
        "n_optic": 1,
        "n_ours": 1,
        "optic_canons": [canon],
        "our_canons": [canon],
        "canon_keys": 1,
        "canon_src_keys": ["|KXMLBGAME-26SEP26NYMWSH-NYM|yes"],
    }
    base.update(over)
    return base


def _tier(sig: dict[str, str] | None) -> str:
    assert sig is not None
    return sig["tier"]


# ---- signals ---------------------------------------------------------------------------------


def test_clean_row_scores_nothing() -> None:
    assert score_row(_row(), NOW) == {"tier": None, "signals": []}


def test_optic_disagreement_is_high_only_for_fixture_or_selection() -> None:
    other_team = _row(optic_canons=["g1|moneyline|washington nationals||0.00"])
    assert _tier(optic_disagrees(other_team)) == "high"
    renamed_market = _row(
        market_id="player_goals",
        canon="g1|player_goals|x|over|0.50",
        optic_canons=["g1|anytime_goal_scorer|x||0.00"],
    )
    assert _tier(optic_disagrees(renamed_market)) == "low"
    assert optic_disagrees(_row(mapping_source="ORIGINAL", optic_canons=["other"])) is None


def test_one_venue_key_on_two_fixtures_is_high() -> None:
    sig = key_multi_market(
        _row(n_ours=2, our_canons=["g1-09|team_total|mets|over|3.50", "g1-13|team_total|mets|over|3.50"])
    )
    assert sig is not None and sig["tier"] == "high"
    assert "2 markets/fixtures" in sig["text"]


def test_ai_verdict_lists_failed_dimensions() -> None:
    sig = ai_flagged(_row(ai_ok=False, ai_line_ok=False, ai_reason="line mismatch: 7.5 vs 6.5"))
    assert sig == {"code": "ai_flagged", "tier": "high", "text": "AI validator: line mismatch: 7.5 vs 6.5 (line)"}
    assert ai_flagged(_row(ai_ok=True)) is None


def test_name_check_player_needs_surname_team_needs_any_token() -> None:
    player = {"market_id": "player_points", "sb": "crypto.com"}
    assert name_mismatch(
        _row(**player, selection="Megan Gustafson", exchange_text="Megan DiLeo Over 15.5 Total Points")
    )
    assert (
        name_mismatch(_row(**player, selection="Oronde Gadsden II", exchange_text="Oronde Gadsden: 8+ receptions"))
        is None
    )
    assert name_mismatch(_row(selection="Carolina Panthers", exchange_text="Carolina wins / Carolina")) is None
    assert name_mismatch(_row(selection="Hawaii", sb="polymarket", exchange_text="Hawai'i vs. Wyoming")) is None
    assert name_mismatch(_row(selection="Enzo Fernández", **player, exchange_text="Enzo Fernandez to score")) is None


def test_name_check_skips_one_sided_venue_text() -> None:
    kalshi_no = _row(src_selection="no", selection="Germany Or Greece", exchange_text="Tie 1st Half")
    assert name_mismatch(kalshi_no) is None
    spread_other_side = _row(
        sb="polymarket",
        market_id="point_spread",
        selection="Texas Southern",
        exchange_text="Spread: Alcorn State (-3.5)",
    )
    assert name_mismatch(spread_other_side) is None


def test_price_gap_prematch_real_books_only() -> None:
    uncorroborated = {"optic_canons": []}
    assert _tier(price_gap(_row(venue_price=1.25, fair_price=2.5, **uncorroborated), NOW)) == "high"  # 80% vs 40%
    assert _tier(price_gap(_row(venue_price=1.5, fair_price=2.0, **uncorroborated), NOW)) == "medium"  # 67% vs 50%
    assert _tier(price_gap(_row(venue_price=1.25, fair_price=2.5), NOW)) == "low"  # Optic agrees on the mapping
    assert price_gap(_row(venue_price=1.01, fair_price=2.5, **uncorroborated), NOW) is None  # empty-book artefact
    started = _row(venue_price=1.25, fair_price=2.5, start_date=NOW - timedelta(minutes=5), **uncorroborated)
    assert price_gap(started, NOW) is None


def test_period_check_reads_kalshi_series() -> None:
    assert (
        _tier(period_mismatch(_row(src_market="KXNCAAF1HTOTAL-26SEP26USAUK-21", market_id="total_points"))) == "medium"
    )
    assert period_mismatch(_row(src_market="KXNCAAF1H-26SEP26USAUK-USA", market_id="1st_half_moneyline_3-way")) is None
    assert period_mismatch(_row(src_market="KXMLBF5TOTAL-26SEP26X-5", market_id="1st_half_total_runs")) is None
    assert period_mismatch(_row(src_market="KXNFL1Q-26SEP27X-DEN", market_id="1st_quarter_moneyline_3-way")) is None
    assert period_mismatch(_row(sb="polymarket", src_market="x", market_id="1st_half_moneyline")) is None


def test_shared_selection_ignores_the_yes_no_complement() -> None:
    pair = ["|UDXNFLGAMEWIN_BALDAL_BAL|yes", "|UDXNFLGAMEWIN_BALDAL_DAL|no"]
    assert shared_selection(_row(canon_keys=2, canon_src_keys=pair)) is None
    dup = ["NX.F.OPT.MLB-00011-260926-M.O.1.281.20261130", "NX.F.OPT.MLB-00011-260926-M.O.1.217.20261130"]
    assert _tier(shared_selection(_row(canon_keys=2, canon_src_keys=dup))) == "low"


def test_gustafson_dileo_incident_ranks_high() -> None:
    """The validator's recorded cross-wire (aaacee7): crypto.com WNBA 2026-08-08."""
    row = _row(
        sb="crypto.com",
        market_id="player_points",
        selection="Megan Gustafson",
        points=15.5,
        src_key="NX.F.OPT.WNBA-00003-260808-M.O.1.63.20261230",
        exchange_text="Megan DiLeo Over 15.5 Total Points / Seattle Storm @ Portland Fire",
        ai_ok=False,
        ai_entity_ok=False,
        ai_reason="player mismatch: Megan Gustafson vs Megan DiLeo",
        optic_canons=[],
    )
    scored = score_row(row, NOW)
    assert scored["tier"] == "high"
    assert {s["code"] for s in scored["signals"]} == {"ai_flagged", "name_mismatch"}
    # Even without the AI verdict, the deterministic name check alone raises it.
    no_ai = score_row({**row, "ai_ok": None, "ai_entity_ok": None}, NOW)
    assert [s["code"] for s in no_ai["signals"]] == ["name_mismatch"]


# ---- listing -----------------------------------------------------------------------------------


def _rows() -> list[dict[str, Any]]:
    return [
        _row(),
        _row(src_key="k-high", optic_canons=["g1|moneyline|washington nationals||0.00"], is_rfq_winner=False),
        _row(
            src_key="k-high-served", canon="g2|moneyline|a||0.00", optic_canons=["g9|moneyline|a||0.00"], league="nfl"
        ),
        _row(src_key="k-low", sb="crypto.com", canon_keys=2, canon_src_keys=["a", "b"], optic_canons=[]),
    ]


def test_list_ranks_riskiest_and_served_first_with_facets() -> None:
    out = list_mapping_risk(query_fn=_rows, now=NOW)
    assert out["error"] is None
    assert [r["src_key"] for r in out["rows"]] == ["k-high-served", "k-high", "k-low"]
    assert out["facets"]["tiers"] == {"high": 2, "low": 1}
    assert out["facets"]["reasons"] == {"optic_disagrees": 2, "shared_selection": 1}


def test_list_filters_and_window() -> None:
    assert list_mapping_risk(query_fn=_rows, platform="crypto.com", now=NOW)["count"] == 1
    assert list_mapping_risk(query_fn=_rows, tier="high", q="nfl", now=NOW)["count"] == 1
    assert list_mapping_risk(query_fn=_rows, reason="shared_selection", now=NOW)["count"] == 1
    late = (NOW + timedelta(hours=10)).isoformat()
    assert list_mapping_risk(query_fn=_rows, kickoff_from=late, now=NOW)["count"] == 0
    assert "kickoff_to" in list_mapping_risk(query_fn=_rows, kickoff_to="soon", now=NOW)["error"]


def test_list_reports_what_each_venue_cannot_measure() -> None:
    notes = {n["platform"]: n["missing"] for n in coverage_notes()}
    assert notes["kalshi"] == []
    assert any("price_gap" in m for m in notes["sx bet"])
    assert any("optic_disagrees" in m for m in notes["crypto.com"])


def test_sql_reads_the_independent_sources() -> None:
    for table in (
        "opticodds_mapping",
        "opticodds_prices",
        "parlay_fair_price_v2",
        "market_mapping_ai_validation",
        "markets_us.market_mapping",
    ):
        assert table in MISMAP_SQL
    assert MISMAP_SQL.lstrip().startswith("with")


# ---- flags -------------------------------------------------------------------------------------


def _store() -> InMemoryStore:
    return InMemoryStore(environment="test", allow_activate=True)


def test_flag_persists_attaches_and_resolves() -> None:
    store = _store()
    row = list_mapping_risk(query_fn=_rows, now=NOW)["rows"][0]
    flag = flag_mapping(store, PROPOSER, row=row, note="Optic has the other team")
    assert flag["status"] == "open" and flag["flagged_by"] == PROPOSER.subject
    assert [i.source for i in store.list_work_items()] == [FLAG_SOURCE]
    listed = list_mapping_risk(query_fn=_rows, store=store, now=NOW)["rows"][0]
    assert listed["flag"]["note"] == "Optic has the other team"
    again = flag_mapping(store, PROPOSER, row=row, note="still wrong")
    assert again["work_item_id"] == flag["work_item_id"]
    done = resolve_flag(store, PROPOSER, fingerprint=row["fingerprint"], note="pinned via Proposed P-1")
    assert done["status"] == "resolved" and done["flagged_by"] == PROPOSER.subject
    assert list_mapping_risk(query_fn=_rows, store=store, flagged=True, now=NOW)["count"] == 0


def test_flagged_view_keeps_a_row_that_no_longer_scores() -> None:
    store = _store()
    row = list_mapping_risk(query_fn=_rows, now=NOW)["rows"][0]
    flag_mapping(store, PROPOSER, row=row, note="wrong fixture")
    out = list_mapping_risk(query_fn=list, store=store, flagged=True, now=NOW)
    assert out["count"] == 1
    assert out["rows"][0]["src_key"] == row["src_key"] and out["rows"][0]["flag"]["status"] == "open"


def test_flag_needs_a_writer_and_a_note() -> None:
    row = list_mapping_risk(query_fn=_rows, now=NOW)["rows"][0]
    with pytest.raises(ForbiddenError):
        flag_mapping(_store(), VIEWER, row=row, note="x")
    with pytest.raises(ValidationFailedError):
        flag_mapping(_store(), PROPOSER, row=row, note="  ")
    with pytest.raises(ValidationFailedError):
        flag_mapping(_store(), PROPOSER, row={"sb": "kalshi"}, note="x")
    with pytest.raises(ValidationFailedError):
        resolve_flag(_store(), PROPOSER, fingerprint="mismap|none", note="x")


def test_routes_forward_filters_and_actor() -> None:
    calls: list[tuple[str, Any]] = []

    class _Svc:
        def console_mapping_risk(self, **kw: Any) -> dict[str, Any]:
            calls.append(("list", kw))
            return {"rows": []}

        def console_mapping_risk_flag(self, row: dict[str, Any], note: str, actor: Actor) -> dict[str, Any]:
            calls.append(("flag", (row, note, actor.subject)))
            return {"status": "open"}

        def console_mapping_risk_resolve(self, fingerprint: str, note: str, actor: Actor) -> dict[str, Any]:
            calls.append(("resolve", (fingerprint, note, actor.subject)))
            return {"status": "resolved"}

    app = FastAPI()
    register_mismap_routes(
        app,
        authenticated_actor=lambda: PROPOSER,
        service=lambda: cast("ProposalService", _Svc()),
        call=lambda fn: fn(),
    )
    client = TestClient(app)
    assert client.get("/console/mapping-risk", params={"tier": "high", "flagged": "true"}).status_code == 200
    assert client.post("/console/mapping-risk/flag", json={"row": {"sb": "kalshi"}, "note": "n"}).status_code == 200
    assert client.post("/console/mapping-risk/resolve", json={"fingerprint": "fp", "note": "ok"}).status_code == 200
    assert calls[0][1]["tier"] == "high" and calls[0][1]["flagged"] is True
    assert calls[1][1] == ({"sb": "kalshi"}, "n", PROPOSER.subject)
    assert calls[2][1] == ("fp", "ok", PROPOSER.subject)


def test_default_query_caches_for_an_hour_and_reports_when(monkeypatch: pytest.MonkeyPatch) -> None:
    assert console_mismap_sql.CACHE_TTL_SECONDS == 3600.0
    calls: list[str] = []
    monkeypatch.setattr(console_mismap, "ro_query", lambda _c, sql: calls.append(sql) or [])
    monkeypatch.setattr(console_mismap.bigquery, "Client", lambda **_: object())
    console_mismap.clear_mismap_cache()
    assert console_mismap.mismap_cached_at() is None
    console_mismap.default_mismap_query()
    console_mismap.default_mismap_query()
    assert len(calls) == 1
    assert console_mismap.mismap_cached_at() is not None
    console_mismap.clear_mismap_cache()


def test_stale_game_is_high_only_when_served() -> None:
    served = stale_game(_row(game_live=False, is_rfq_winner=True, game_id="40848-66077-2026-09-27-03"))
    assert served is not None and served["tier"] == "high"
    assert "40848-66077-2026-09-27-03" in served["text"]
    assert _tier(stale_game(_row(game_live="false", is_rfq_winner=False))) == "low"  # BQ CLI string form
    assert stale_game(_row(game_live=True, is_rfq_winner=True)) is None
    assert stale_game(_row(is_rfq_winner=True)) is None  # no evidence -> no signal


def test_market_key_groups_reschedules_by_fixture_id() -> None:
    assert "concat(o.fixture_id, '|', o.market_id" in MISMAP_SQL
    assert "coalesce(o.fixture_id" not in MISMAP_SQL  # no game_id fallback
    assert "opticodds_fixtures" in MISMAP_SQL and "game_live" in MISMAP_SQL
    # Same current-game rule as fold+rank: rank window + live statuses only.
    assert "status in ('unplayed', 'live', 'delayed')" in MISMAP_SQL
    assert "if(fx.fixture_id is null, null, fx.game_id = o.game_id) as game_live" in MISMAP_SQL


def test_missing_fixture_id_is_flagged_not_grouped() -> None:
    assert _tier(missing_fixture_id(_row(fixture_id=None, is_rfq_winner=True))) == "medium"
    assert _tier(missing_fixture_id(_row(fixture_id="", is_rfq_winner=False))) == "low"
    assert missing_fixture_id(_row(fixture_id="202609275E72F08B")) is None
