"""Shared gap harvest key / catalogue helpers."""

from __future__ import annotations

from mappers.control_plane.gap_fix_tip import harvest_cid


def test_harvest_cid_matches_catalogue_legal_name() -> None:
    harvest = {"Cristian Ignacio Garin": "308357"}
    assert harvest_cid(harvest, "Cristian Garin", player=True) == "308357"


def test_harvest_cid_matches_person_name_extends() -> None:
    harvest = {"Juan Cruz Martin Manzano": "90001"}
    assert harvest_cid(harvest, "Juan Martin", player=True) == "90001"


def test_harvest_cid_rejects_ambiguous_names_fit() -> None:
    harvest = {
        "Juan Cruz Martin Manzano": "90001",
        "Juan Martin Del Potro": "90002",
    }
    assert harvest_cid(harvest, "Juan Martin", player=True) == ""


def test_harvest_cid_surname_spelling_with_optic_counterpart() -> None:
    harvest = {
        "Abedallah Shelbayh": "1130651",
        "Li Tu": "385908",
    }
    assert harvest_cid(
        harvest,
        "Abdullah Shelbayh",
        player=True,
        optic_counterpart="Li Tu",
    ) == "1130651"
