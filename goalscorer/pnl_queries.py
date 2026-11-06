"""Queries behind the goalscorer PnL report.

A goalscorer combo is any Kalshi combo we were filled on that has at least one
leg in a soccer goalscorer series (the registry's soccer leagues, anytime and
first goalscorer, e.g. ``KXEPLGOAL-`` / ``KXEPLFIRSTGOAL-``). Fills are counted
inside the report window; resolutions up to a day after it, so late-settling
combos still land.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta

from google.cloud import bigquery

from BigQuery.client import ro_query
from goalscorer.codes import first_goal_prefix
from goalscorer.config import League
from goalscorer.timeutil import day_window

_P = bigquery.ScalarQueryParameter


def soccer_goal_prefixes(leagues: Iterable[League]) -> list[str]:
    """Sorted anytime and first goalscorer series of the soccer leagues (NHL and other sports excluded)."""
    anytime = {lg.goal_prefix for lg in leagues if lg.sport == "soccer"}
    return sorted(anytime | {first_goal_prefix(p) for p in anytime})


def goal_leg_regex(prefixes: Iterable[str]) -> str:
    """RE2 pattern matching a leg ticker in any of the given goal series."""
    return "^(" + "|".join(re.escape(p) for p in prefixes) + ")-"


_BASE_CTES = """
  combos as (
    select distinct t.market_ticker,
      array_to_string(array(
        select distinct regexp_extract(leg.market_ticker, r'^(KX[A-Z0-9]+GOAL)-')
        from unnest(t.legs) leg where regexp_contains(leg.market_ticker, @goal_re)
        order by 1
      ), ', ') as series
    from `{p}.processed_upstream_us.kalshi_tickers_v2` t
    join `{p}.processed_upstream_us.kalshi_fills` f
      on f.market_ticker = t.market_ticker and f.publish_time >= @fill_start and f.publish_time < @fill_end
    where t.publish_time >= @ticker_start and t.publish_time < @ticker_end
      and exists (select 1 from unnest(t.legs) leg where regexp_contains(leg.market_ticker, @goal_re))
  ),
  fills as (
    select f.market_ticker, sum(f.count_fp * f.yes_price_dollars) as stakes, sum(f.count_fp) as risk
    from `{p}.processed_upstream_us.kalshi_fills` f
    where f.publish_time >= @fill_start and f.publish_time < @fill_end
      and f.market_ticker in (select market_ticker from combos)
    group by f.market_ticker
  ),
  resolved as (
    select r.ticker, any_value(r.market_result) as market_result,
           sum(ifnull(r.pnl, 0) - ifnull(r.fee_cost, 0)) as pnl, sum(ifnull(r.fee_cost, 0)) as fees
    from `{p}.reporting_us.kalshi_resolutions` r
    where r.settled_time >= @fill_start and r.settled_time < @settle_end
      and r.ticker in (select market_ticker from combos)
    group by r.ticker
  )
"""

_COMBO_LEGS_CTE = """
  combo_legs as (
    select distinct t.market_ticker as combo, leg.market_ticker as leg
    from `{p}.processed_upstream_us.kalshi_tickers_v2` t, unnest(t.legs) leg
    where t.publish_time >= @ticker_start and t.publish_time < @ticker_end
      and t.market_ticker in (select market_ticker from combos)
  )
"""

_SUMMARY_SQL = """
  with {ctes}
  select c.series, count(*) as combos, countif(r.market_result is not null) as settled,
    countif(r.market_result = 'no') as won, countif(r.market_result = 'yes') as lost,
    ifnull(sum(r.pnl), 0) as pnl, ifnull(sum(fs.stakes), 0) as stakes,
    ifnull(sum(fs.risk), 0) as risk, ifnull(sum(r.fees), 0) as fees
  from combos c
  left join fills fs on fs.market_ticker = c.market_ticker
  left join resolved r on r.ticker = c.market_ticker
  group by rollup (c.series)
  order by c.series is null, c.series
