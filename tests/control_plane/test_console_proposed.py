"""Tests for trader console proposed view + trim."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from mappers.control_plane.console_coverage import list_coverage_fixtures
from mappers.control_plane.console_coverage_detail import get_coverage_fixture
from mappers.control_plane.console_mapping_fixtures import (
    attach_next_fixtures,
    fixture_rows_from_optic,
    rail_fixtures_for_rows,
    upcoming_fixture_sort_key,
)
from mappers.control_plane.console_mapping_rows import mapping_rows_from_proposal
from mappers.control_plane.console_proposed_trim import drop_batch_items, payload_unchanged
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    BatchChangesPayload,
    EntityAliasPayload,
    ExchangePin,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    MarketRulePin,
    ProposeRequest,
    ValidationFailedError,
)
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import InMemoryStore


def _svc() -> ProposalService:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S_proposed",
        entities=[
            EntityRow(
                league="epl",
                entity_type="team",
                canonical_key="CHE",
                canonical_name="Chelsea",
                aliases=[
                    {
                        "sportsbook": "px",
                        "alias_kind": "code",
                        "alias_value": "CHE",
                    },
                    {
                        "sportsbook": "optic",
                        "alias_kind": "external_id",
                        "alias_value": "c1",
                    },
                ],
            ),
        ],
        leagues=[
            LeagueRow(
                league="epl",
                sport="soccer",
                optic_league_id="epl-optic",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[{"sportsbook": "px", "parser_profile": "x"}],
            )
        ],
        market_rules=[
            MarketRuleRow(
                rule_id="epl-kalshi-game",
                league="epl",
                sportsbook="px",
                rule_kind="taxonomy",
                source_key_type="market_name",
                source_key="TOTAL",
                action="map",
                canonical_market_type="total",
                priority=100,
                enabled=True,
                confidence="manual",
            )
        ],
        activate=True,
    )
    return ProposalService(store)


def _batch_proposal(svc: ProposalService) -> str:
    actor = Actor(subject="tester", role=ActorRole.ADMIN)
    payload = BatchChangesPayload(
        entity_aliases=[
            EntityAliasPayload(
                league="epl",
                canonical_key="ARS",
                canonical_name="Arsenal",
                aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value="ARS")],
            )
        ],
        market_rules=[
            MappingMarketRulesPayload(
                league="epl",
                rules=[
                    MarketRulePin(
                        sportsbook="px",
                        rule_kind="taxonomy",
                        source_key_type="market_name",
                        source_key="GAME",
                        action="map",
                        canonical_market_type="moneyline_3way",
                    )
                ],
            )
        ],
    )
    req = ProposeRequest(
        request_id="req-proposed-1",
        expected_rule_set_id=svc.store.current_rule_set_id or "",
        artifact_type="batch_changes",
        summary="batch test",
        evidence_refs=["kalshi:title:Arsenal vs Chelsea"],
        payload=payload,
    )
    proposal = svc.propose(req, actor)
    svc.validate(proposal.proposal_id, actor)
    return proposal.proposal_id


def test_mapping_rows_unique_keys() -> None:
    svc = _svc()
    proposal = svc._get(_batch_proposal(svc))  # noqa: SLF001
    groups = svc._change_groups(proposal)  # noqa: SLF001
    tip = {row.league: row for row in svc._tip_leagues()}  # noqa: SLF001
    rows = mapping_rows_from_proposal(
        proposal,
        groups=groups,
        tip_leagues=tip,
        new_leagues=set(),
    )
    kinds = {r["kind"] for r in rows}
    assert kinds == {"alias", "market_rule"}
    keys = [r["key"] for r in rows]
    assert len(keys) == len(set(keys))
    alias = next(r for r in rows if r["kind"] == "alias")
    assert alias["target"]["name"] == "Arsenal"
    assert alias["tier"] == "confirmed"


def test_mapping_rows_league_card_carries_editor_fields() -> None:
    payload = BatchChangesPayload(
        leagues=[
            MappingLeaguePayload(
                league="nfl",
                sport="football",
                optic_league_id="nfl",
                fixture_horizon_hours=168.0,
                exchanges=[
                    ExchangePin(
                        sportsbook="px",
                        parser_profile="px_generic_v1",
                        enabled=True,
                        source_league_id="KXNFL",
                        settings={"prefix": "KXNFL"},
                    ),
                ],
            ),
        ],
    )
    svc = _svc()
    proposal = svc.propose(
        ProposeRequest(
            request_id="req-league-edit",
            expected_rule_set_id=svc.store.current_rule_set_id or "",
            artifact_type="batch_changes",
            summary="nfl kalshi prefix",
            evidence_refs=[],
            payload=payload,
        ),
        Actor(subject="tester", role=ActorRole.ADMIN),
    )
    rows = mapping_rows_from_proposal(
        proposal,
        groups=svc._change_groups(proposal),  # noqa: SLF001
        tip_leagues={row.league: row for row in svc._tip_leagues()},  # noqa: SLF001
        new_leagues={"nfl"},
    )
    league = next(r for r in rows if r["kind"] == "league")
    assert league["fixture_horizon_hours"] == 168.0
    assert league["exchanges"][0]["settings"]["prefix"] == "KXNFL"


def test_drop_new_league_cascades() -> None:
    payload = BatchChangesPayload(
        entity_aliases=[
            EntityAliasPayload(
                league="isl1",
                canonical_key="KRR",
                canonical_name="KR Reykjavik",
                aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value="KRR")],
            )
        ],
        leagues=[
            MappingLeaguePayload(
                league="isl1",
                sport="soccer",
                optic_league_id="isl1-optic",
                exchanges=[
                    ExchangePin(sportsbook="px", parser_profile="x", enabled=True)
                ],
            )
        ],
        market_rules=[
            MappingMarketRulesPayload(
                league="isl1",
                rules=[
                    MarketRulePin(
                        sportsbook="px",
                        rule_kind="taxonomy",
                        source_key_type="market_name",
                        source_key="GAME",
                        action="map",
                        canonical_market_type="moneyline_3way",
                    )
                ],
            )
        ],
    )
    with pytest.raises(ValueError, match="empty_batch"):
        drop_batch_items(
            payload,
            [{"kind": "league", "key": "league:isl1"}],
            tip_league_slugs={"epl"},
        )


def test_drop_alias_with_colon_in_value() -> None:
    payload = BatchChangesPayload(
        entity_aliases=[
            EntityAliasPayload(
                league="epl",
                canonical_key="ARS",
                canonical_name="Arsenal",
                aliases=[
                    AliasPin(
                        sportsbook="polymarket",
                        alias_kind="name",
                        alias_value="Arsenal: home",
                    ),
                    AliasPin(sportsbook="px", alias_kind="code", alias_value="ARS"),
                ],
            )
        ],
    )
    out = drop_batch_items(
        payload,
        [{"kind": "alias", "key": "alias:epl:ARS:polymarket:Arsenal: home"}],
        tip_league_slugs={"epl"},
    )
    pins = out.entity_aliases[0].aliases
    assert [pin.alias_value for pin in pins] == ["ARS"]
    assert not payload_unchanged(payload, out)


def test_drop_clone_bundle_keeps_league() -> None:
    payload = BatchChangesPayload(
        leagues=[
            MappingLeaguePayload(
                league="isl1",
                sport="soccer",
                optic_league_id="isl1-optic",
                exchanges=[
                    ExchangePin(sportsbook="px", parser_profile="x", enabled=True)
                ],
                clone_market_rules_from="epl",
            )
        ],
    )
    out = drop_batch_items(
        payload,
        [{"kind": "market_rule", "key": "clone:isl1"}],
        tip_league_slugs={"epl"},
    )
    assert len(out.leagues) == 1
    assert out.leagues[0].clone_market_rules_from is None
    assert not payload_unchanged(payload, out)


def test_drop_one_cloned_rule_materializes_the_rest() -> None:
    payload = BatchChangesPayload(
        leagues=[
            MappingLeaguePayload(
                league="isl1",
                sport="soccer",
                optic_league_id="isl1-optic",
                exchanges=[
                    ExchangePin(sportsbook="px", parser_profile="x", enabled=True)
                ],
                clone_market_rules_from="epl",
            )
        ],
    )
    tip = [
        MarketRuleRow(
            rule_id="epl-TOTAL",
            league="epl",
            sportsbook="px",
            rule_kind="taxonomy",
            source_key_type="market_name",
            source_key="TOTAL",
            action="map",
            canonical_market_type="total",
            priority=100,
            enabled=True,
            confidence="manual",
        ),
        MarketRuleRow(
            rule_id="epl-SPREAD",
            league="epl",
            sportsbook="px",
            rule_kind="taxonomy",
            source_key_type="market_name",
            source_key="SPREAD",
            action="map",
            canonical_market_type="spread",
            priority=100,
            enabled=True,
            confidence="manual",
        ),
    ]
    out = drop_batch_items(
        payload,
        [{"kind": "market_rule", "key": "rule:isl1:px:market_name:TOTAL"}],
        tip_league_slugs={"epl"},
        tip_market_rules=tip,
    )
    assert out.leagues[0].clone_market_rules_from is None
    assert [pin.source_key for pin in out.leagues[0].market_rules] == ["SPREAD"]


def test_console_trim_rejected_explains_supersede() -> None:
    svc = _svc()
    actor = Actor(subject="checker", role=ActorRole.ADMIN)
    ref = _batch_proposal(svc)
    svc.reject(ref, actor, comment="superseded: combined into P_new")
    with pytest.raises(ValidationFailedError) as exc:
        svc.console_trim_proposed(
            ref,
            [{"kind": "alias", "key": "alias:epl:ARS:px:ARS"}],
            actor,
        )
    assert exc.value.reason_code == "bad_status"
    assert "P_new" in str(exc.value)
    assert exc.value.dry_run.get("superseded_by") == "P_new"
    view = svc.get_review(ref)
    assert view["status"] == "rejected"
    assert view["note"] == "superseded: combined into P_new"


def test_console_trim_noop_keeps_validated() -> None:
    svc = _svc()
    actor = Actor(subject="checker", role=ActorRole.ADMIN)
    ref = _batch_proposal(svc)
    before = svc._get(ref)  # noqa: SLF001
    view = svc.console_trim_proposed(
        ref,
        [{"kind": "alias", "key": "alias:epl:NOPE:px:NOPE"}],
        actor,
    )
    after = svc._get(ref)  # noqa: SLF001
    assert after.status == "validated"
    assert after.candidate_rule_set_id == before.candidate_rule_set_id
    assert view["status"] == "waiting_for_checker"


def test_console_trim_noop_revalidates_when_not_validated() -> None:
    svc = _svc()
    actor = Actor(subject="checker", role=ActorRole.ADMIN)
    ref = _batch_proposal(svc)
    rec = svc._get(ref)  # noqa: SLF001
    rec.status = "proposed"
    rec.candidate_rule_set_id = None
    rec.validated_at = None
    svc.store.put_proposal(rec)
    view = svc.console_trim_proposed(
        ref,
        [{"kind": "alias", "key": "alias:epl:NOPE:px:NOPE"}],
        actor,
    )
    assert view["status"] == "waiting_for_checker"
    assert svc._get(ref).status == "validated"  # noqa: SLF001


def test_console_trim_revalidates() -> None:
    svc = _svc()
    actor = Actor(subject="checker", role=ActorRole.ADMIN)
    ref = _batch_proposal(svc)
    view = svc.console_trim_proposed(
        ref,
        [{"kind": "market_rule", "key": "rule:epl:px:market_name:GAME"}],
        actor,
    )
    assert view["status"] in {"waiting_for_checker", "submitted"}
    assert view.get("mappings")
    assert not any(r["kind"] == "market_rule" for r in view["mappings"])


def test_console_proposed_leagues_ref() -> None:
    svc = _svc()
    ref = _batch_proposal(svc)
    view = svc.console_proposed_leagues(ref=ref)
    assert view["count"] >= 1
    assert view["proposal_ref"] == ref
    assert view["leagues"]


def test_mapping_rows_from_entity_alias_payload() -> None:
    svc = _svc()
    actor = Actor(subject="tester", role=ActorRole.ADMIN)
    payload = EntityAliasPayload(
        league="epl",
        canonical_key="ARS",
        canonical_name="Arsenal",
        aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value="ARS")],
    )
    req = ProposeRequest(
        request_id="req-alias-single",
        expected_rule_set_id=svc.store.current_rule_set_id or "",
        artifact_type="entity_alias",
        summary="single alias",
        evidence_refs=["kalshi:title:Arsenal vs Chelsea"],
        payload=payload,
    )
    proposal = svc.propose(req, actor)
    rec = svc._get(proposal.proposal_id)  # noqa: SLF001
    tip = {row.league: row for row in svc._tip_leagues()}  # noqa: SLF001
    rows = mapping_rows_from_proposal(rec, groups=None, tip_leagues=tip, new_leagues=set())
    assert len(rows) == 1
    assert rows[0]["kind"] == "alias"
    assert rows[0]["sportsbook"] == "px"
    assert rows[0]["target"]["name"] == "Arsenal"


def test_attach_next_fixtures_word_aware() -> None:
    rows = [{"kind": "alias", "league": "epl", "target": {"name": "United"}}]
    fixtures = {
        "epl": [
            {"fixture_id": "1", "home": "Manchester United", "away": "Chelsea"},
            {"fixture_id": "2", "home": "Newcastle", "away": "Arsenal"},
        ]
    }
    attach_next_fixtures(rows, fixtures)
    ids = {str(fx.get("fixture_id")) for fx in rows[0]["next_fixtures"]}
    assert ids == {"1"}


def test_attach_next_fixtures_fills_optic_abbr() -> None:
    rows = [{
        "kind": "alias",
        "league": "epl",
        "sportsbook": "optic",
        "source": {"platform": "Optic", "name": "Chelsea"},
        "target": {"name": "Chelsea", "code": "CHE"},
    }]
    fixtures = {
        "epl": [{
            "fixture_id": "1",
            "home": "Chelsea",
            "away": "Arsenal",
            "home_abbr": "CHE",
            "away_abbr": "ARS",
        }],
    }
    attach_next_fixtures(rows, fixtures)
    assert rows[0]["target"]["abbr"] == "CHE"
    assert rows[0]["source"]["abbr"] == "CHE"


def test_rail_fixtures_only_unblocking() -> None:
    rows = [{"kind": "alias", "next_fixtures": [{"fixture_id": "fx1"}]}]
    league_fixtures = [
        {"fixture_id": "fx1", "label": "A vs B"},
        {"fixture_id": "fx2", "label": "C vs D"},
    ]
    assert rail_fixtures_for_rows(rows, league_fixtures) == [league_fixtures[0]]


def _optic_stub(_oid: str, *, horizon_hours: float) -> list[dict]:
    return [
        {
            "id": "fx1",
            "status": "unplayed",
            "start_date": "2099-06-01T12:00:00+00:00",
            "home_competitors": [
                {"name": "Chelsea", "id": "c1", "abbreviation": "CHE"},
            ],
            "away_competitors": [
                {"name": "Arsenal", "id": "a1", "abbreviation": "ARS"},
            ],
        }
    ]


def test_upcoming_fixture_sort_key_orders_started_after_upcoming() -> None:
    rows = [
        {"ttko_hours": -1.0, "fixture_id": "started"},
        {"ttko_hours": None, "fixture_id": "missing"},
        {"ttko_hours": 2.0, "fixture_id": "soon"},
        {"ttko_hours": 8.0, "fixture_id": "later"},
    ]
    rows.sort(key=upcoming_fixture_sort_key)
    assert [row["fixture_id"] for row in rows] == ["soon", "later", "started", "missing"]


def test_coverage_uses_mapping_query() -> None:
    svc = _svc()

    def mapping_query_fn(_ids: list[str]) -> list[dict]:
        return [{"fixture_id": "fx1", "sportsbook": "px", "market_type": "total"}]

    view = list_coverage_fixtures(
        svc.store,
        league="epl",
        phase="pre",
        fetch_fn=_optic_stub,
        mapping_query_fn=mapping_query_fn,
    )
    assert view["fixtures"]
    assert view["fixtures"][0]["optic_status"] == "unplayed"
    cov = view["fixtures"][0]["coverage"]
    assert cov["mapped_count"] == 1
    detail = get_coverage_fixture(
        svc.store,
        "fx1",
        league="epl",
        fetch_fn=_optic_stub,
        mapping_query_fn=mapping_query_fn,
    )
    assert detail is not None
    assert detail["home"] == "Chelsea"
    assert detail["start_date"]
    home_ent = detail["home_entity"]
    assert home_ent is not None
    assert home_ent["canonical_key"] == "CHE"
    assert detail["home_abbr"] == "CHE"
    assert detail["home_competitor_ids"] == ["c1"]
    assert detail["away_entity"] is None
    assert detail["away_abbr"] == "ARS"
    assert detail["away_competitor_ids"] == ["a1"]
    assert any(pin["code"] == "CHE" and pin["sportsbook"] == "px" for pin in home_ent["aliases"])
    rules = detail["market_rules"]
    assert rules
    assert rules[0]["canonical_market_type"] == "total"
    assert detail["output_order"] == ["moneyline"]
    league_detail = detail["league_detail"]
    assert league_detail is not None
    assert league_detail["sport"] == "soccer"
    assert league_detail["optic_league_id"] == "epl-optic"
    assert league_detail["enabled"] is True
    assert league_detail["fixture_horizon_hours"] == 96
    assert league_detail["alias_enforcement"] == "raise"
    assert any(ex["sportsbook"] == "px" for ex in league_detail["exchanges"])
    platforms = detail["coverage_detail"]["platforms"]
    assert platforms
    assert platforms[0]["mapped_count"] == 1


def test_coverage_counts_game_id_and_casefold_market() -> None:
    svc = _svc()

    def optic(_oid: str, *, horizon_hours: float) -> list[dict]:
        return [
            {
                "id": "optic-fx",
                "game_id": "game-fx",
                "start_date": "2099-06-01T12:00:00+00:00",
                "home_competitors": [
                    {"name": "Chelsea", "id": "c1", "abbreviation": "CHE"},
                ],
                "away_competitors": [
                    {"name": "Arsenal", "id": "a1", "abbreviation": "ARS"},
                ],
            }
        ]

    def mapping_query_fn(ids: list[str]) -> list[dict]:
        assert "optic-fx" in ids
        assert "game-fx" in ids
        return [
            {
                "fixture_id": "other-id",
                "game_id": "game-fx",
                "sportsbook": "px",
                "market_type": "TOTAL",
            }
        ]

    view = list_coverage_fixtures(
        svc.store,
        league="epl",
        phase="pre",
        fetch_fn=optic,
        mapping_query_fn=mapping_query_fn,
    )
    assert view["fixtures"][0]["coverage"]["mapped_count"] == 1
    assert view["fixtures"][0]["sport"] == "soccer"
    detail = get_coverage_fixture(
        svc.store,
        "optic-fx",
        league="epl",
        fetch_fn=optic,
        mapping_query_fn=mapping_query_fn,
    )
    assert detail is not None
    assert detail["sport"] == "soccer"
    assert detail["league"] == "epl"
    assert detail["coverage"]["mapped_count"] == 1


def test_coverage_list_pages_without_live_optic() -> None:
    svc = _svc()
    rows = [
        {
            "fixture_id": f"fx{i}",
            "start_date": "2099-06-01T12:00:00+00:00",
            "home": "Chelsea",
            "away": f"Club{i}",
            "optic_league_id": "epl-optic",
            "home_id": "c1",
            "away_id": f"a{i}",
        }
        for i in range(15)
    ]

    def optic_query_fn(
        *,
        optic_ids: list[str],
        q: str | None,
        limit: int,
        offset: int,
        fwd_hours: int,
        phase: str = "live",
        back_hours: int = 36,
    ) -> tuple[list[dict], int]:
        assert "epl-optic" in optic_ids
        needle = (q or "").strip().lower()
        filtered = [
            row
            for row in rows
            if not needle or needle in f"{row['home']} {row['away']}".lower()
        ]
        return filtered[offset : offset + limit], len(filtered)

    view = list_coverage_fixtures(
        svc.store,
        league="epl",
        phase="pre",
        limit=10,
        offset=0,
        optic_query_fn=optic_query_fn,
        mapping_query_fn=lambda _ids: [],
    )
    assert view["count"] == 15
    assert len(view["fixtures"]) == 10
    assert view["fixtures"][0]["home"] == "Chelsea"
    page2 = list_coverage_fixtures(
        svc.store,
        league="epl",
        phase="pre",
        limit=10,
        offset=10,
        optic_query_fn=optic_query_fn,
        mapping_query_fn=lambda _ids: [],
    )
    assert len(page2["fixtures"]) == 5


def test_coverage_detail_ignores_wrong_league_filter() -> None:
    svc = _svc()
    row = {
        "fixture_id": "fx-detail",
        "start_date": "2099-06-01T12:00:00+00:00",
        "home": "Chelsea",
        "away": "Arsenal",
        "optic_league_id": "epl-optic",
        "home_id": "c1",
        "away_id": "a1",
    }

    def optic_one_fn(fixture_id: str) -> dict:
        assert fixture_id == "fx-detail"
        return row

    detail = get_coverage_fixture(
        svc.store,
        "fx-detail",
        league="wrong-league",
        optic_one_fn=optic_one_fn,
        mapping_query_fn=lambda _ids: [],
    )
    assert detail is not None
    assert detail["home"] == "Chelsea"
    assert detail["league"] == "epl"


def test_fixture_rows_include_optic_id_and_abbr() -> None:
    rows = fixture_rows_from_optic(
        [
            {
                "id": "fx-cs2",
                "start_date": "2099-06-01T12:00:00+00:00",
                "home_competitors": [
                    {"name": "LPH Gaming", "id": "oid-lph", "abbreviation": "LPH"},
                ],
                "away_competitors": [
                    {"name": "XI Esport", "id": "oid-xi", "abbreviation": ""},
                ],
            }
        ]
    )
    assert rows[0]["home_competitor_ids"] == ["oid-lph"]
    assert rows[0]["home_abbr"] == "LPH"
    assert rows[0]["away_competitor_ids"] == ["oid-xi"]
    assert rows[0]["away_abbr"] == ""


def test_coverage_detail_includes_optic_id_and_abbr() -> None:
    svc = _svc()
    row = {
        "fixture_id": "fx-cs2",
        "start_date": "2099-06-01T12:00:00+00:00",
        "home": "LPH Gaming",
        "away": "XI Esport",
        "optic_league_id": "epl-optic",
        "home_id": "oid-lph",
        "away_id": "oid-xi",
        "home_abbr": "LPH",
        "away_abbr": "",
    }

    def optic_one_fn(fixture_id: str) -> dict:
        assert fixture_id == "fx-cs2"
        return row

    detail = get_coverage_fixture(
        svc.store,
        "fx-cs2",
        optic_one_fn=optic_one_fn,
        mapping_query_fn=lambda _ids: [],
    )
    assert detail is not None
    assert detail["home_entity"] is None
    assert detail["away_entity"] is None
    assert detail["home_competitor_ids"] == ["oid-lph"]
    assert detail["home_abbr"] == "LPH"
    assert detail["away_competitor_ids"] == ["oid-xi"]
    assert detail["away_abbr"] == ""


def test_coverage_detail_serializes_bq_datetimes() -> None:
    svc = _svc()
    row = {
        "fixture_id": "fx-detail",
        "start_date": "2099-06-01T12:00:00+00:00",
        "home": "Chelsea",
        "away": "Arsenal",
        "optic_league_id": "epl-optic",
        "home_id": "c1",
        "away_id": "a1",
    }
    kickoff = datetime(2099, 6, 1, 12, 0, tzinfo=UTC)

    def optic_one_fn(fixture_id: str) -> dict:
        assert fixture_id == "fx-detail"
        return row

    def mapping_query_fn(_ids: list[str]) -> list[dict]:
        return [
            {
                "fixture_id": "fx-detail",
                "sportsbook": "px",
                "market_type": "total",
                "market_id": "total_points",
                "last_updated": kickoff,
            }
        ]

    detail = get_coverage_fixture(
        svc.store,
        "fx-detail",
        optic_one_fn=optic_one_fn,
        mapping_query_fn=mapping_query_fn,
    )
    assert detail is not None
    stamps = detail["coverage_detail"]["stamps"]
    assert stamps[0]["last_updated"] == kickoff.isoformat()
    json.dumps(detail)
