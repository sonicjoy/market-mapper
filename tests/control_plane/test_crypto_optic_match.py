"""Accent/FC-aware crypto.com → Optic fixture name matching."""

from __future__ import annotations

from typing import Any

from mappers.control_plane.crypto_optic_match import (
    best_fixture,
    entity_name_from_crypto_refs,
    event_title_from_crypto_refs,
    fixture_for_ids,
    fixtures_on_day,
    is_matchup_title,
    match_optic_fixture,
    name_sides,
    unique_fixture,
)


def _game(
    fid: str, home: str, home_id: str, away: str, away_id: str,
) -> dict[str, Any]:
    return {
        "id": fid,
        "start_date": "2026-08-29T15:30:00Z",
        "home_competitors": [{"id": home_id, "name": home}],
        "away_competitors": [{"id": away_id, "name": away}],
    }


def test_name_sides_soccer_at_and_vs() -> None:
    assert name_sides("Borussia Monchengladbach @ RB Leipzig") == (
        "Borussia Monchengladbach",
        "RB Leipzig",
    )
    assert is_matchup_title("Thomas Faurel @ Dusan Obradovic")
    assert not is_matchup_title("Dusan Obradovic")


def test_crypto_source_name_skips_matchup_title() -> None:
    refs = [
        "crypto:name:Thomas Faurel @ Dusan Obradovic",
        "crypto:name:Thomas Faurel",
        "crypto:name:Dusan Obradovic",
    ]
    assert entity_name_from_crypto_refs(refs, "Dusan Obradovic") == "Dusan Obradovic"
    assert entity_name_from_crypto_refs(
        ["crypto:name:Thomas Faurel @ Dusan Obradovic"],
        "Dusan Obradovic",
    ) == "Dusan Obradovic"
    assert event_title_from_crypto_refs(refs) == "Thomas Faurel @ Dusan Obradovic"
    assert event_title_from_crypto_refs(
        ["crypto:title:Faurel @ Obradovic", "crypto:name:Dusan Obradovic"],
    ) == "Faurel @ Obradovic"
    assert entity_name_from_crypto_refs(
        ["crypto:name:Juan Martin"],
        "Juan Cruz Martin Manzano",
    ) == "Juan Martin"


def test_best_fixture_folds_umlaut() -> None:
    hit = best_fixture(
        [_game(
            "fx-lei", "RB Leipzig", "oid-rbl",
            "Borussia Mönchengladbach", "oid-bmg",
        )],
        ("Borussia Monchengladbach", "RB Leipzig"),
        player=False,
    )
    assert hit is not None
    assert hit["away_id"] == "oid-bmg"


def test_best_fixture_strips_fc_suffix() -> None:
    hit = best_fixture(
        [_game(
            "fx-liv", "Liverpool", "oid-liv",
            "Nottingham Forest", "oid-nfo",
        )],
        ("Nottingham Forest FC", "Liverpool FC"),
        player=False,
    )
    assert hit is not None
    assert hit["home_id"] == "oid-liv"


def test_best_fixture_legal_name_suffix() -> None:
    hit = best_fixture(
        [_game(
            "fx-nice", "Paris FC", "oid-pfc",
            "OGC Nice Côte d'Azur", "oid-nic",
        )],
        ("Paris FC", "OGC Nice"),
        player=False,
    )
    assert hit is not None
    assert hit["away_id"] == "oid-nic"
    rennes = best_fixture(
        [_game(
            "fx-ren", "Stade Rennais FC", "oid-ren",
            "Le Mans", "oid-lem",
        )],
        ("Stade Rennais FC 1901", "Le Mans FC"),
        player=False,
    )
    assert rennes is not None
    assert rennes["home_id"] == "oid-ren"


def test_best_fixture_player_middle_name() -> None:
    """Catalogue drops a middle name; Optic keeps the legal name."""
    hit = best_fixture(
        [_game(
            "fx-jcm", "Duje Ajdukovic", "oid-ajd",
            "Juan Cruz Martin Manzano", "oid-jcm",
        )],
        ("Juan Martin", "Duje Ajdukovic"),
        player=True,
    )
    assert hit is not None
    assert hit["away_id"] == "oid-jcm"


