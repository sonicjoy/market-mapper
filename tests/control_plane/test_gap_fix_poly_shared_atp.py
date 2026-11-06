"""Polymarket US inner `atp` is shared by ATP and ATP Challenger."""

from __future__ import annotations

from types import SimpleNamespace

from mappers.control_plane.gap_fix import harvest_gap_pins
from mappers.control_plane.gap_fix_poly import harvest_poly_side
from mappers.seed.poly_usa_exchange import us_inner_owner_ok, us_inner_targets
from tests.control_plane.test_gap_fix import (
    _optic_row,
    _poly_us_league,
    _store,
    _us_event,
)


def test_us_inner_owner_ok_allows_atp_family() -> None:
    atp = SimpleNamespace(league="atp")
    chal = SimpleNamespace(league="atp_challenger")
    assert us_inner_owner_ok("atp", [atp])
    assert us_inner_owner_ok("atp", [atp, chal])
    assert not us_inner_owner_ok("atp", [atp, SimpleNamespace(league="wta")])
    assert not us_inner_owner_ok("kor", [_poly_us_league("korea_k1", "k1", "kor"),
                                         _poly_us_league("korea_k2", "k2", "kor")])


def test_us_inner_targets_includes_disabled_challenger() -> None:
    atp = _poly_us_league("atp", "atp", "atp")
    chal = _poly_us_league("atp_challenger", "atp_challenger", "", enabled=False)
    got = us_inner_targets("atp", [atp], [atp, chal])
    assert [row.league for row in got] == ["atp", "atp_challenger"]
    assert us_inner_targets("kor", [atp], [atp, chal]) == [atp]


def test_harvest_poly_skips_unrelated_us_code_collision() -> None:
    store = _store([], [
        _poly_us_league("korea_k1", "korea_-_k_league_1", "kor"),
        _poly_us_league("korea_k2", "korea_-_k_league_2", "kor"),
    ])
    pins, skipped = harvest_poly_side(
        store, ["kor"], [_us_event("kor", "a", "b")], [],
    )
    assert pins == []
    assert skipped == [{"book": "polymarket", "key": "kor", "reason": "us_code_collision"}]


def test_harvest_poly_shared_atp_inner_enables_challenger() -> None:
    """US-off Challenger still gets the inner-atp pin plus name-matched aliases."""
    store = _store([], [
        _poly_us_league("atp", "atp", "atp"),
        _poly_us_league("atp_challenger", "atp_challenger", "", enabled=False),
    ])
    result = harvest_gap_pins(
        store,
        poly_prefixes=["atp"],
        us_events_fn=lambda: [_us_event(
            "atp", "fajsun", "alegal",
            title="Fajing Sun vs. Alexis Galarneau",
            team_names={"fajsun": "Fajing Sun", "alegal": "Alexis Galarneau"},
        )],
        official_events_fn=list,
        optic_rows_fn=lambda: [_optic_row(
            "atp_challenger", "", "Fajing Sun", "9FA08779B33B",
            "", "Alexis Galarneau", "329DCEB3CD29",
        )],
    )
    leagues = [p for p in result["pins"] if p.get("kind") == "mapping_league"]
    assert [p["league"] for p in leagues] == ["atp_challenger"]
    usa = next(ex for ex in leagues[0]["exchanges"] if ex["sportsbook"] == "polymarket_usa")
    assert usa["enabled"] is True
    assert usa["source_league_id"] == "atp"
    values = {a["alias_value"] for p in result["pins"] for a in p.get("aliases") or []}
    assert "fajsun" in values
    assert "alegal" in values
    assert "9FA08779B33B" in values
    assert result["skipped"] == []


