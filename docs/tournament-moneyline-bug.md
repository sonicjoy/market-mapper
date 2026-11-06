# Missing Kalshi moneyline mappings for conference tournament finals

> Historical note. Tip/console steps here are retired; see CLAUDE.md.

## Issue

Kalshi uses two ticker formats for NCAAB moneyline markets:

- **Per-game moneylines** (`KXNCAAMBGAME-26MAR14UVADUKE`) — used for
  regular season and conference tournament semifinals.  Date and team
  codes are embedded in the event ticker.
- **Tournament outright winner** (`KXNCAAMBACC-26`) — used for
  conference tournament finals.  The event ticker has only the year;
  team codes appear in the market ticker suffix (e.g.
  `KXNCAAMBACC-26-DUKE`).

We were not fetching the tournament series, and the mapper did not know
how to handle them.  Spreads, totals, and 1H markets were unaffected
(those use per-game tickers for all rounds).  Only the moneyline was
missing.

## Confirmed missing (March 15)

These games have both per-game markets (spreads/totals) and a 2-team
tournament moneyline in our post-fix fetches.  The tournament moneyline
was not being fetched or mapped before the fix.

| Game suffix        | Conference          | Tournament ticker     |
|--------------------|---------------------|-----------------------|
| DAYVCU             | Atlantic 10         | KXNCAAMBA10-26        |
| WICHUSF            | American Athletic   | KXNCAAMBAMER-26       |
| PURMICH            | Big Ten             | KXNCAAMBBIG10-26      |
| HAWUCI             | Big West            | KXNCAAMBBWEST-26      |
| PENNYALE           | Ivy League          | KXNCAAMBIVY-26        |
| VANARK             | SEC                 | KXNCAAMBSEC-26        |
| CBUUVU             | WAC                 | KXNCAAMBWAC-26        |

## Suspected missing (March 14)

These games had per-game markets (spreads, totals, 1H) but no
`KXNCAAMBGAME` moneyline in our March 14 fetches.  We were not
fetching tournament series at that point, so we cannot confirm a
tournament moneyline existed, but the pattern matches the confirmed
cases above.

| Game suffix        | Suspected conference |
|--------------------|----------------------|
| UVADUKE            | ACC                  |
| UVMUMBC            | America East         |
| HOUARIZ            | Big 12               |
| CONNSJU            | Big East             |
| HAWUCI             | Big West             |
| KENNLT             | Conference USA       |
| NCCUHOW            | MEAC                 |
| TOLAKR             | Mid-American         |
| SDSUUSU            | Mountain West        |
| PVSOU              | SWAC                 |

## Cleaning up tournament moneyline rows in market_mapping

These rows map a tournament outright winner market to a specific game,
which may not be correct (the outright winner is only equivalent to
the game moneyline if exactly two teams remain).  To inspect them:

```sql
SELECT start_date, home, away, side, fixture_id,
       JSON_VALUE(source_ids, '$.market_id') AS kalshi_ticker
FROM `rs-marketmaking.greg_sandbox.market_mapping`
WHERE start_date >= '2026-03-13'
  AND sportsbook = 'Kalshi'
  AND market_type = 'moneyline'
  AND JSON_VALUE(source_ids, '$.market_id') NOT LIKE '%GAME%'
ORDER BY start_date, home, away, side
```

To delete them:

```sql
DELETE FROM `rs-marketmaking.greg_sandbox.market_mapping`
WHERE start_date >= '2026-03-13'
  AND sportsbook = 'Kalshi'
  AND market_type = 'moneyline'
  AND JSON_VALUE(source_ids, '$.market_id') NOT LIKE '%GAME%'
```

## Fix

Commit `613cfe0` (2026-03-15).  Fetch now discovers series
dynamically via the Kalshi `/series` endpoint.  Mapper groups
tournament markets separately and attaches them to already-resolved
games by team code matching.
