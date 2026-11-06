"""Polymarket US league config: the venue's own, unrelated to Polymarket.

Polymarket US is its own venue with its own contract. Its market vocabulary is
the gateway ``sportsMarketType`` enum, mapped once in
``mappers.vocab.poly_usa_smt``; which gateway leagues a run-set league reads
is ``mappers.exchanges.polymarket_usa_leagues``. Both are code. Nothing here
reads the tip or Polymarket (CLOB) tables.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PolyUsaConfig:
    """One league's Polymarket US scope: the gateway league ids it reads."""

    league_ids: frozenset[int]
