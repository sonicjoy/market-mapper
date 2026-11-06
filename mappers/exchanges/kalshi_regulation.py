"""Regulation-basis check for Kalshi basketball 2H / 4Q markets.

Optic grades basketball 2nd_half_* and 4th_quarter_* on regulation. Kalshi
states the basis only in the free-text ``rules_primary``: NBA 2nd half
"(including overtime)", NBA 4th quarter "(excluding overtime)", WNBA both
"(not including overtime)". Map only when the rules exclude overtime; a market
with no ``rules_primary`` at all fails closed and is counted, so a fetch that
stops carrying the field shows up instead of silently unmapping the period.
"""

from __future__ import annotations

import re
import sys

from mappers.market_types import MarketType
from mappers.sport import Sport

_REGULATION_PERIOD_PREFIXES = ("2h_", "4q_")
_EXCLUDES_OVERTIME_RE = re.compile(r"\((?:excluding|not including) overtime\)", re.IGNORECASE)

_missing_rules: list[str] = []


def regulation_basis(sport: Sport, mt: MarketType | None, rules_primary: str | None, ticker: str) -> MarketType | None:
    """``mt``, or None for a basketball 2H / 4Q market whose rules do not exclude overtime."""
    if mt is None or sport is not Sport.BASKETBALL:
        return mt
    if not mt.value.startswith(_REGULATION_PERIOD_PREFIXES):
        return mt
    if not rules_primary:
        _missing_rules.append(ticker)
        return None
    return mt if _EXCLUDES_OVERTIME_RE.search(rules_primary) else None


def report_missing_rules() -> None:
    """One summary line for the markets held since they had no rules_primary; resets."""
    if _missing_rules:
        print(f"  ALERT kalshi: {len(_missing_rules)} basketball 2H/4Q markets without rules_primary held "
              f"(e.g. {_missing_rules[0]!r})", file=sys.stderr)
        _missing_rules.clear()