"""

_LEGS_SQL = """
  with {ctes}, {combo_legs}
  select l.leg, count(distinct l.combo) as combos, ifnull(sum(fs.stakes), 0) as stakes,
    ifnull(sum(fs.risk), 0) as risk, ifnull(sum(r.pnl), 0) as pnl
  from combo_legs l
  join fills fs on fs.market_ticker = l.combo
  left join resolved r on r.ticker = l.combo
  where regexp_contains(l.leg, @goal_re)
  group by l.leg
"""

_LOSSES_SQL = """
  with {ctes}, {combo_legs},
  lost as (
    select r.ticker as combo, r.pnl from resolved r
    where r.market_result = 'yes' and r.ticker in (select combo from combo_legs where leg = @leg)
  )
  select l.combo, l.pnl, ifnull(fs.stakes, 0) as stakes, ifnull(fs.risk, 0) as risk,
    array_agg(cl.leg ignore nulls order by cl.leg) as legs
  from lost l
  join fills fs on fs.market_ticker = l.combo
  left join combo_legs cl on cl.combo = l.combo and cl.leg != @leg
  group by l.combo, l.pnl, fs.stakes, fs.risk
  order by l.pnl
  limit 10
"""


@dataclass(frozen=True)
class SeriesRow:
    """Summary numbers for one goal series (series '' = total)."""

    series: str
    combos: int
    settled: int
    won: int
    lost: int
    pnl: float
    stakes: float
    risk: float
    fees: float

    @property
    def roi(self) -> float:
        """PnL as a percentage of risk."""
        return self.pnl / self.risk * 100 if self.risk else 0.0


@dataclass(frozen=True)
class LegRow:
    """PnL of the combos one goal leg appeared in."""

    leg: str
    combos: int
    stakes: float
    risk: float
    pnl: float


@dataclass(frozen=True)
class LossCombo:
    """One losing combo containing the worst leg, with its other legs."""

    combo: str
    pnl: float
    stakes: float
    risk: float
    legs: list[str] = field(default_factory=list)


class PnlQueries:
    """Runs the report queries for a day or a date range."""

    def __init__(self, client: bigquery.Client, project: str, goal_prefixes: Iterable[str]) -> None:
        self.client = client
        self.project = project
        self.goal_re = goal_leg_regex(goal_prefixes)

    def _run(self, template: str, start: date, end: date, *extra) -> list[bigquery.Row]:
        """Run a report query over [start, end] with the shared window params."""
        fill_start, fill_end = day_window(start, days=(end - start).days + 1)
        params = [
            _P("goal_re", "STRING", self.goal_re),
            _P("fill_start", "TIMESTAMP", fill_start),
            _P("fill_end", "TIMESTAMP", fill_end),
            _P("ticker_start", "TIMESTAMP", fill_start - timedelta(days=1)),
            _P("ticker_end", "TIMESTAMP", fill_end + timedelta(hours=12)),
            _P("settle_end", "TIMESTAMP", fill_end + timedelta(days=1)),
            *extra,
        ]
        ctes = _BASE_CTES.format(p=self.project)
        sql = template.format(ctes=ctes, combo_legs=_COMBO_LEGS_CTE.format(p=self.project))
        return list(ro_query(self.client, sql, job_config=bigquery.QueryJobConfig(query_parameters=params)))

    def summary(self, start: date, end: date) -> tuple[list[SeriesRow], SeriesRow]:
        """Per-series rows and the rollup total for [start, end]."""
        rows = [SeriesRow(**{**dict(r.items()), "series": r.series or ""}) for r in self._run(_SUMMARY_SQL, start, end)]
        total = next((r for r in rows if not r.series), SeriesRow("", 0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0))
        return [r for r in rows if r.series], total

    def legs(self, day: date) -> list[LegRow]:
        """Every goal leg traded on `day` with the PnL of its combos."""
        return [LegRow(**dict(r.items())) for r in self._run(_LEGS_SQL, day, day)]

    def losses(self, day: date, leg: str) -> list[LossCombo]:
        """The ten worst losing combos containing `leg`."""
        rows = self._run(_LOSSES_SQL, day, day, _P("leg", "STRING", leg))
        return [LossCombo(r.combo, r.pnl, r.stakes, r.risk, list(r.legs)) for r in rows]
