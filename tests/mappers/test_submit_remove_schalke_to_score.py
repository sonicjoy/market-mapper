"""Schalke to-score-first leftover is a Cart-gated alias delete."""

from __future__ import annotations

from mappers.control_plane.pin_flow import draft_and_verify_remove
from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.store import InMemoryStore
from scripts.submit_remove_schalke_to_score import ALIAS, KEY, LEAGUE, NAME, _pin, removal


def _store() -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0_s04",
        entities=[
            EntityRow(
                league=LEAGUE,
                entity_type="team",
                canonical_key=KEY,
                canonical_name=NAME,
                aliases=[
                    {
                        "sportsbook": "polymarket",
                        "alias_kind": "name",
                        "alias_value": ALIAS,
                    },
                    {
                        "sportsbook": "optic",
                        "alias_kind": "external_id",
                        "alias_value": "oid-s04",
                    },
                ],
            ),
        ],
        leagues=[
            LeagueRow(
                league=LEAGUE,
                sport="soccer",
                optic_league_id="germany_-_bundesliga",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96,
                enabled=True,
                output_order=[],
                exchanges=[],
            ),
        ],
        activate=True,
    )
    return store


def test_removal_pin_is_delete_on_s04() -> None:
    row = removal()
    assert row.league == LEAGUE
    assert row.canonical_key == KEY
    assert row.aliases[0].remove is True
    assert row.aliases[0].alias_value == ALIAS


def test_draft_and_verify_remove_keeps_live_selection_alias() -> None:
    staged = draft_and_verify_remove(_store(), _pin())
    assert staged["ok"] is True
    assert staged["blockers"] == []
    assert staged["pins"][0]["aliases"][0]["remove"] is True
