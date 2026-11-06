"""DKEX Liga MX Pumas UNAM v Club America (2026-11-07): the names no rule fits."""

from __future__ import annotations

import pytest

from mappers.exchanges.dkex_names import optic_id_side

_TEAMS = {"A3DA6E9D1669": "home", "B4088A0A4C58": "away"}  # Optic 12440-72234-2026-11-07


@pytest.mark.parametrize(("name", "side"), [("Pumas UNAM", "home"), ("Club America", "away")])
def test_pin_names_the_side(name: str, side: str) -> None:
    assert optic_id_side(name, _TEAMS) == side


def test_pin_is_by_optic_id_not_by_name() -> None:
    # Women's Liga MX carries a different America / Pumas competitor id: no bind.
    assert optic_id_side("Pumas UNAM", {"D5DEB28976E80A83": "home"}) is None
