"""League exchange id harvest kernel."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mappers.control_plane.harvest_league_ids import (
    exchange_source_on_tip,
    harvest_exchange_source_id,
)
from mappers.control_plane.harvest_league_ids_common import wired_probe_row
from mappers.control_plane.harvest_league_ids_live import harvest_crypto_meta
from mappers.control_plane.ops_suggest import SuggestOpsMixin
from mappers.control_plane.rows import LeagueRow
from mappers.control_plane.store import InMemoryStore


def test_exchange_source_on_tip_ignores_kalshi_prefix_setting() -> None:
    row = SimpleNamespace(
        exchanges=[
            {
                "sportsbook": "kalshi",
                "enabled": True,
                "source_league_id": "",
                "settings": {"prefix": "KXEPL"},
            }
        ]
    )
    assert exchange_source_on_tip(row, "kalshi") == ""


def test_kalshi_is_not_a_harvest_book() -> None:
    out = harvest_exchange_source_id(
        InMemoryStore(environment="test"),
        league="epl",
        sport="soccer",
        optic_league_id="england_-_premier_league",
        sportsbook="kalshi",
        fixtures_fn=lambda *_a, **_k: [],
    )
    assert out["ok"] is False
    assert out["error"] == "unknown sportsbook"


def test_wired_probe_row_preserves_crypto_settings() -> None:
    row = SimpleNamespace(
        exchanges=[
            {
                "sportsbook": "crypto.com",
                "enabled": True,
                "source_league_id": "UCL",
                "settings": {"league": "UCL", "sport_grouping": "SOCCER"},
            }
        ]
    )
    wired = wired_probe_row(row, "crypto.com")
    assert wired is not None
    assert wired["settings"]["sport_grouping"] == "SOCCER"


def test_optic_harvest_enables_without_fixtures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.harvest_league_ids.fetch_league_fixtures",
        lambda *_a, **_k: ([], None),
    )
    out = harvest_exchange_source_id(
        InMemoryStore(environment="test"),
        league="epl",
        sport="soccer",
        optic_league_id="england_-_premier_league",
        sportsbook="optic",
    )
    assert out["evidence"] is True
    assert out["source"] == "england_-_premier_league"


def test_crypto_harvest_returns_archive_meta() -> None:
    out = harvest_crypto_meta("ucl", "uefa_-_champions_league", [], sport="soccer")
    assert out["evidence"] is True
    assert out["source"] == "UCL"
    assert out["settings"] == {"league": "UCL", "sport_grouping": "SOCCER"}


def test_underdog_harvest_maps_nfl_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.harvest_league_ids.fetch_league_fixtures",
        lambda *_a, **_k: ([], None),
    )
    out = harvest_exchange_source_id(
        InMemoryStore(environment="test"),
        league="nfl",
        sport="football",
        optic_league_id="nfl",
        sportsbook="underdog",
    )
    assert out["evidence"] is True
    assert out["source"] == "NFL"
    assert out["settings"]["league"] == "NFL"


def test_underdog_harvest_uses_optic_league_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.harvest_league_ids.fetch_league_fixtures",
        lambda *_a, **_k: ([], None),
    )
    out = harvest_exchange_source_id(
        InMemoryStore(environment="test"),
        league="college_football",
        sport="football",
        optic_league_id="ncaaf",
        sportsbook="underdog",
    )
    assert out["evidence"] is True
    assert out["source"] == "NCAAMFB"


def test_crypto_harvest_unknown_slug_stays_unevidenced() -> None:
    out = harvest_crypto_meta("brand_new_slug", "some_optic_id", [], sport="soccer")
    assert out["evidence"] is False


def test_polymarket_harvest_does_not_invent_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mappers.control_plane.harvest_league_ids.fetch_league_fixtures",
        lambda *_a, **_k: ([{"id": "fx-1"}], None),
    )
    monkeypatch.setattr(
        "mappers.control_plane.harvest_league_ids_live._recent_poly_prefixes",
        list,
    )
    monkeypatch.setattr(
        "mappers.control_plane.harvest_league_ids_live._poly_prefix_hits",
        lambda *_a, **_k: [],
    )
    out = harvest_exchange_source_id(
        InMemoryStore(environment="test"),
        league="epl",
        sport="soccer",
        optic_league_id="england_-_premier_league",
        sportsbook="polymarket",
    )
    assert out["evidence"] is False
    assert "source" not in out or not out.get("source")


def test_editor_harvest_returns_wired_px_tournament_from_tip() -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
        leagues=[
            LeagueRow(
                league="international_friendlies",
                sport="soccer",
                optic_league_id="international_-_friendlies",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "px",
                        "enabled": True,
                        "parser_profile": "px_generic_v1",
                        "source_league_id": "648",
                        "settings": {"tournament_id": "648"},
                    }
                ],
            )
        ],
        activate=True,
    )

    class _Svc(SuggestOpsMixin):
        def __init__(self, tip_store: InMemoryStore) -> None:
            self.store = tip_store

    body = SimpleNamespace(
        league="international_friendlies",
        sport="soccer",
        optic_league_id="international_-_friendlies",
        sportsbook="px",
        fixture_horizon_hours=None,
    )
    out = _Svc(store).entry_league_harvest_id(body)
    assert out["evidence"] is True
    assert out["source"] == "648"
    assert out["settings"]["tournament_id"] == "648"
    assert out.get("note") == "already wired on tip"


def test_probe_skips_wired_tip_row(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryStore(environment="test", allow_activate=True)
    store.seed_rule_set(
        rule_set_id="S0",
        entities=[],
        leagues=[
            LeagueRow(
                league="epl",
                sport="soccer",
                optic_league_id="england_-_premier_league",
                extra_optic_league_ids=[],
                fixture_source="api",
                fixture_horizon_hours=96.0,
                enabled=True,
                output_order=[],
                exchanges=[
                    {
                        "sportsbook": "px",
                        "enabled": True,
                        "parser_profile": "px_generic_v1",
                        "source_league_id": "648",
                        "settings": {"tournament_id": "648"},
                    }
                ],
            )
        ],
        activate=True,
    )
    from mappers.control_plane.chat_tools_skill import probe_exchange_league

    out = probe_exchange_league(store, "epl", "px", optic_league_id="england_-_premier_league")
    assert out["evidence"] is True
    assert out["source"] == "648"
    assert out["settings"]["tournament_id"] == "648"
    assert out.get("skipped_probe") is True
