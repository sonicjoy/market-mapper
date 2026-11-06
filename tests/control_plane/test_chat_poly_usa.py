"""Mapper Chat must not treat Optic id as Polymarket US inner league code."""

from __future__ import annotations

import pytest

from mappers.control_plane.chat_tools_skill import probe_exchange_league
from mappers.control_plane.rows import LeagueRow
from mappers.control_plane.store import InMemoryStore


def _ncaaf_usa_store() -> InMemoryStore:
    league = LeagueRow(
        league="ncaaf",
        sport="football",
        optic_league_id="ncaaf",
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[
            {
                "sportsbook": "polymarket_usa",
                "enabled": True,
                "settings": {"slug_prefix": "cfb"},
            }
        ],
    )
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(rule_set_id="S0_ncaaf_usa", entities=[], leagues=[league], activate=True)
    return store


def test_probe_polymarket_usa_uses_override_not_optic_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _ncaaf_usa_store()
    out = probe_exchange_league(
        store,
        "ncaaf",
        "polymarket_usa",
        optic_league_id="ncaaf",
    )
    assert out["ok"] is True
    assert out["evidence"] is True
    assert out["source"] == "cfb"
    assert out["source"] != "ncaaf"


def test_probe_polymarket_usa_without_override_stays_unevidenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.harvest_league_ids_live.fetch_close_us_events",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "mappers.control_plane.harvest_league_ids_live._recent_us_inners",
        lambda *_a, **_k: [],
    )
    store = InMemoryStore(environment="test", allow_activate=True)
    monkeypatch.setattr(
        "mappers.control_plane.chat_tools_skill.harvest_exchange_source_id",
        lambda *_a, **_k: {
            "ok": True,
            "book": "polymarket_usa",
            "evidence": False,
        },
    )
    out = probe_exchange_league(
        store,
        "argentina_primera_nacional",
        "polymarket_usa",
        optic_league_id="argentina_-_primera_nacional",
    )
    assert out["ok"] is True
    assert out["evidence"] is False
