"""2026-11-05 DKEX misses: DKEX and Optic spell the same entity apart."""

from __future__ import annotations

import pytest

from mappers.exchanges.dkex_names import (
    OPTIC_PLAYER_IDS_BY_DKEX_NAME,
    optic_id_side,
)


@pytest.mark.parametrize(("name", "optic_id"), [
    ("Red Star Belgrade", "DA099181EE5BD01B"),   # FK Crvena zvezda Beograd
    ("Seokhyeon Ko", "99CC61D9718D"),            # Seok Hyun Ko
    ("Gabriel Lorenco", "834CB3D4ED4288C0"),     # Gabriel Lourenco
    ("Chun-Chien Hou", "EAAABF97CEE5DCA3"),      # Hou Chun Chien
    ("Chun-Chien Hou", "1138A5187752B0DA"),      # second Optic competitor, same player
    ("Digvijay Pratap Singh", "0419A719CAD7E3BC"),  # Digvijaypratap Singh
])
def test_name_pin_names_the_side(name: str, optic_id: str) -> None:
    assert optic_id_side(name, {optic_id: "A", "OTHER": "B"}) == "A"
    assert optic_id_side(name, {"OTHER": "B"}) is None


@pytest.mark.parametrize(("name", "optic_id"), [
    ("Zachary Bolduc", "CF74533DDE3E"),
    ("Gabe Perreault", "80065152FF8073EF"),
    ("Marquise Brown", "9AF71136A8B6"),
    ("Kamal-Deen Sulemana", "CC1AA46FEE8104DC"),
    ("Max Rosenfelde", "5EC54D60865770D1"),
    ("Nicolas Moumi", "B4A61EFE19E50CCF"),
    ("Bekhruz Karimov", "DE847442AF017283"),
    ("Toni Garcia", "4D3704B58B65"),
])
def test_player_pin(name: str, optic_id: str) -> None:
    assert OPTIC_PLAYER_IDS_BY_DKEX_NAME[name.casefold()] == frozenset({optic_id})


def test_tennis_name_order_and_fused_given_names_resolve_by_pin() -> None:
    from types import SimpleNamespace

    from mappers.exchanges.dkex_pass import _side_for

    taipei = SimpleNamespace(
        home="WON", away="HOU", home_name="Chak Lam Coleman Wong", away_name="Hou Chun Chien",
        team_map={"2D9E3304CAE9": "WON", "EAAABF97CEE5DCA3": "HOU"})
    assert _side_for("Coleman Wong", taipei, person=True) == "WON"
    assert _side_for("Chun-Chien Hou", taipei, person=True) == "HOU"
    fergana = SimpleNamespace(
        home="DIG", away="HRA", home_name="Digvijaypratap Singh", away_name="Jan Hrazdil",
        team_map={"0419A719CAD7E3BC": "DIG", "E466EEE78D8C9D6A": "HRA"})
    assert _side_for("Digvijay Pratap Singh", fergana, person=True) == "DIG"
    assert _side_for("Jan Hrazdil", fergana, person=True) == "HRA"
