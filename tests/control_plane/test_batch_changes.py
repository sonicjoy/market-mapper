"""Tests for compound batch_changes proposals."""

from __future__ import annotations

import pytest

from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    BatchChangesPayload,
    BatchEntryRequest,
    EntityAliasPayload,
    ExchangePin,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    MarketRulePin,
    ProposeRequest,
    ValidationFailedError,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import EntityRow, InMemoryStore, LeagueRow


def _admin() -> Actor:
    return Actor(subject="admin@wsd.com", role=ActorRole.ADMIN)


def _seed() -> InMemoryStore:
    store = InMemoryStore()
    store.seed_rule_set(
        rule_set_id="S0_batch_baseline",
        entities=[
            EntityRow(
                league="lol",
                entity_type="team",
                canonical_key="T1",
                canonical_name="T1",
                aliases=[{"sportsbook": "px", "alias_kind": "code", "alias_value": "T1"}],
            ),
            EntityRow(
                league="lol",
                entity_type="team",
                canonical_key="GEN",
                canonical_name="Gen.G",
                aliases=[{"sportsbook": "px", "alias_kind": "code", "alias_value": "GEN"}],
            ),
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


def test_batch_league_market_rules_and_reassigns_one_candidate():
    svc = ProposalService(_seed())
    payload = BatchChangesPayload(
        leagues=[
            MappingLeaguePayload(
                league="demo_batch",
                sport="soccer",
                optic_league_id="demo-batch",
                exchanges=[
                    ExchangePin(
                        sportsbook="px",
                        parser_profile="px_generic_v1",
                        settings={"prefix": "KXDEMO"},
                    )
                ],
            )
        ],
        market_rules=[
            MappingMarketRulesPayload(
                league="demo_batch",
                rules=[
                    MarketRulePin(
                        sportsbook="px",
                        rule_kind="taxonomy",
                        source_key_type="series_ticker",
                        source_key="KXDEMO-ML",
                        action="map",
                        canonical_market_type="moneyline",
                    ),
                    MarketRulePin(
                        sportsbook="px",
                        rule_kind="taxonomy",
                        source_key_type="series_ticker",
                        source_key="KXDEMO-SPREAD",
                        action="map",
                        canonical_market_type="point_spread",
                    ),
                ],
            )
        ],
        entity_aliases=[
            EntityAliasPayload(
                league="lol",
                canonical_key="T1",
                canonical_name="T1",
                reassign=True,
                aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value="GEN")],
            ),
            EntityAliasPayload(
                league="lol",
                canonical_key="GEN",
                canonical_name="Gen.G",
                reassign=True,
                aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value="GENG")],
            ),
        ],
    )
    prop = svc.propose(
        ProposeRequest(
            request_id="req_batch_ok",
            expected_rule_set_id="S0_batch_baseline",
            artifact_type="batch_changes",
            summary="Batch: 2 aliases, 1 league, 2 market rules",
            payload=payload,
        ),
        _admin(),
    )
    validated = svc.validate(prop.proposal_id, _admin())
    assert validated.status == "validated"
    cid = validated.candidate_rule_set_id
    assert cid is not None
    leagues = {row.league for row in svc.store.leagues_for(cid)}
    assert "demo_batch" in leagues
    assert len(svc.store.market_rules_for(cid)) == 2
    ents = {e.canonical_key: e for e in svc.store.entities_for(cid) if e.league == "lol"}
    t1_codes = {a["alias_value"] for a in ents["T1"].aliases if a.get("sportsbook") == "px"}
    gen_codes = {a["alias_value"] for a in ents["GEN"].aliases if a.get("sportsbook") == "px"}
    assert "GEN" in t1_codes
    assert "GEN" not in gen_codes
    assert "GENG" in gen_codes


