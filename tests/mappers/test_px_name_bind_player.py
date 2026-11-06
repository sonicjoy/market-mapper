"""Shared player fixture pairing (mapper, chat, gap-propose)."""

from __future__ import annotations

from mappers.px_name_bind import (
    NamedSide,
    orientation_pair_ok,
    pair_fits,
    person_surname_agree,
    unique_optic_sides,
)


def test_surname_spelling_variant_pairs_with_anchor() -> None:
    assert person_surname_agree("Abedallah Shelbayh", "Abdullah Shelbayh")
    assert orientation_pair_ok(
        "Abedallah Shelbayh",
        "Li Tu",
        "Abdullah Shelbayh",
        "Li Tu",
        player=True,
    )
    assert not orientation_pair_ok(
        "Juan Garcia",
        "Pedro Garcia",
        "Juan Martinez",
        "Pedro Martinez",
        player=True,
    )


def test_unique_optic_sides_shelbayh_fixture() -> None:
    fixtures = [
        (
            NamedSide("8029841F6C68", "Abdullah Shelbayh"),
            NamedSide("3A8D00CF0E05", "Li Tu"),
        ),
    ]
    hit = unique_optic_sides(
        NamedSide("1130651", "Abedallah Shelbayh"),
        NamedSide("385908", "Li Tu"),
        fixtures,
        player=True,
    )
    assert hit is not None
    assert hit[0].name == "Abdullah Shelbayh"
    assert hit[1].name == "Li Tu"


def test_pair_fits_flips_club_home_away() -> None:
    assert pair_fits(
        NamedSide("", "Nottingham Forest FC"),
        NamedSide("", "Liverpool FC"),
        NamedSide("", "Liverpool"),
        NamedSide("", "Nottingham Forest"),
        player=False,
    )


def test_name_ok_uses_catalogue_and_optic_partners() -> None:
    from mappers.control_plane.live_evidence_names import name_ok

    assert name_ok(
        "Abdullah Shelbayh",
        "Abedallah Shelbayh",
        "atp",
        partner="Li Tu",
        optic_partner="Li Tu",
    )
    assert not name_ok(
        "Abdullah Shelbayh",
        "Abedallah Shelbayh",
        "atp",
        partner="Li Tu",
        optic_partner="Someone Else",
    )


def test_hold_kind_spelling_variant_sees_wrong_owner() -> None:
    from mappers.control_plane.crypto_alias_correct import hold_kind
    from mappers.control_plane.gap_fix_tip import TipLeagueIndex

    indexed = TipLeagueIndex()
    indexed.optic["8029841F6C68"] = "SHEL"
    kind = hold_kind(
        indexed,
        "atp_challenger",
        ["1130651", "385908"],
        ["Abedallah Shelbayh", "Li Tu"],
        [
            {"crypto_id": "1130651", "owners": ["OTHER"]},
            {"crypto_id": "385908", "owners": ["LITU"]},
        ],
        {
            "home": "Abdullah Shelbayh",
            "home_id": "8029841F6C68",
            "away": "Li Tu",
            "away_id": "3A8D00CF0E05",
        },
    )
    assert kind == "alias_mismatch"


def test_pair_fits_rejects_mismatched_surname_fixture() -> None:
    assert not pair_fits(
        NamedSide("", "Marcos Silva"),
        NamedSide("", "Joao Silva"),
        NamedSide("h1", "Marcos Silva"),
        NamedSide("a1", "Pedro Silva"),
        player=True,
    )
