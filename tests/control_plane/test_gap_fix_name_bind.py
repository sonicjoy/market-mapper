"""Fail-closed unique name binds for gap harvest."""

from __future__ import annotations

from mappers.control_plane.gap_fix_name_bind import (
    club_bind_name_ok,
    expand_person_pair,
    name_bind_keys,
    person_unique_hit_ok,
    unique_side,
    vs_sides,
)


def test_club_bind_name_ok_accepts_kalshi_short_labels() -> None:
    assert club_bind_name_ok("Ceuta", "AD Ceuta")
    assert club_bind_name_ok("Mechelen", "KV Mechelen")
    assert club_bind_name_ok("Anderlecht", "RSC Anderlecht")
    assert club_bind_name_ok("Bilbao", "Athletic Club Bilbao")
    assert club_bind_name_ok("Como", "Calcio Como 1907")
    assert club_bind_name_ok("Bayern", "Bayern Munich")
    assert not club_bind_name_ok("Madrid", "Real Madrid")
    assert not club_bind_name_ok("Madrid", "Atlético Madrid")
    assert not club_bind_name_ok("Valencia", "Other Valencia")
    assert not club_bind_name_ok(
        "Southern Connecticut", "Southern Connecticut State",
    )


def test_bind_keys_last_then_first_drops_year() -> None:
    assert name_bind_keys("Katarina 2001 Kuzmova", person=True) == [
        "kuzmova", "katarina",
    ]
    assert name_bind_keys("Lorenzo Lorusso", person=True) == ["lorusso", "lorenzo"]
    assert name_bind_keys("Lorusso Lorenzo", person=True) == ["lorenzo", "lorusso"]


def test_bind_keys_fold_apostrophe_and_underscore() -> None:
    assert name_bind_keys("Andrea M'chich", person=True) == ["mchich", "andrea"]
    assert name_bind_keys("andrea_mchich", person=True) == ["mchich", "andrea"]
    assert name_bind_keys("RB Leipzig") == ["leipzig"]


def test_bind_keys_surname_only_person_is_empty() -> None:
    assert name_bind_keys("Rune", person=True) == []
    assert name_bind_keys("Rune") == ["rune"]


def test_unique_side_one_token_person_does_not_bind() -> None:
    """Length is not identity: Jones is short, Ferrari is long, both surnames."""
    assert unique_side(
        "Benouaich", "Delphine Benouaich", "Sofia Montenegro", person=True,
    ) == ""
    assert unique_side(
        "Jones", "Jon Jones", "Anna Smith", person=True,
    ) == ""
    assert unique_side(
        "Ferrari", "Gianmarco Ferrari", "Thiago Seyboth Wild", person=True,
    ) == ""
    assert unique_side("Rune", "Holger Rune", "Carlos Alcaraz", person=True) == ""
    assert person_unique_hit_ok("Benouaich", "Delphine Benouaich") is False
    assert person_unique_hit_ok("Jones", "Jon Jones") is False


def test_expand_person_pair_uses_full_names_not_length() -> None:
    wins = ["Cody Gibson", "Abdul Hussein"]
    assert expand_person_pair("Gibson", "Hussein", wins) == (
        "Cody Gibson", "Abdul Hussein",
    )
    assert expand_person_pair("Jones", "Smith", ["Jon Jones", "Anna Smith"]) == (
        "Jon Jones", "Anna Smith",
    )
    assert expand_person_pair("Gibson", "Husain", wins) is None
    assert expand_person_pair("Amanda Serrano", "Lucrecia Anabella Manzur", []) == (
        "Amanda Serrano", "Lucrecia Anabella Manzur",
    )


def test_unique_side_reverse_and_apostrophe() -> None:
    assert unique_side(
        "Lorenzo Lorusso", "Lorusso Lorenzo", "Kandil Omar", person=True,
    ) == "home"
    assert unique_side(
        "Andrea M'chich", "Andrea Mchich", "Omar Kandil", person=True,
    ) == "home"
    assert unique_side(
        "Juan Martin", "Juan Cruz Martin Manzano", "Duje Ajdukovic", person=True,
    ) == "home"
    assert unique_side("Rune", "Holger Rune", "Carlos Alcaraz", person=True) == ""
    assert unique_side("QUB", "QUB", "FURIA", person=False) == "home"


def test_unique_side_rejects_shared_surname() -> None:
    """Challenger: unique Ferrari in the pair is not Francesco Ferrari."""
    assert unique_side(
        "Francesco Ferrari",
        "Thiago Seyboth Wild",
        "Gianmarco Ferrari",
        person=True,
    ) == ""
    assert unique_side(
        "Juan Martin", "Juan Perez", "Duje Ajdukovic", person=True,
    ) == ""
    assert person_unique_hit_ok("Francesco Ferrari", "Gianmarco Ferrari") is False
    assert person_unique_hit_ok(
        "Francesco Ferrari", "Gianmarco Francesco Ferrari",
    ) is True
    assert unique_side(
        "Francesco Ferrari",
        "Thiago Seyboth Wild",
        "Gianmarco Francesco Ferrari",
        person=True,
    ) == "away"
    assert person_unique_hit_ok("Lorenzo Lorusso", "Lorusso Lorenzo") is True


def test_unique_side_skips_state_suffix() -> None:
    assert unique_side(
        "Southern Connecticut State",
        "Southern Connecticut",
        "Wagner",
        person=False,
    ) == ""
    assert unique_side(
        "Ohio State", "Ohio State", "Michigan", person=False,
    ) == "home"


def test_vs_sides_tennis_prefix_and_soccer_line() -> None:
    assert vs_sides("M15 Hurghada: Omar Kandil vs Lorenzo Lorusso") == (
        "Omar Kandil", "Lorenzo Lorusso",
    )
    assert vs_sides("RB Leipzig vs. Borussia Mönchengladbach: O/U 2.5") == (
        "RB Leipzig", "Borussia Mönchengladbach",
    )
    assert vs_sides(
        "Counter-Strike: 3DMAX vs Infinite (BO3) - ESL Pro League",
    ) == ("3DMAX", "Infinite")
    assert vs_sides(
        "Counter-Strike: 3DMAX vs Infinite - Map 2 Winner",
    ) is None
    assert vs_sides(
        "Counter-Strike: Vitality vs 100 Thieves (BO1) - Map 3 Winner",
    ) is None