def test_batch_dry_run_fails_closed_on_blocked_subitem():
    svc = ProposalService(_seed())
    payload = BatchChangesPayload(
        leagues=[
            MappingLeaguePayload(
                league="bad_league",
                sport="other",
                optic_league_id="x",
                exchanges=[
                    ExchangePin(sportsbook="px", parser_profile="px_does_not_exist_v9")
                ],
            )
        ],
        entity_aliases=[
            EntityAliasPayload(
                league="lol",
                canonical_key="T1",
                aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value="NEWCODE")],
            )
        ],
    )
    prop = svc.propose(
        ProposeRequest(
            request_id="req_batch_bad",
            expected_rule_set_id="S0_batch_baseline",
            artifact_type="batch_changes",
            summary="should fail",
            payload=payload,
        ),
        _admin(),
    )
    with pytest.raises(ValidationFailedError) as excinfo:
        svc.validate(prop.proposal_id, _admin())
    assert excinfo.value.reason_code == "dry_run_failed"
    assert excinfo.value.dry_run.get("blockers")


def test_entry_batch_verify_and_submit():
    svc = ProposalService(_seed())
    body = BatchEntryRequest(
        leagues=[
            MappingLeaguePayload(
                league="cart_league",
                sport="soccer",
                optic_league_id="cart",
                exchanges=[
                    ExchangePin(sportsbook="px", parser_profile="px_generic_v1")
                ],
            )
        ],
        acknowledge_shadow=True,
    )
    verified = svc.entry_batch_verify(body)
    assert verified["ok"] is True
    assert verified["preview_token"]
    card = svc.entry_batch_submit(verified["preview_token"], _admin())
    assert card["artifact"] == "batch_changes"
    assert "Batch:" in card["summary"]
    assert card["headline"] == "Add 1 league."
    assert card["league_label"] != "batch"


def test_batch_review_detail_shows_league_and_rule_changes():
    svc = ProposalService(_seed())
    payload = BatchChangesPayload(
        leagues=[
            MappingLeaguePayload(
                league="demo_a",
                sport="soccer",
                optic_league_id="demo-a",
                exchanges=[
                    ExchangePin(sportsbook="px", parser_profile="px_generic_v1")
                ],
            ),
            MappingLeaguePayload(
                league="demo_b",
                sport="soccer",
                optic_league_id="demo-b",
                exchanges=[
                    ExchangePin(sportsbook="px", parser_profile="px_generic_v1")
                ],
            ),
        ],
        market_rules=[
            MappingMarketRulesPayload(
                league="demo_a",
                rules=[
                    MarketRulePin(
                        sportsbook="px",
                        rule_kind="taxonomy",
                        source_key_type="series_ticker",
                        source_key="KXDEMOA-ML",
                        action="map",
                        canonical_market_type="moneyline",
                    )
                ],
            )
        ],
    )
    prop = svc.propose(
        ProposeRequest(
            request_id="req_batch_review_detail",
            expected_rule_set_id="S0_batch_baseline",
            artifact_type="batch_changes",
            summary="Batch: 0 aliases, 2 leagues, 1 market rules",
            payload=payload,
        ),
        _admin(),
    )
    svc.validate(prop.proposal_id, _admin())
    view = svc.get_review(prop.proposal_id)
    groups = view["change_groups"]
    assert groups["aliases"]["added_count"] == 0
    assert groups["leagues"]["added_count"] == 2
    assert groups["market_rules"]["added_count"] == 1
    assert any("demo_a" in line for line in groups["leagues"]["lines"])
    assert any("demo_b" in line for line in groups["leagues"]["lines"])
    assert any("KXDEMOA-ML" in line for line in groups["market_rules"]["lines"])
    assert view["changes"] == {"added_count": 3, "removed_count": 0, "modified_count": 0}
    assert view["headline"]
    assert "league" in view["headline"].lower()
    assert "Demo A" in view["league_label"]
    assert view["league_label"] != "batch"


