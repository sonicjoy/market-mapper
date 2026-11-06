"""Shared tip-store fixtures for gap-harvest tests (no live network).

Leagues carry no Kalshi exchange row and teams no Kalshi code alias: Kalshi
maps from its own typed fields, so the tip holds nothing for it.
"""

from __future__ import annotations

from typing import Any

from mappers.control_plane.rows import EntityRow, LeagueRow
from mappers.control_plane.store import InMemoryStore


def _league(slug: str, optic: str, *, sport: str = "soccer") -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport=sport,
        optic_league_id=optic,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[],
    )


def _team(league: str, key: str, name: str, aliases: list[dict[str, Any]] | None = None) -> EntityRow:
    return EntityRow(
        league=league,
        entity_type="team",
        canonical_key=key,
        canonical_name=name,
        aliases=list(aliases or []),
    )


def _store(entities: list[EntityRow], leagues: list[LeagueRow]) -> InMemoryStore:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(rule_set_id="S0", entities=entities, leagues=leagues, activate=True)
    return store


def _soccer_store() -> InMemoryStore:
    return _store(
        [
            _team("la_liga", "VAL", "Valencia"),
            _team("la_liga", "BET", "Real Betis"),
            _team("itf_men", "WIS", "Max Wiskandt"),
            _team("itf_women", "GAU", "Coco Gauff"),
            _team("international_club_friendlies", "VI2", "Villarreal B"),
        ],
        [
            _league("la_liga", "spain_-_la_liga"),
            _league("itf_men", "itf_men"),
            _league("itf_women", "itf_women"),
            _league("international_club_friendlies", "club_friendly_games"),
        ],
    )


def _fixtures(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": "fx-val-bet",
            "start_date": "2026-08-25T18:00:00Z",
            "home_competitors": [{"id": "oid-val", "name": "Valencia CF"}],
            "away_competitors": [{"id": "oid-bet", "name": "Real Betis"}],
        }
    ]
