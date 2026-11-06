"""Explore -> Override patterns: cluster repeated overrides, draft via the kernel, stage (no BQ)."""

from __future__ import annotations

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mappers.control_plane.http_console_override_patterns import register_override_pattern_routes
from mappers.control_plane.models import Actor, ActorRole
from mappers.control_plane.override_clusters import cluster_id_for, cluster_overrides
from mappers.control_plane.override_clusters_draft import (
    list_override_patterns,
    stage_override_pattern,
)
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import InMemoryStore

_ACTOR = Actor(subject="ops@example.com", role=ActorRole.PROPOSER)


def _nfl_league() -> LeagueRow:
    return LeagueRow(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=["moneyline"],
        exchanges=[],
    )


def _team(key: str, name: str, aliases: list[dict[str, Any]] | None = None) -> EntityRow:
    return EntityRow(league="nfl", entity_type="team", canonical_key=key, canonical_name=name, aliases=aliases or [])


def _store(entities: list[EntityRow] | None = None, rules: list[MarketRuleRow] | None = None) -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_override_patterns",
        entities=entities if entities is not None else [_team("KC", "Kansas City Chiefs")],
        leagues=[_nfl_league()],
        market_rules=rules or [],
        activate=True,
    )
    return store


def _override(ticker: str, game: str, market: str, selection: str, **extra: Any) -> dict[str, Any]:
    return {
        "sportsbook": "kalshi",
        "source_market_id": ticker,
        "source_selection_id": extra.get("side", "yes"),
        "game_id": game,
        "market_id": market,
        "selection": selection,
        "active": extra.get("active", True),
        "source": extra.get("source"),
    }


def _rows(games: int = 3) -> list[dict[str, Any]]:
    """Kalshi overrides onto Optic moneyline in ``games`` fixtures."""
    return [_override(f"KXNFLGAME-26SEP{20 + g}KCCBUF-KCC", f"m{g}", "moneyline", "Kansas City Chiefs") for g in range(games)]


# ---- clustering --------------------------------------------------------------------------------


def test_no_venue_is_clustered_and_every_row_is_counted() -> None:
    """Kalshi maps from its own typed fields, so its overrides propose no tip rule."""
    rows = [*_rows(3), {**_rows(1)[0], "sportsbook": "prophet x"}]
    grouped = cluster_overrides(rows, _store())
    assert grouped["clusters"] == []
    assert grouped["unparsed"] == {"kalshi:unsupported_book": 3, "prophet x:unsupported_book": 1}


def test_inactive_overrides_skipped_unless_asked() -> None:
    rows = [{**row, "active": False} for row in _rows(3)]
    assert cluster_overrides(rows, _store())["unparsed"] == {}
    assert cluster_overrides(rows, _store(), include_inactive=True)["unparsed"] == {"kalshi:unsupported_book": 3}


def test_cluster_ids_are_stable() -> None:
    assert cluster_id_for("alias", "px", "nfl", "KCC", "kansas city chiefs") == cluster_id_for(
        "alias", "px", "nfl", "KCC", "kansas city chiefs"
    )


# ---- listing -----------------------------------------------------------------------------------


class _Svc:
    def __init__(self, store: InMemoryStore) -> None:
        self.store = store

    def list_proposals(self) -> list[Any]:
        return []


def test_list_surfaces_fetch_errors() -> None:
    def boom() -> list[dict[str, Any]]:
        raise RuntimeError("bq down")

    out = list_override_patterns(_Svc(_store()), boom)
    assert out["error"] == "bq down"
    assert out["clusters"] == []


# ---- staging -----------------------------------------------------------------------------------


def test_stage_refuses_unknown_clusters() -> None:
    service = ProposalService(_store())
    assert stage_override_pattern(service, _ACTOR, "alias:000000000000", _rows)["ok"] is False
    assert service.list_proposals() == []


# ---- routes ------------------------------------------------------------------------------------


def test_routes_forward_and_require_actor_for_stage() -> None:
    calls: list[tuple[str, Any]] = []

    class _Control:
        def console_override_patterns(self, **kw: Any) -> dict[str, Any]:
            calls.append(("list", kw))
            return {"clusters": []}

        def console_override_pattern_stage(self, cluster_id: str, actor: Actor, **kw: Any) -> dict[str, Any]:
            calls.append(("stage", (cluster_id, actor.subject, kw["acknowledge_shadow"])))
            return {"ok": True}

    app = FastAPI()
    register_override_pattern_routes(
        app,
        authenticated_actor=lambda: _ACTOR,
        service=lambda: cast("ProposalService", _Control()),
        call=lambda fn: fn(),
    )
    client = TestClient(app)
    got = client.get("/console/override-patterns", params={"min_games": 5, "include_inactive": "true", "kind": "alias"})
    assert got.status_code == 200
    assert (
        client.post(
            "/console/override-patterns/stage", json={"cluster_id": "alias:abc", "acknowledge_shadow": True}
        ).status_code
        == 200
    )
    assert calls == [
        ("list", {"min_games": 5, "include_inactive": True, "kind": "alias"}),
        ("stage", ("alias:abc", "ops@example.com", True)),
    ]


def test_service_stage_forbids_read_only_roles() -> None:
    service = ProposalService(_store())
    service.override_rows_fn = _rows
    viewer = Actor(subject="viewer@example.com", role=ActorRole.VIEWER)
    try:
        service.console_override_pattern_stage("alias:x", viewer)
    except Exception as exc:  # noqa: BLE001 - asserting the type below
        assert type(exc).__name__ == "ForbiddenError"
    else:
        raise AssertionError("viewer staged a proposal")