def test_get_review_does_not_coalesce_snapshots() -> None:
    svc = ProposalService(_seed())
    payload = BatchChangesPayload(
        leagues=[
            MappingLeaguePayload(
                league="demo_a",
                sport="soccer",
                optic_league_id="demo-a",
                exchanges=[
                    ExchangePin(sportsbook="px", parser_profile="px_generic_v1")
                ],
            )
        ],
    )
    prop = svc.propose(
        ProposeRequest(
            request_id="req_review_no_coalesce",
            expected_rule_set_id="S0_batch_baseline",
            artifact_type="batch_changes",
            summary="Batch: 0 aliases, 1 leagues, 0 market rules",
            payload=payload,
        ),
        _admin(),
    )
    svc.validate(prop.proposal_id, _admin())
    calls = {"n": 0}
    original = svc.store.entities_for

    def wrapped(rule_set_id: str):
        calls["n"] += 1
        return original(rule_set_id)

    svc.store.entities_for = wrapped  # type: ignore[method-assign]
    view = svc.get_review(prop.proposal_id)
    assert calls["n"] == 0
    assert view["change_groups"]["leagues"]["added_count"] == 1


def test_review_unvalidated_tip_league_is_update_not_add():
    svc = ProposalService(_seed())
    payload = BatchChangesPayload(
        leagues=[
            MappingLeaguePayload(
                league="lol",
                sport="esports",
                optic_league_id="league-of-legends",
                exchanges=[
                    ExchangePin(
                        sportsbook="optic",
                        parser_profile="optic_standard_v1",
                        source_league_id="league-of-legends",
                    ),
                ],
            )
        ],
    )
    prop = svc.propose(
        ProposeRequest(
            request_id="req_review_unvalidated_update",
            expected_rule_set_id="S0_batch_baseline",
            artifact_type="batch_changes",
            summary="Batch: 0 aliases, 1 leagues, 0 market rules",
            payload=payload,
        ),
        _admin(),
    )
    view = svc.get_review(prop.proposal_id)
    assert view["headline"] == "Update 1 league."
    assert view["change_groups"]["leagues"]["modified_count"] == 1


def test_review_update_existing_league_shows_book_delta():
    svc = ProposalService(_seed())
    payload = BatchChangesPayload(
        leagues=[
            MappingLeaguePayload(
                league="lol",
                sport="esports",
                optic_league_id="league-of-legends",
                exchanges=[
                    ExchangePin(sportsbook="px", parser_profile="px_generic_v1"),
                    ExchangePin(
                        sportsbook="optic",
                        parser_profile="optic_standard_v1",
                        source_league_id="league-of-legends",
                    ),
                ],
                notes="From Rules: update lol",
            )
        ],
    )
    prop = svc.propose(
        ProposeRequest(
            request_id="req_review_update_league",
            expected_rule_set_id="S0_batch_baseline",
            artifact_type="batch_changes",
            summary="Batch: 0 aliases, 1 leagues, 0 market rules",
            payload=payload,
        ),
        _admin(),
    )
    svc.validate(prop.proposal_id, _admin())
    calls = {"n": 0}
    original = svc.store.entities_for

    def wrapped(rule_set_id: str):
        calls["n"] += 1
        return original(rule_set_id)

    svc.store.entities_for = wrapped  # type: ignore[method-assign]
    view = svc.get_review(prop.proposal_id)
    assert calls["n"] == 0
    assert view["headline"] == "Update 1 league."
    assert view["change_groups"]["leagues"]["modified_count"] == 1
    assert view["change_groups"]["leagues"]["added_count"] == 0
    line = view["change_groups"]["leagues"]["lines"][0]
    assert "Enable Optic" in line
    assert any(ref.startswith("optic:id:") for ref in view["evidence"])
    assert any(ref.startswith("note:") for ref in view["evidence"])
    queue = svc.list_review()
    assert queue[0]["headline"] == "Update 1 league."
    assert queue[0]["changes"] is None
