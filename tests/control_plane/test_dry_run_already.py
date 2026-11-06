"""Verify blocks when proposed rules already match the current tip."""

from __future__ import annotations

from mappers.control_plane.batch_apply import dry_run_batch
from mappers.control_plane.change_view import snapshot_change_groups
from mappers.control_plane.dry_run import thin_dry_run
from mappers.control_plane.dry_run_already import NOOP_BLOCKER
from mappers.control_plane.dry_run_league import apply_league_payload, thin_dry_run_league
from mappers.control_plane.dry_run_market_rules import thin_dry_run_market_rules
from mappers.control_plane.league_review import league_card_copy
from mappers.control_plane.models import (
    AliasPin,
    BatchChangesPayload,
    EntityAliasPayload,
    ExchangePin,
    MappingLeaguePayload,
    MappingMarketRulesPayload,
    MarketRulePin,
)
from mappers.control_plane.store import EntityRow, InMemoryStore, LeagueRow, MarketRuleRow


def _league() -> LeagueRow:
    return LeagueRow(
        league="la_liga",
        sport="soccer",
        optic_league_id="la-liga",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96,
        enabled=True,
        output_order=[],
        exchanges=[{"sportsbook": "px", "parser_profile": "px_generic_v1"}],
    )


def _rule(*, action: str = "map", canonical: str | None = "1h_btts") -> MarketRuleRow:
    return MarketRuleRow(
        rule_id="mr-1hbtts",
        league="la_liga",
        sportsbook="px",
        rule_kind="taxonomy",
        source_key_type="market_name",
        source_key="1HBTTS",
        action=action,
        canonical_market_type=canonical,
        priority=100,
        enabled=True,
        confidence="manual",
    )


def _pin(*, action: str = "map", canonical: str | None = "1h_btts") -> MarketRulePin:
    return MarketRulePin(
        sportsbook="px",
        rule_kind="taxonomy",
        source_key_type="market_name",
        source_key="1HBTTS",
        action=action,
        canonical_market_type=canonical,
    )


def _league_payload() -> MappingLeaguePayload:
    return MappingLeaguePayload(
        league="la_liga",
        sport="soccer",
        optic_league_id="la-liga",
        exchanges=[ExchangePin(sportsbook="px", parser_profile="px_generic_v1")],
    )


def test_market_rule_already_live_is_blocked() -> None:
    dry = thin_dry_run_market_rules(
        [_league()],
        [_rule()],
        MappingMarketRulesPayload(
            league="la_liga",
            rules=[_pin()],
        ),
    )
    assert dry["ok"] is False
    assert NOOP_BLOCKER in dry["blockers"]
    assert any("Already live" in note for note in dry["warnings"])


def test_same_canonical_line_and_citation_is_a_change() -> None:
    pin = _pin().model_copy(update={
        "line_offset": -0.5,
        "yes_side": "under",
        "official_description": "before Round 5 means Rounds 1-4",
        "citation_url": "https://assets.kalshi.com/contract_terms/FIGHTROUNDCOUNT.pdf",
    })
    dry = thin_dry_run_market_rules(
        [_league()],
        [_rule()],
        MappingMarketRulesPayload(league="la_liga", rules=[pin]),
    )
    assert dry["ok"] is True
    assert dry["change_count"] == 1
    assert any("official text changes" in note for note in dry["warnings"])


def test_market_rule_ignore_to_map_is_allowed() -> None:
    dry = thin_dry_run_market_rules(
        [_league()],
        [_rule(action="ignore", canonical=None)],
        MappingMarketRulesPayload(league="la_liga", rules=[_pin()]),
    )
    assert dry["ok"] is True
    assert dry["change_count"] == 1
    assert any("ignored" in note and "1h_btts" in note for note in dry["warnings"])


def test_league_already_live_is_blocked() -> None:
    dry = thin_dry_run_league([_league()], _league_payload())
    assert dry["ok"] is False
    assert NOOP_BLOCKER in dry["blockers"]


def test_league_optic_change_is_allowed() -> None:
    payload = _league_payload().model_copy(update={"optic_league_id": "la-liga-v2"})
    dry = thin_dry_run_league([_league()], payload)
    assert dry["ok"] is True
    assert dry["updating"] is True


def test_alias_already_live_is_blocked() -> None:
    entities = [
        EntityRow(
            league="lol",
            entity_type="team",
            canonical_key="T1",
            canonical_name="T1",
            aliases=[{"sportsbook": "px", "alias_kind": "code", "alias_value": "T1"}],
        )
    ]
    dry = thin_dry_run(
        entities,
        EntityAliasPayload(
            league="lol",
            canonical_key="T1",
            canonical_name="T1",
            aliases=[AliasPin(sportsbook="px", alias_kind="code", alias_value="T1")],
        ),
    )
    assert dry["ok"] is False
    assert NOOP_BLOCKER in dry["blockers"]


def test_batch_all_live_is_blocked() -> None:
    store = InMemoryStore()
    store.seed_rule_set(
        rule_set_id="S0_live",
        entities=[],
        leagues=[_league()],
        market_rules=[_rule()],
        activate=True,
    )
    dry = dry_run_batch(
        store,
        "S0_live",
        BatchChangesPayload(market_rules=[MappingMarketRulesPayload(league="la_liga", rules=[_pin()])]),
    )
    assert dry["ok"] is False
    assert NOOP_BLOCKER in dry["blockers"]


