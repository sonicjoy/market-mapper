"""Shared types for live alias verify."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

FixturesFn = Callable[..., list[dict[str, Any]]]
CryptoFn = Callable[[str], dict[str, Any]]
TxoddsTeamsFn = Callable[[], dict[str, str]]


@dataclass(frozen=True)
class EvidenceHit:
    """Live probe result; blocker set means verify must not pass."""

    refs: tuple[str, ...] = ()
    blocker: str | None = None


@dataclass(frozen=True)
class EvidenceFetchers:
    """Injectable HTTP/BQ backends (production uses defaults)."""

    optic_fixtures: FixturesFn | None = None
    crypto_row: CryptoFn | None = None
    # TxODDS TeamId -> PreferredName (tx_scores_us.txodds_reference_raw team rows).
    txodds_teams: TxoddsTeamsFn | None = None
