"""Payload building for scripts/submit_enable_novig_soccer_leagues.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from mappers.control_plane.rows import LeagueRow, MarketRuleRow

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "submit_enable_novig_soccer_leagues.py"
_SPEC = importlib.util.spec_from_file_location("submit_enable_novig_soccer_leagues", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
script = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(script)

_LEAGUE = "uefa_nations_league"
_EXCHANGES = [
    {"sportsbook": "optic", "enabled": True, "parser_profile": "optic_standard_v1",
     "source_league_id": "uefa_-_nations_league", "settings": {"entity_type": "team"}},
    {"sportsbook": "kalshi", "enabled": True, "parser_profile": "kalshi_generic_v1",
     "source_league_id": "KXUEFANL", "settings": {"prefix": "KXUEFANL"}},
]


def _league(exchanges: list[dict]) -> LeagueRow:
    return LeagueRow(
        league=_LEAGUE, sport="soccer", optic_league_id="uefa_-_nations_league",
        extra_optic_league_ids=[], fixture_source="api", fixture_horizon_hours=168.0,
        enabled=True, output_order=[], exchanges=exchanges,
        settings={"entity_type": "team", "alias_enforcement": "raise"},
    )


def _rule(key: str) -> MarketRuleRow:
    return MarketRuleRow(
        rule_id=f"{_LEAGUE}-optic-{key}", league=_LEAGUE, sportsbook="optic",
        rule_kind="taxonomy", source_key_type="optic_market", source_key=key,
        action="map", canonical_market_type="btts", priority=100,
        enabled=True, confidence="manual",
    )


def test_prod_adds_only_the_novig_exchange() -> None:
    leagues, rules = [_league(list(_EXCHANGES))], [_rule("both_teams_to_score")]
    (plan,) = script.build_payloads(leagues, rules, leagues, rules)
    assert plan.league == _LEAGUE and plan.market_rules == []
    assert [e.sportsbook for e in plan.exchanges] == ["optic", "kalshi", "novig"]
    novig = plan.exchanges[-1]
    assert novig.enabled and novig.parser_profile == "novig_generic_v1"
    assert novig.settings == {"league": "UEFA Nations League"}
    assert plan.exchanges[1].settings == {"prefix": "KXUEFANL"}


def test_disabled_novig_entry_is_switched_on_not_duplicated() -> None:
    off = {"sportsbook": "novig", "enabled": False, "parser_profile": "novig_generic_v1",
           "source_league_id": None, "settings": {}}
    leagues = [_league([*_EXCHANGES, off])]
    (plan,) = script.build_payloads(leagues, [], leagues, [])
    novig = [e for e in plan.exchanges if e.sportsbook == "novig"]
    assert len(novig) == 1 and novig[0].enabled
    assert novig[0].settings == {"league": "UEFA Nations League"}


def test_env_missing_rules_come_from_prod() -> None:
    prod = [_league(list(_EXCHANGES))]
    rules = [_rule("both_teams_to_score"), _rule("moneyline")]
    (plan,) = script.build_payloads(prod, rules, prod, [_rule("moneyline")])
    assert [r.source_key for r in plan.market_rules] == ["both_teams_to_score"]


def test_already_live_league_is_skipped() -> None:
    live = {"sportsbook": "novig", "enabled": True, "parser_profile": "novig_generic_v1",
            "source_league_id": "UEFA Nations League",
            "settings": {"league": "UEFA Nations League"}}
    leagues = [_league([*_EXCHANGES, live])]
    assert script.build_payloads(leagues, [], leagues, []) == []