def test_batch_mixed_live_and_new_is_allowed() -> None:
    store = InMemoryStore()
    store.seed_rule_set(
        rule_set_id="S0_live",
        entities=[],
        leagues=[_league()],
        market_rules=[_rule()],
        activate=True,
    )
    dry = dry_run_batch(
        store,
        "S0_live",
        BatchChangesPayload(
            leagues=[
                MappingLeaguePayload(
                    league="demo_a",
                    sport="soccer",
                    optic_league_id="demo-a",
                    exchanges=[ExchangePin(sportsbook="px", parser_profile="px_generic_v1")],
                )
            ],
            market_rules=[MappingMarketRulesPayload(league="la_liga", rules=[_pin()])],
        ),
    )
    assert dry["ok"] is True
    assert NOOP_BLOCKER not in dry["blockers"]


def test_review_ignores_confidence_only_rule_diff() -> None:
    parent = [_rule(action="map", canonical="1h_btts")]
    child = [_rule(action="map", canonical="1h_btts")]
    child[0].confidence = "harvest"
    groups = snapshot_change_groups([], [], [], [], parent, child)
    assert groups["market_rules"]["modified_count"] == 0


def test_league_update_omitted_horizon_keeps_tip_168() -> None:
    row = LeagueRow(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=168,
        enabled=True,
        output_order=[],
        exchanges=[
            {
                "sportsbook": "optic",
                "parser_profile": "optic_standard_v1",
                "enabled": True,
            }
        ],
    )
    payload = MappingLeaguePayload(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        exchanges=[
            ExchangePin(
                sportsbook="optic",
                parser_profile="optic_standard_v1",
                enabled=True,
            ),
            ExchangePin(
                sportsbook="novig",
                parser_profile="novig_generic_v1",
                enabled=True,
            ),
        ],
    )
    applied = apply_league_payload([row], payload)
    nfl = next(lg for lg in applied if lg.league == "nfl")
    assert nfl.fixture_horizon_hours == 168.0
    _reason, diff = league_card_copy(payload, row)
    assert not any("horizon" in bit for bit in diff["other"])


def test_league_update_explicit_horizon_still_shows() -> None:
    row = LeagueRow(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=168,
        enabled=True,
        output_order=[],
        exchanges=[{"sportsbook": "optic", "parser_profile": "optic_standard_v1"}],
    )
    payload = MappingLeaguePayload(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        fixture_horizon_hours=96.0,
        exchanges=[
            ExchangePin(sportsbook="optic", parser_profile="optic_standard_v1"),
        ],
    )
    _reason, diff = league_card_copy(payload, row)
    assert any("168" in bit and "96" in bit for bit in diff["other"])


def test_league_update_omitted_extra_optic_and_order_keep_tip() -> None:
    row = LeagueRow(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        extra_optic_league_ids=["ncaaf-bowl"],
        fixture_source="api",
        fixture_horizon_hours=168,
        enabled=True,
        output_order=["moneyline", "point_spread"],
        exchanges=[{"sportsbook": "optic", "parser_profile": "optic_standard_v1"}],
    )
    payload = MappingLeaguePayload(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        exchanges=[
            ExchangePin(sportsbook="optic", parser_profile="optic_standard_v1"),
            ExchangePin(sportsbook="novig", parser_profile="novig_generic_v1"),
        ],
    )
    applied = apply_league_payload([row], payload)
    nfl = next(lg for lg in applied if lg.league == "nfl")
    assert nfl.extra_optic_league_ids == ["ncaaf-bowl"]
    assert nfl.output_order == ["moneyline", "point_spread"]
    assert nfl.enabled is True
    _reason, diff = league_card_copy(payload, row)
    assert not any("extra optic" in bit for bit in diff["other"])
    assert not any("output order" in bit for bit in diff["other"])


def test_league_update_explicit_empty_extra_optic_shows() -> None:
    row = LeagueRow(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        extra_optic_league_ids=["ncaaf-bowl"],
        fixture_source="api",
        fixture_horizon_hours=168,
        enabled=True,
        output_order=["moneyline"],
        exchanges=[{"sportsbook": "optic", "parser_profile": "optic_standard_v1"}],
    )
    payload = MappingLeaguePayload(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        extra_optic_league_ids=[],
        output_order=[],
        exchanges=[
            ExchangePin(sportsbook="optic", parser_profile="optic_standard_v1"),
        ],
    )
    applied = apply_league_payload([row], payload)
    nfl = next(lg for lg in applied if lg.league == "nfl")
    assert nfl.extra_optic_league_ids == []
    assert nfl.output_order == []
    _reason, diff = league_card_copy(payload, row)
    assert any("extra optic" in bit for bit in diff["other"])
    assert any("output order" in bit for bit in diff["other"])


def test_league_update_omitted_enabled_keeps_disabled_tip() -> None:
    row = LeagueRow(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=168,
        enabled=False,
        output_order=[],
        exchanges=[{"sportsbook": "optic", "parser_profile": "optic_standard_v1"}],
    )
    payload = MappingLeaguePayload(
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        exchanges=[
            ExchangePin(sportsbook="optic", parser_profile="optic_standard_v1"),
        ],
    )
    applied = apply_league_payload([row], payload)
    nfl = next(lg for lg in applied if lg.league == "nfl")
    assert nfl.enabled is False
    _reason, diff = league_card_copy(payload, row)
    assert "enable league" not in diff["other"]
    assert "disable league" not in diff["other"]
