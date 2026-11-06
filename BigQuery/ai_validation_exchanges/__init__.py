"""Registry of the exchanges the AI mapping validator judges.

Adding an exchange = one module in this package exporting `SPEC`, plus one line
in `_SPECS` below. Order is stable and drives the SQL join/select order and the
`SPORTSBOOKS` tuple. Nothing else in `ai_validation.py` needs to change.
"""

from __future__ import annotations

from BigQuery.ai_validation_exchanges import crypto_com, kalshi, novig, polymarket, sx_bet
from BigQuery.ai_validation_exchanges.base import ExchangeSpec

_SPECS: tuple[ExchangeSpec, ...] = (
    kalshi.SPEC,
    polymarket.SPEC,
    crypto_com.SPEC,
    novig.SPEC,
    # Dormant unless AI_VALIDATION_SXBET=1 (owner call: see sx_bet.py).
    *((sx_bet.SPEC,) if sx_bet.enabled() else ()),
)

#: sportsbook name -> spec, in a stable order. Always read through the helpers
#: below at call time (never copy it at import) so tests can monkeypatch it.
EXCHANGES: dict[str, ExchangeSpec] = {s.name: s for s in _SPECS}


def sportsbooks() -> tuple[str, ...]:
    """Names of every registered exchange, in registry order."""
    return tuple(EXCHANGES)


def corroborated_sportsbooks() -> tuple[str, ...]:
    """Exchanges where Optic's own id can corroborate a match without the model."""
    return tuple(name for name, s in EXCHANGES.items() if s.corroborated)


def prompts() -> dict[str, str]:
    """Per-exchange rule blocks."""
    return {name: s.prompt for name, s in EXCHANGES.items()}


def get(name: str | None) -> ExchangeSpec | None:
    """The spec for a sportsbook, or None when it is not a registered exchange."""
    return EXCHANGES.get(name) if name else None
