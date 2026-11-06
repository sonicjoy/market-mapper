"""Boxing league config.

Optic's "moneyline_3-way" (with a real, differently-priced Draw
outcome) is deliberately NOT wired — only "moneyline" is, matching
Kalshi's own 2-way contract.
"""

from mappers.market_types import MarketType
from mappers.sport import Sport, sport_for_league
from tests.mappers._combat_helpers import (
    BOXING_OPTIC,
    boxing_league_config,
)


def test_boxing_registered():
    assert sport_for_league("boxing_matches") == Sport.BOXING


def test_optic_only_maps_plain_moneyline_not_3way():
    assert BOXING_OPTIC.league_id == "boxing_matches"
    assert BOXING_OPTIC.table_types == {"moneyline": MarketType.MONEYLINE}
    assert "moneyline_3-way" not in BOXING_OPTIC.table_types


def test_no_px_crypto_polymarket_wired_for_v1():
    cfg = boxing_league_config()
    assert cfg.PX is None
    assert cfg.CRYPTO is None
    assert cfg.POLYMARKET is None
