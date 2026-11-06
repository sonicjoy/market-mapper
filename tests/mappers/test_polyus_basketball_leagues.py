"""PolyUS basketball gateway leagues (catalogue + Optic fixtures read 2026-11-05)."""

from __future__ import annotations

import pytest

from mappers.exchanges.polymarket_usa_leagues import us_league_ids
from mappers.seed.code_leagues import CODE_LEAGUES, code_league_configs
from mappers.sport import Sport

_PAIRS = {
    "australia_-_nbl": 250,
    "spain_-_liga_acb": 74,
    "france_-_lnb_pro_a": 269,
    "france_-_lnb_pro_b": 278,
    "greece_-_a1_league": 273,
    "japan_-_b1_league": 315,
    "international_-_vtb_united_league": 266,
}


@pytest.mark.parametrize(("optic_id", "gateway_id"), sorted(_PAIRS.items()))
def test_gateway_id_and_code_league(optic_id: str, gateway_id: int) -> None:
    assert us_league_ids((optic_id,)) == frozenset({gateway_id})
    owners = [s for s, (sport, ids) in CODE_LEAGUES.items() if ids[0] == optic_id and sport is Sport.BASKETBALL]
    assert len(owners) == 1
    assert code_league_configs()[owners[0]].OPTIC.league_id == optic_id
