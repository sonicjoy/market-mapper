"""crypto.com NFL "To Go To Overtime" maps to will_there_be_overtime (yes)."""

from __future__ import annotations

import json

from mappers.exchanges.crypto_com import build_rows, parse_selection
from mappers.market_types import MarketType
from mappers.vocab.football_markets import NCAAF_CRYPTO, NFL_CRYPTO

_PAYLOAD = {
    "eventMetaLEAGUE": "NFL",
    "eventMetaSPORTS_GROUPING": "NFL",
    "eventMetaEVENT_DATE": "2026-10-20T00:15:00+00:00",
    "eventMetaHOME_PARTICIPANT": "San Francisco 49ers",
    "eventMetaAWAY_PARTICIPANT": "Washington Commanders",
    "eventMetaEXTERNAL_HOME_ID": "30000002",
    "eventMetaEXTERNAL_AWAY_ID": "30000009",
    "eventMetaEXTERNAL_GAME_ID": "G-OT-1",
    "eventMetaPREDICT_MARKET_TYPE": "Game Prop",
    "eventMetaPREDICT_PERIOD_TYPE": "Full-Game",
    "eventMetaPREDICT_CONTRACT_TYPE": "To Go To Overtime",
    "eventMetaPREDICT_OUTCOME_TYPE": "Yes",
    "eventMetaPREDICT_MARKET_ID": "MKT-OT",
    "eventMetaPREDICT_OUTCOME_ID": "OUT-OT",
    "SecurityID": "NFL-OT-1",
    "Symbol": "NX.F.OPT.NFL-00001-261019-M.O.1.491.20270301",
}
_ALIASES = {"30000002": "SF", "30000009": "WAS"}


def _rows(payload: dict):
    sel = parse_selection(json.dumps(payload))
    assert sel is not None
    return build_rows(
        "2026-10-20T00:15:00+00:00", "SF", "WAS", [sel],
        NFL_CRYPTO, aliases=_ALIASES, league="nfl",
    )


def test_to_go_to_overtime_maps_yes() -> None:
    (row,) = _rows(_PAYLOAD)
    assert row.market_type == MarketType.WILL_THERE_BE_OVERTIME.value
    assert row.side == "yes"
    assert row.entity is None and row.line is None
    assert row.crypto_symbol == _PAYLOAD["Symbol"]


def test_other_period_not_mapped() -> None:
    assert _rows({**_PAYLOAD, "eventMetaPREDICT_PERIOD_TYPE": "1st Half"}) == []


def test_ncaaf_shares_vocab() -> None:
    assert NCAAF_CRYPTO is not None
    assert NCAAF_CRYPTO.game_prop_contract_types == NFL_CRYPTO.game_prop_contract_types
