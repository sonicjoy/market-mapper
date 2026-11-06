"""Tests for mapping_league / market_rules proposals."""

from __future__ import annotations

from mappers.control_plane.models import (
    Actor,
    ActorRole,
    ExchangePin,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    MarketRulePin,
    ProposeRequest,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import EntityRow, InMemoryStore, LeagueRow


def _admin() -> Actor:
    return Actor(subject="admin@wsd.com", role=ActorRole.ADMIN)


def _seed() -> InMemoryStore:
    store = InMemoryStore()
    store.seed_rule_set(
        rule_set_id="S0_test_baseline",
        entities=[
            EntityRow(
                league="lol",
                entity_type="team",
                canonical_key="T1",
                canonical_name="T1",
                aliases=[],
            )
        ],
        leagues=[
            LeagueRow(
                league="lol",
                sport="esports",
                optic_league_id="league-of-legends",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[{"sportsbook": "px", "parser_profile": "px_generic_v1"}],
            )
        ],
        market_rules=[],
        activate=True,
    )
    return store


def test_league_propose_validate_activate():
    svc = ProposalService(_seed())
    prop = svc.propose(
        ProposeRequest(
            request_id="req_league",
            expected_rule_set_id="S0_test_baseline",
            artifact_type="mapping_league",
            summary="Add demo league",
            payload=MappingLeaguePayload(
                league="demo_league",
                sport="soccer",
                optic_league_id="demo",
                exchanges=[
                    ExchangePin(
                        sportsbook="px",
                        parser_profile="px_generic_v1",
                        settings={"prefix": "KXDEMO"},
                    )
                ],
            ),
        ),
        _admin(),
    )
    svc.validate(prop.proposal_id, _admin())
    approved = svc.approve(prop.proposal_id, _admin())
    assert approved.status == "activated"
    leagues = {row.league for row in svc.store.leagues_for(approved.activated_rule_set_id or "")}
    assert "demo_league" in leagues


def test_league_needs_code_blocks_unknown_profile():
    svc = ProposalService(_seed())
    prop = svc.propose(
        ProposeRequest(
            request_id="req_bad_profile",
            expected_rule_set_id="S0_test_baseline",
            artifact_type="mapping_league",
            summary="bad",
            payload=MappingLeaguePayload(
                league="weird",
                sport="other",
                optic_league_id="x",
                exchanges=[
                    ExchangePin(sportsbook="px", parser_profile="px_does_not_exist_v9")
                ],
            ),
        ),
        _admin(),
    )
    try:
        svc.validate(prop.proposal_id, _admin())
        raise AssertionError("expected ValidationFailedError")
    except Exception as exc:  # noqa: BLE001
        assert getattr(exc, "reason_code", None) == "dry_run_failed"


def test_market_rules_propose_validate():
    svc = ProposalService(_seed())
    prop = svc.propose(
        ProposeRequest(
            request_id="req_mr",
            expected_rule_set_id="S0_test_baseline",
            artifact_type="mapping_market_rules",
            summary="map optic id",
            payload=MappingMarketRulesPayload(
                league="lol",
                rules=[
                    MarketRulePin(
                        sportsbook="optic",
                        rule_kind="market_id",
                        source_key_type="optic_market_id",
                        source_key="moneyline",
                        action="map",
                        canonical_market_type="moneyline",
                    )
                ],
            ),
        ),
        _admin(),
    )
    result = svc.validate(prop.proposal_id, _admin())
    assert result.status == "validated"
    assert svc.human_rules(kind="leagues")["count"] >= 1


def test_human_rules_pagination():
    store = InMemoryStore()
    entities = [
        EntityRow(
            league="lol",
            entity_type="team",
            canonical_key=f"T{i}",
            canonical_name=f"Team {i}",
            aliases=[
                {
                    "sportsbook": "px",
                    "alias_kind": "code",
                    "alias_value": f"C{i:03d}",
                    "enabled": True,
                }
            ],
        )
        for i in range(5)
    ]
    store.seed_rule_set(
        rule_set_id="S0_page",
        entities=entities,
        leagues=[],
        market_rules=[],
        activate=True,
    )
    svc = ProposalService(store)
    page0 = svc.human_rules(kind="entities", limit=2, offset=0)
    assert page0["count"] == 5
    assert page0["limit"] == 2
    assert page0["offset"] == 0
    assert len(page0["entities"]) == 2
    assert page0["entities"][0]["aliases"][0]["code"] == "C000"

    page1 = svc.human_rules(kind="entities", limit=2, offset=2)
    assert page1["count"] == 5
    assert len(page1["entities"]) == 2
    assert page1["entities"][0]["aliases"][0]["code"] == "C002"

    page2 = svc.human_rules(kind="entities", limit=2, offset=4)
    assert len(page2["entities"]) == 1
    assert page2["entities"][0]["aliases"][0]["code"] == "C004"

    clamped = svc.human_rules(kind="entities", limit=0, offset=-3)
    assert clamped["limit"] == 1
    assert clamped["offset"] == 0
    assert len(clamped["entities"]) == 1


def test_league_update_and_market_rule_replace():
    from mappers.control_plane.dry_run_league import apply_league_payload, thin_dry_run_league
    from mappers.control_plane.dry_run_market_rules import (
        apply_market_rules_payload,
        thin_dry_run_market_rules,
    )
    from mappers.control_plane.models import (
        ExchangePin,
        MappingLeaguePayload,
        MappingMarketRulesPayload,
        MarketRulePin,
    )
    from mappers.control_plane.store import MarketRuleRow

    leagues = [
        LeagueRow(
            league="lol",
            sport="esports",
            optic_league_id="league-of-legends",
            extra_optic_league_ids=[],
            fixture_source="api",
            fixture_horizon_hours=96,
            enabled=True,
            output_order=["moneyline"],
            exchanges=[{"sportsbook": "px", "parser_profile": "px_generic_v1"}],
        )
    ]
    update = MappingLeaguePayload(
        league="lol",
        sport="esports",
        optic_league_id="lol-v2",
        exchanges=[
            ExchangePin(sportsbook="px", parser_profile="px_generic_v1", enabled=True)
        ],
    )
    dry = thin_dry_run_league(leagues, update)
    assert dry["ok"]
    assert dry["updating"] is True
    applied = apply_league_payload(leagues, update)
    assert len(applied) == 1
    assert applied[0].optic_league_id == "lol-v2"

    synth = MappingLeaguePayload(
        league="itf_men_doubles",
        sport="tennis",
        optic_league_id="itf_men_doubles",
        fixture_source="synthetic",
        exchanges=[
            ExchangePin(
                sportsbook="px",
                parser_profile="px_generic_v1",
                enabled=True,
                settings={"prefix": "KXITFDOUBLES"},
            )
        ],
    )
    synth_dry = thin_dry_run_league([], synth)
    assert synth_dry["ok"], synth_dry["blockers"]
    empty_optic = MappingLeaguePayload(
        league="italy_serie_a",
        sport="soccer",
        optic_league_id="  ",
        exchanges=[
            ExchangePin(sportsbook="optic", parser_profile="optic_standard_v1"),
        ],
    )
    empty_dry = thin_dry_run_league([], empty_optic)
    assert not empty_dry["ok"]
    assert any("optic_league_id" in b for b in empty_dry["blockers"])
    rules = [
        MarketRuleRow(
            rule_id="mr1",
            league="lol",
            sportsbook="px",
            rule_kind="taxonomy",
            source_key_type="series_ticker",
            source_key="GAME",
            action="ignore",
            canonical_market_type=None,
            priority=100,
            enabled=True,
            confidence="manual",
        )
    ]
    pin = MarketRulePin(
        sportsbook="px",
        rule_kind="taxonomy",
        source_key_type="series_ticker",
        source_key="GAME",
        action="map",
        canonical_market_type="moneyline",
    )
    mr_payload = MappingMarketRulesPayload(league="lol", rules=[pin])
    mr_dry = thin_dry_run_market_rules(leagues, rules, mr_payload)
    assert mr_dry["ok"]
    assert mr_dry["replacing"] == 1
    replaced = apply_market_rules_payload(rules, mr_payload)
    assert len(replaced) == 1
    assert replaced[0].action == "map"
    assert replaced[0].canonical_market_type == "moneyline"


def test_alias_move_strips_prior_owner():
    from mappers.control_plane.dry_run import apply_alias_payload, resolve_alias
    from mappers.control_plane.models import AliasPin, EntityAliasPayload

    entities = [
        EntityRow(
            league="lol",
            entity_type="team",
            canonical_key="T1",
            canonical_name="Team One",
            aliases=[
                {
                    "sportsbook": "px",
                    "alias_kind": "code",
                    "alias_value": "ABC",
                    "enabled": True,
                }
            ],
        ),
        EntityRow(
            league="lol",
            entity_type="team",
            canonical_key="T2",
            canonical_name="Team Two",
            aliases=[],
        ),
    ]
    payload = EntityAliasPayload(
        league="lol",
        canonical_key="T2",
        entity_type="team",
        canonical_name="Team Two",
        aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value="ABC")],
        reassign=True,
    )
    out = apply_alias_payload(entities, payload)
    by_key = {e.canonical_key: e for e in out}
    assert not any(a.get("alias_value") == "ABC" for a in by_key["T1"].aliases)
    assert any(a.get("alias_value") == "ABC" for a in by_key["T2"].aliases)
    assert resolve_alias(
        out, league="lol", sportsbook="px", alias_kind="code", alias_value="ABC"
    ) == ["T2"]


def test_human_rules_includes_machine_keys():
    store = InMemoryStore()
    store.seed_rule_set(
        rule_set_id="S0_keys",
        entities=[
            EntityRow(
                league="lol",
                entity_type="team",
                canonical_key="T1",
                canonical_name="T1",
                aliases=[
                    {
                        "sportsbook": "px",
                        "alias_kind": "code",
                        "alias_value": "T1",
                        "enabled": True,
                    }
                ],
            )
        ],
        leagues=[
            LeagueRow(
                league="lol",
                sport="esports",
                optic_league_id="league-of-legends",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=["moneyline"],
                exchanges=[{"sportsbook": "px", "parser_profile": "px_generic_v1"}],
            )
        ],
        market_rules=[],
        activate=True,
    )
    svc = ProposalService(store)
    ents = svc.human_rules(kind="entities")
    assert ents["entities"]
    row = ents["entities"][0]
    assert row["league"] == "lol"
    assert row["canonical_key"] == "T1"
    leagues = svc.human_rules(kind="leagues")
    assert leagues["leagues"][0]["league"] == "lol"
    assert "exchanges" in leagues["leagues"][0]
