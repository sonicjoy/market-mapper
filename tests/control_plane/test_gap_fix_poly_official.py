"""Official Polymarket Path 2 harvest (injected BQ; no live network)."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.rows import LeagueRow
from tests.control_plane.test_gap_fix import (
    _optic_row,
    _poly_us_league,
    _soccer_store,
    _store,
    _us_event,
)


def _official_event(prefix: str, question: str, day: str = "2026-08-29") -> dict[str, Any]:
    return {"prefix": prefix, "question": question, "date": day}


def _poly_official_league(slug: str, optic: str, prefix: str) -> LeagueRow:
    return LeagueRow(
        league=slug,
        sport="soccer",
        optic_league_id=optic,
        extra_optic_league_ids=[],
        fixture_source="api",
        fixture_horizon_hours=96.0,
        enabled=True,
        output_order=[],
        exchanges=[
            {
                "sportsbook": "polymarket",
                "enabled": True,
                "parser_profile": "poly_generic_v1",
                "source_league_id": optic,
                "settings": {
                    "slug_prefix": prefix,
                    "optic_league_id": optic,
                    "question_style": "mlb_suffix",
                },
            }
        ],
    )


def _la_liga_optic() -> list[dict[str, Any]]:
    return [
        _optic_row(
            "spain_-_la_liga", "VCFC", "Valencia CF", "oid-val",
            "RBB", "Real Betis", "oid-bet",
        )
    ]


def _val_bet_question(prefix: str) -> list[dict[str, Any]]:
    return [_official_event(prefix, "Will Valencia CF beat Real Betis?")]


def _poly_ex(pin: dict[str, Any]) -> dict[str, Any]:
    return next(ex for ex in pin["exchanges"] if ex["sportsbook"] == "polymarket")


def test_harvest_poly_enables_official_on_existing_league() -> None:
    result = harvest_gap_pins(
        _soccer_store(),
        poly_prefixes=["spa"],
        us_events_fn=list,
        official_events_fn=lambda: _val_bet_question("spa"),
        optic_rows_fn=_la_liga_optic,
    )
    leagues = [p for p in result["pins"] if p.get("kind") == "mapping_league"]
    assert len(leagues) == 1
    assert leagues[0]["league"] == "la_liga"
    poly = _poly_ex(leagues[0])
    assert poly["enabled"] is True
    assert poly["settings"]["slug_prefix"] == "spa"


def test_harvest_poly_onboards_official_unique_optic() -> None:
    result = harvest_gap_pins(
        _soccer_store(),
        poly_prefixes=["par2"],
        us_events_fn=list,
        official_events_fn=lambda: [
            _official_event("par2", "Cerro Porteno vs Guarani Asuncion"),
        ],
        optic_rows_fn=lambda: [
            _optic_row(
                "paraguay_-_division_intermedia", "CERC", "Cerro Porteno", "oid-cer",
                "GUAR", "Guarani Asuncion", "oid-gua",
            )
        ],
    )
    leagues = [p for p in result["pins"] if p.get("kind") == "mapping_league"]
    assert len(leagues) == 1
    assert leagues[0]["league"] == "paraguay_division_intermedia"
    assert leagues[0]["clone_market_rules_from"] == "la_liga"
    poly = _poly_ex(leagues[0])
    assert poly["enabled"] is True
    assert poly["settings"]["slug_prefix"] == "par2"


def test_harvest_poly_enables_official_on_us_wired_without_tickers() -> None:
    """cfb analog: US inner already on the tip, official Path 2 still empty."""
    store = _store([], [_poly_us_league("korea_k1", "korea_-_k_league_1", "kor")])
    result = harvest_gap_pins(
        store,
        poly_prefixes=["kor"],
        us_events_fn=list,
        official_events_fn=lambda: [
            _official_event("kor", "FC Seoul vs Ulsan Hyundai"),
        ],
        optic_rows_fn=lambda: [
            _optic_row(
                "korea_-_k_league_1", "SUFC", "FC Seoul", "oid-seo",
                "UHD", "Ulsan Hyundai", "oid-uls",
            )
        ],
    )
    leagues = [p for p in result["pins"] if p.get("kind") == "mapping_league"]
    assert len(leagues) == 1
    assert leagues[0]["league"] == "korea_k1"
    assert _poly_ex(leagues[0])["settings"]["slug_prefix"] == "kor"
    assert not any(row["key"] == "kor" for row in result["skipped"])


def test_harvest_poly_official_already_wired_is_silent() -> None:
    store = _store([], [_poly_official_league("la_liga", "spain_-_la_liga", "spa")])
    result = harvest_gap_pins(
        store,
        poly_prefixes=["spa"],
        us_events_fn=list,
        official_events_fn=lambda: _val_bet_question("spa"),
        optic_rows_fn=_la_liga_optic,
    )
    assert result["pins"] == []
    assert not any(row["key"] == "spa" for row in result["skipped"])


def test_harvest_poly_official_wrong_prefix_collision() -> None:
    store = _store([], [_poly_official_league("la_liga", "spain_-_la_liga", "bun")])
    result = harvest_gap_pins(
        store,
        poly_prefixes=["spa"],
        us_events_fn=list,
        official_events_fn=lambda: _val_bet_question("spa"),
        optic_rows_fn=_la_liga_optic,
    )
    assert result["pins"] == []
    by_key = {row["key"]: row["reason"] for row in result["skipped"] if row.get("book") == "polymarket"}
    assert by_key["spa"] == "wrong_prefix_collision"


def test_harvest_poly_us_onboard_patches_official_prefix() -> None:
    result = harvest_gap_pins(
        _soccer_store(),
        poly_prefixes=["par2"],
        us_events_fn=lambda: [_us_event("par2", "cer", "gua")],
        official_events_fn=lambda: [
            _official_event("par2", "Cerro Porteno vs Guarani Asuncion"),
        ],
        optic_rows_fn=lambda: [
            _optic_row(
                "paraguay_-_division_intermedia", "CERC", "Cerro Porteno", "oid-cer",
                "GUAR", "Guarani Asuncion", "oid-gua",
            )
        ],
    )
    leagues = [p for p in result["pins"] if p.get("kind") == "mapping_league"]
    assert len(leagues) == 1
    usa = next(ex for ex in leagues[0]["exchanges"] if ex["sportsbook"] == "polymarket_usa")
    assert usa["source_league_id"] == "par2"
    poly = _poly_ex(leagues[0])
    assert poly["enabled"] is True
    assert poly["settings"]["slug_prefix"] == "par2"
