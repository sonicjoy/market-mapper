"""The per-exchange contract for the AI mapping validator.

An `ExchangeSpec` bundles everything the validator knows about ONE exchange: the
SQL that fetches its native listing text, the rule block shown to the judge, and
the row accessors that render it. `ai_validation.py` holds only the exchange-
agnostic core and assembles itself from the registry in `__init__.py`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

#: Trailing ISO date on a Polymarket slug (atp-gentzsc-dahlin-2026-07-30).
_SLUG_DATE_RE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
#: Date segment inside a Kalshi ticker (26AUG01, 26JUN27) or a crypto.com FIX
#: symbol (-260804-). Both are matcher INPUTS, never shown to the judge.
#: No word boundaries: the date runs straight into the matchup code
#: (26AUG01KOVBOR), so \b would never match on the trailing side.
_TICKER_DATE_RE = re.compile(r"\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{2}")
_SYMBOL_DATE_RE = re.compile(r"-\d{6}-")


def mask_exchange_dates(ref: str | None) -> str | None:
    """Blank the date inside a Kalshi ticker / crypto.com symbol before display.

    The exchange's date is what the MATCHER used to find the fixture in the first
    place, so re-checking it in the judge is circular -- and it is not even a
    reliable signal: tournament schedules shift, so a Round-of-128 ticker dated
    26AUG01 legitimately belongs to a match played on the 3rd.

    Told to ignore dates, the model ignored the instruction instead: 100% of rows
    in v1, 126 rows in v2, and 10 more in v4 were flagged on nothing but a date.
    Removing the field is the only thing that has actually worked.
    """
    if not ref:
        return None
    masked = _TICKER_DATE_RE.sub("*", ref)
    return _SYMBOL_DATE_RE.sub("-*-", masked)


def strip_slug_date(slug: str | None) -> str | None:
    """Drop the trailing date from a Polymarket slug before showing it to the model.

    Polymarket dates a slug by LOCAL TOURNAMENT DAY, which disagrees with both our
    UTC date and its US-Eastern equivalent on plenty of correct mappings. Left in
    the prompt it produced 126 "fixture date mismatch" flags on tennis and LoL rows
    whose participants matched exactly, and no amount of prompt hedging stopped the
    model reaching for it. The slug's non-date part still identifies the market, so
    that is all it gets.
    """
    if not slug:
        return None
    return _SLUG_DATE_RE.sub("", slug) or None


@dataclass(frozen=True)
class ExchangeSpec:
    """Everything the validator needs to know about one exchange.

    SQL fragments are spliced into the core query in `ai_validation.py`:
    - `cte_sql`: one or more `name AS (...)` CTEs (comma-separated when several,
      no leading/trailing comma). `{project}` and `{lookback_days}` are filled in.
    - `join_sql`: the LEFT JOIN(s) that attach those CTEs to the `map m` rows,
      gated on `m.sportsbook = '<name>'` so other exchanges' rows stay NULL.
    - `select_sql`: the columns those joins add to the outer SELECT.
    """

    #: The `sportsbook` value in markets_us.market_mapping.
    name: str
    #: True when Optic publishes its own id for the same selection, so a match can
    #: be corroborated without the model (see CORROBORATED_SPORTSBOOKS).
    corroborated: bool
    #: Days of raw snapshots / catalogue scanned for this exchange's text.
    lookback_days: int
    cte_sql: str
    join_sql: str
    select_sql: str
    #: Rule block shown to the judge on batches of this exchange only.
    prompt: str
    #: True when the row carries exchange-native text worth judging.
    has_text: Callable[[dict], bool]
    #: The exchange id under judgement (ticker / clob token / FIX symbol).
    ref: Callable[[dict], str | None]
    #: The exchange's own side label, where it has one.
    side: Callable[[dict], str | None]
    #: The exchange-native text kept for triage.
    text: Callable[[dict], str | None]
    #: The exchange half of a prompt line, in that exchange's own terms.
    line: Callable[[dict], str]

    def render_cte(self, project: str) -> str:
        """`cte_sql` with `{project}` and this exchange's `{lookback_days}` filled in."""
        return self.cte_sql.replace("{lookback_days}", str(self.lookback_days)).replace("{project}", project)