def test_harvest_poly_shared_atp_inner_does_not_enable_without_bind() -> None:
    """Main-tour ATP events must not enable Challenger US with no Challenger bind."""
    store = _store([], [
        _poly_us_league("atp", "atp", "atp"),
        _poly_us_league("atp_challenger", "atp_challenger", "", enabled=False),
    ])
    result = harvest_gap_pins(
        store,
        poly_prefixes=["atp"],
        us_events_fn=lambda: [_us_event(
            "atp", "jsinxx", "calcar",
            title="Jannik Sinner vs. Carlos Alcaraz",
            team_names={"jsinxx": "Jannik Sinner", "calcar": "Carlos Alcaraz"},
        )],
        official_events_fn=list,
        optic_rows_fn=lambda: [_optic_row(
            "atp", "", "Jannik Sinner", "oid-sin",
            "", "Carlos Alcaraz", "oid-alc",
        )],
    )
    assert not any(p.get("kind") == "mapping_league" for p in result["pins"])
    values = {a["alias_value"] for p in result["pins"] for a in p.get("aliases") or []}
    assert "jsinxx" in values
    assert result["skipped"] == []


def test_harvest_poly_shared_atp_inner_two_owners_pin_matching_tour() -> None:
    """Both tours may own inner atp; each event binds only its Optic book."""
    store = _store([], [
        _poly_us_league("atp", "atp", "atp"),
        _poly_us_league("atp_challenger", "atp_challenger", "atp"),
    ])
    result = harvest_gap_pins(
        store,
        poly_prefixes=["atp"],
        us_events_fn=lambda: [
            _us_event(
                "atp", "jsinxx", "calcar",
                title="Jannik Sinner vs. Carlos Alcaraz",
                team_names={"jsinxx": "Jannik Sinner", "calcar": "Carlos Alcaraz"},
            ),
            _us_event(
                "atp", "fajsun", "alegal",
                title="Fajing Sun vs. Alexis Galarneau",
                team_names={"fajsun": "Fajing Sun", "alegal": "Alexis Galarneau"},
            ),
        ],
        official_events_fn=list,
        optic_rows_fn=lambda: [
            _optic_row(
                "atp", "", "Jannik Sinner", "oid-sin",
                "", "Carlos Alcaraz", "oid-alc",
            ),
            _optic_row(
                "atp_challenger", "", "Fajing Sun", "oid-sun",
                "", "Alexis Galarneau", "oid-gal",
            ),
        ],
    )
    by_league: dict[str, set[str]] = {}
    for pin in result["pins"]:
        if pin.get("kind") != "entity_alias":
            continue
        by_league.setdefault(str(pin["league"]), set()).update(
            str(a["alias_value"]) for a in pin.get("aliases") or []
        )
    assert "jsinxx" in by_league["atp"]
    assert "fajsun" in by_league["atp_challenger"]
    assert "fajsun" not in by_league["atp"]
    assert "jsinxx" not in by_league["atp_challenger"]
    assert not any(p.get("kind") == "mapping_league" for p in result["pins"])
    assert result["skipped"] == []


def test_harvest_poly_challenger_skips_shared_surname_code() -> None:
    """Francesco Ferrari must not pin onto Gianmarco Ferrari (GFIS)."""
    store = _store([], [
        _poly_us_league("atp_challenger", "atp_challenger", "atp"),
    ])
    result = harvest_gap_pins(
        store,
        poly_prefixes=["atp"],
        us_events_fn=lambda: [_us_event(
            "atp", "thiwil", "frafer",
            day="2026-09-08",
            title="Thiago Seyboth Wild vs. Francesco Ferrari",
            team_names={
                "thiwil": "Thiago Seyboth Wild",
                "frafer": "Francesco Ferrari",
            },
        )],
        official_events_fn=list,
        optic_rows_fn=lambda: [_optic_row(
            "atp_challenger", "TSW", "Thiago Seyboth Wild", "oid-thi",
            "GFIS", "Gianmarco Ferrari", "oid-gfi",
            day="2026-09-08",
        )],
    )
    values = {a["alias_value"] for p in result["pins"] for a in p.get("aliases") or []}
    assert "frafer" not in values
    assert "GFIS" not in values
    assert "oid-gfi" not in values
