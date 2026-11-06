"""Console / chat view of what the Polymarket US table maps.

Everything derives from ``mappers.vocab.poly_usa_smt`` plus Optic's own
tables; nothing reads Polymarket (CLOB) vocabulary.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from mappers.market_types import MarketType
from mappers.vocab.baseball_markets import BASEBALL_OPTIC_TABLE_TYPES
from mappers.vocab.basketball_markets import BASKETBALL_OPTIC_TABLE_TYPES
from mappers.vocab.combat_markets import BOXING_OPTIC_TABLE_TYPES, UFC_OPTIC_TABLE_TYPES
from mappers.vocab.cricket_markets import CRICKET_OPTIC_TABLE_TYPES
from mappers.vocab.esports_markets import ESPORTS_OPTIC_TABLE_TYPES
from mappers.vocab.football_markets import FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES
from mappers.vocab.hockey_markets import HOCKEY_OPTIC_TABLE_TYPES
from mappers.vocab.poly_usa_smt import known_smts, smt_spec
from mappers.vocab.soccer_markets import SOCCER_OPTIC_TABLE_TYPES
from mappers.vocab.tennis_markets import TENNIS_OPTIC_TABLE_TYPES

SMT_RULE_KEY_TYPE = "sports_market_type"

_OPTIC_TABLES = (
    BASEBALL_OPTIC_TABLE_TYPES, BASKETBALL_OPTIC_TABLE_TYPES,
    BOXING_OPTIC_TABLE_TYPES, UFC_OPTIC_TABLE_TYPES, CRICKET_OPTIC_TABLE_TYPES,
    ESPORTS_OPTIC_TABLE_TYPES, FOOTBALL_NFL_NCAAF_OPTIC_TABLE_TYPES,
    HOCKEY_OPTIC_TABLE_TYPES, SOCCER_OPTIC_TABLE_TYPES, TENNIS_OPTIC_TABLE_TYPES,
)


@cache
def produced_market_types() -> frozenset[MarketType]:
    """Every MarketType some explicitly wired enum maps onto."""
    out: set[MarketType] = set()
    for smt in known_smts():
        spec = smt_spec(smt)
        if spec is not None:
            out.add(spec[0])
    return frozenset(out)


@cache
def parsed_source_keys() -> frozenset[str]:
    """Enums, MarketType values and Optic ids the US table can land on."""
    produced = produced_market_types()
    optic_ids = {
        optic_id
        for table in _OPTIC_TABLES
        for optic_id, mt in table.items()
        if mt in produced
    }
    return known_smts() | {mt.value for mt in produced} | frozenset(optic_ids)


def wired_canonical(cfg: Any, smt: str) -> str | None:
    """Canonical MarketType value this league maps the enum onto, if any."""
    usa = getattr(cfg, "POLYMARKET_USA", None)
    if usa is None:
        return None
    spec = smt_spec(smt)
    return spec[0].value if spec is not None else None


def is_smt_rule(source_key_type: str) -> bool:
    """True for a tip rule keyed on the gateway enum."""
    return source_key_type == SMT_RULE_KEY_TYPE


def llm_prompt_fragment() -> str:
    """Wired Poly US enums for the LLM system card (from the enum table)."""
    wired = ", ".join(sorted(known_smts()))
    return (
        "Polymarket US maps only on the gateway sportsMarketType enum, from a "
        f"code table: {wired}. It is unrelated to Polymarket. Tip rules "
        "never change it (rows with "
        f"source_key_type={SMT_RULE_KEY_TYPE} are ignored); any other enum "
        "is needs_code — explain the parser work, do not propose_markets."
    )