def test_best_fixture_one_token_prefix_is_not_enough() -> None:
    """Santos ⊄ Santos Sao Paulo — still a different club."""
    assert best_fixture(
        [_game(
            "fx-san", "Santos FC Sao Paulo", "oid-san",
            "Corinthians", "oid-cor",
        )],
        ("Santos FC", "Corinthians"),
        player=False,
    ) is None


def test_best_fixture_reverse_player_and_apostrophe() -> None:
    reverse = best_fixture(
        [_game(
            "fx-rev", "Lorusso Lorenzo", "oid-lor",
            "Kandil Omar", "oid-kan",
        )],
        ("Lorenzo Lorusso", "Omar Kandil"),
        player=True,
    )
    assert reverse is not None
    assert reverse["home_id"] == "oid-lor"
    apostrophe = best_fixture(
        [_game(
            "fx-mch", "Andrea Mchich", "oid-mch",
            "Omar Kandil", "oid-kan",
        )],
        ("Andrea M'chich", "Omar Kandil"),
        player=True,
    )
    assert apostrophe is not None
    assert apostrophe["home_id"] == "oid-mch"


def test_fixtures_on_day_filters_then_falls_back() -> None:
    same = _game("a", "Home", "h", "Away", "a")
    other = dict(same, id="b", start_date="2026-08-30T15:30:00Z")
    assert [g["id"] for g in fixtures_on_day([same, other], "2026-08-29")] == ["a"]
    assert len(fixtures_on_day([same, other], "")) == 2


def test_fixture_for_ids_either_orientation() -> None:
    game = _game("fx", "Home", "H1", "Away", "A1")
    hit = fixture_for_ids([game], ["A1", "H1"])
    assert hit is not None
    assert hit["fixture_id"] == "fx"


def test_match_optic_fixture_unique_other_day() -> None:
    sunday = _game("sun", "Celta", "c", "Malaga", "m")
    sunday["start_date"] = "2026-09-13T12:00:00Z"
    friday = _game("fri", "Sevilla FC", "oid-sev", "Valencia CF", "oid-val")
    friday["start_date"] = "2026-09-11T19:00:00Z"
    hit = match_optic_fixture(
        [sunday, friday],
        ("Valencia CF", "Sevilla FC"),
        ["90000606", "90000614"],
        "2026-09-13",
        player=False,
    )
    assert hit is not None
    assert hit["fixture_id"] == "fri"


def test_unique_fixture_fails_closed_on_two_meetings() -> None:
    a = _game("a", "Sevilla FC", "s", "Valencia CF", "v")
    b = dict(a, id="b", start_date="2026-09-20T19:00:00Z")
    assert unique_fixture([a, b], ("Valencia CF", "Sevilla FC"), player=False) is None


def test_match_optic_fixture_empty_catalogue_day_unique_other_day() -> None:
    friday = _game("fri", "Sevilla FC", "oid-sev", "Valencia CF", "oid-val")
    friday["start_date"] = "2026-09-11T19:00:00Z"
    hit = match_optic_fixture(
        [friday],
        ("Valencia CF", "Sevilla FC"),
        ["90000606", "90000614"],
        "2026-09-13",
        player=False,
    )
    assert hit is not None
    assert hit["fixture_id"] == "fri"


def test_match_optic_fixture_surname_spelling_variant() -> None:
    game = _game(
        "fx-shel", "Abdullah Shelbayh", "8029841F6C68", "Li Tu", "3A8D00CF0E05",
    )
    game["start_date"] = "2026-09-29T14:00:00Z"
    hit = match_optic_fixture(
        [game],
        ("Li Tu", "Abedallah Shelbayh"),
        ["385908", "1130651"],
        "2026-09-29",
        player=True,
    )
    assert hit is not None
    assert hit["fixture_id"] == "fx-shel"


def test_match_optic_fixture_empty_day_fails_closed_on_two_meetings() -> None:
    a = _game("a", "Sevilla FC", "s", "Valencia CF", "v")
    b = dict(a, id="b", start_date="2026-09-20T19:00:00Z")
    assert match_optic_fixture(
        [a, b],
        ("Valencia CF", "Sevilla FC"),
        [],
        "2026-09-13",
        player=False,
    ) is None
