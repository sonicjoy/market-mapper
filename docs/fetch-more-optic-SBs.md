# Fetching More Optic Sportsbooks for Better Coverage

## Context

Optic only returns odds for a fixture if at least one of the
requested sportsbooks has prices for that market.  The API limits
each request to 5 sportsbooks.  We currently request exactly 5:

    kalshi, prophet_x, fanatics, draftkings, betmgm

Markets that only exist on books outside that set are invisible to
us.  The BQ `prices_dedup_state` table shows ~20 sportsbooks with
significant row counts — the current 5 cover roughly 35k of ~145k
non-Kalshi/PX rows.  Betano alone has 32k.

## Why we aren't adding more sportsbooks now

We investigated missing Kalshi spread coverage on the dashboard
(2026-03-17, MIA @ CHA fixture `2026031788F6F987`).  The 01:32
fetch had only 2 point_spread entries; a fresh fetch at 02:25 (same
sportsbooks) had 52 — including Kalshi `source_ids` at many lines.
The gap was a **timing** issue: alternate spread markets activate
closer to game time, not a sportsbook coverage issue.

We probed the same fixture with 5 extra sportsbooks (betano,
fanduel, unibet, hard_rock, pinnacle).  Findings:

- The extra SBs added **integer lines** (±1, ±2, ±5, ±6, etc.)
  that the current SBs don't return.
- Kalshi spread markets are all **half-point lines** (1.5, 2.5,
  4.5, ...).  The current 5 SBs already produce Optic odds at
  those half-point lines, so the extra SBs don't improve Kalshi
  spread matching.
- The extra SBs produced 68 raw entries vs. 66 from the current
  SBs — comparable volume, just different lines.

For the markets we currently care about (moneyline, point_spread,
totals on Kalshi and Prophet X), the current 5 sportsbooks provide
sufficient Optic coverage.  The main bottleneck for spread coverage
is market activation timing, not sportsbook breadth.

## Why we might want more sportsbooks later

The untested scenario is **markets where none of the current 5
books have prices at all**.  If a market type only appears on books
like Pinnacle or Betano, it's invisible to us today.  We haven't
quantified how often this occurs for markets that Kalshi or PX also
offer.  When we expand to more exotic market types or additional
exchanges, this could become relevant.

Adding more sportsbooks would also increase the density of Optic
odds across more lines, which matters if we start caring about
mapping accuracy at every line rather than just confirming coverage
exists.

## How to add more sportsbooks

### The API mechanism

The `sportsbook` param on `/fixtures/odds` accepts up to 5 values.
To cover N sportsbooks we make ceil(N/5) requests per fixture, each
with a different batch of 5.  The response structure is the same
for every request: a fixture dict with an `odds` array of per-
sportsbook entries.

### Concatenation and deduplication

Each raw odds entry has an ID like:

    game_id:sportsbook:market_id:selection

The same market across different sportsbooks produces distinct raw
entries that share a clean_id (the ID with the sportsbook segment
removed).  `deduplicate_odds` already handles this: it strips the
sportsbook, merges entries with the same clean_id via `clean_odds`,
and accumulates `source_ids` from Kalshi and Prophet X.

To support multiple requests we concatenate the `odds` arrays from
all responses for the same fixture and feed the combined list to
`deduplicate_odds`.  No changes to the dedup logic are needed.

**Constraint:** each sportsbook must appear in exactly one batch.
The assert `sportsbook not in accumulated_source_ids` (line 124 of
`fetch/optic.py`) enforces this.

### Implementation sketch

In `get_fixture_odds`:

```python
ALL_SPORTSBOOKS = [
    # Batch 1 (must-haves: our exchanges + high coverage)
    "kalshi", "prophet_x", "draftkings", "fanatics", "betmgm",
    # Batch 2
    "betano", "fanduel", "unibet", "hard_rock", "betfair_exchange",
    # Batch 3
    "bodog", "pinnacle", "888sport", "bc_game", "polymarket",
    # Batch 4
    "dafabet", "bwin", "sbobet", "robinhood", "4cx",
]

def _sportsbook_batches(sportsbooks, batch_size=5):
    for i in range(0, len(sportsbooks), batch_size):
        yield sportsbooks[i : i + batch_size]
```

For each fixture, make one API call per batch, then:

```python
combined_odds = []
for batch in _sportsbook_batches(ALL_SPORTSBOOKS):
    params = {"fixture_id": fixture_id}
    for sb in batch:
        params.setdefault("sportsbook", []).append(sb)
    result = get_optic(url, headers, params)
    combined_odds.extend(result[0]["odds"])

fixture_data = result[0]          # fixture-level fields are the same
fixture_data["odds"] = combined_odds
return fixture_data
```

### Trade-offs

**Cost:** Currently 1 API call per fixture.  With 20 sportsbooks
that's 4 calls per fixture (4x API usage).  With the 0.2s sleep
between fixtures, fetch time per fixture also increases.

**Coverage gain:** Based on BQ row counts, the additional 15
sportsbooks roughly triple the raw odds volume.  The deduplication
step collapses most of this, but markets that only one niche book
carries will now appear.

**Risk:** `clean_odds` asserts when two entries for the same
clean_id have same-length but differing values for a non-volatile
field.  More sportsbooks means more merge pairs, increasing the
chance of hitting this assert on data inconsistencies.  If it fires,
we need to decide whether to relax the assert (pick one value) or
investigate the mismatch.

**This fired on 2026-07-29** and killed five pipeline ticks, because
`fetch.optic` is REQUIRED.  Optic quoted Marina Spasic's moneyline on
UFC fixture `20260801BA4BBFF1` under two competitor ids — six of nine
books used one that was not in the fight at all.  Resolution: neither
relax nor investigate case by case, but arbitrate `team_id` against the
fixture's own `home_competitors`/`away_competitors` (`_prefer_team_id`),
which is the same authority the mapper's `team_map` is built from.  Note
a majority vote would have picked the wrong id here.  A fixture whose
data still cannot be merged is now skipped with an `ALERT:` line rather
than failing the run (`fetch_processed_fixture`).

### Sportsbook API identifiers

The BQ table uses display names (e.g. "Betfair Exchange").  The
Optic API uses snake_case identifiers (e.g. "betfair_exchange").
Before implementing, verify the exact API identifiers — the names
above are guesses based on the display names.  Use `--explore` mode
(`python -m fetch.optic_explore --explore <league>`) or the API docs
to confirm.

### Sportsbook priority

Not all 20 books are equally useful.  A pragmatic first step is to
add one batch (5 more books) chosen by coverage volume:

    betano, fanduel, unibet, hard_rock, betfair_exchange

This covers the top non-current books by row count and doubles
coverage from 1 to 2 requests per fixture.

## Probe script

`scripts/probe_spread_sbs.py` fetches odds for a single fixture
with different sportsbook sets and compares what point_spread lines
come back.  Useful for testing whether additional sportsbooks would
improve coverage for a specific game.

    .venv/bin/python scripts/probe_spread_sbs.py <fixture_id>

## Results: expanding from 5 to 20 sportsbooks (2026-03-17)

### What we did

Replaced the single `SPORTSBOOKS` list with `SPORTSBOOK_BATCHES` in
`fetch/optic.py`.  Each batch is one API request (max 5 per request):

    Batch 1: kalshi, prophet_x, draftkings, fanatics, betmgm
    Batch 2: betano, fanduel, hard_rock, betfair_exchange, unibet
    Batch 3: bodog, 888sport, bc_game, polymarket, dafabet
    Batch 4: pinnacle, bwin, sbobet, robinhood, 4cx

Kalshi and Prophet X stay in batch 1 so the pipeline can cross-check
mappings against their Optic source_ids.  They only need to appear in
one batch — `deduplicate_odds` merges across the concatenated array
from all batches.

### Before and after

Compared the 02:25 fetch (5 sportsbooks) against the 03:42 fetch
(20 sportsbooks).  Same date, same leagues (NBA + NCAAB), both full fetches.

    Metric                   5 SBs     20 SBs
    ─────────────────────────────────────────
    Total mapping rows       5,544     15,675
    Games                       35         37
    Market types                24         24
    Rows with Kalshi match   1,364      1,853
    Rows with PX match       3,780      6,001

The 20-SB fetch produced 10,136 additional mapping rows.  Of those:

- 2,459 (24%) matched a Kalshi or PX market — these are lines where
  we now have Optic odds to compare against exchange prices that the
  old 5 sportsbooks couldn't surface.
- 7,677 (76%) are Optic-only — no current Kalshi or PX market at
  those lines.  Useful for taxonomy discovery but not active mapping.

No new market types appeared.  The gain is **line density**: more
points/spreads/totals at which Optic odds exist, particularly at
integer lines and deep alt lines that only books like Betano, Unibet,
and Pinnacle carry.

Two entirely new games appeared (UIC @ CAL, JOES @ CSU) — NCAAB
fixtures where none of the original 5 sportsbooks had prices, making
them previously invisible.

### Example 1: OKC @ ORL — Jalen Suggs player points

The old 5 sportsbooks returned zero Optic odds for Jalen Suggs
player points.  The expanded set returned 35 deduped entries across
24 lines (4.5 through 29.5).  Of those, 22 rows matched a Prophet X
market — Suggs player points markets that PX offers but that were
invisible to us before because no Optic sportsbook in the old set
carried prices for them.

    Old lines:   (none)
    New lines:   4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5,
                 13.5, 14.5, 15.5, 16.5, 17.5, 18.5, 19.5, 20.5,
                 21.5, 22.5, 23.5, 24.5, 25.5, 26.5, 29.5

### Example 2: TEX @ NCSU — 1st half point spread

The old fetch had 8 rows covering 6 lines near the main line
(-1.5 to +1.5).  The expanded set added 22 rows with PX matches
at deep alt lines out to ±16.5.

    Old lines:   -1.5, -1.0, -0.5, 0.5, 1.0, 1.5
    Added lines: -16.5, -14.5, -13.5, -11.5, -10.5, -8.5, -7.5,
                 -5.5, -4.5, -2.5, 2.5, 4.5, 5.5, 7.5, 8.5,
                 10.5, 11.5, 13.5, 14.5, 16.5

### Example 3: UIC @ CAL — entirely new game

This NCAAB fixture was invisible in the old fetch — none of the
original 5 sportsbooks had prices for it.  The expanded set surfaced
it with 77 total mapping rows, of which 27 matched Kalshi or PX:

    moneyline:        2 matched rows
    point_spread:     4 matched rows
    game_total:      10 matched rows
    team_total:       8 matched rows
    1h_winner_3way:   3 matched rows

This is the scenario the earlier investigation hadn't tested: a
fixture where the market exists on Kalshi/PX but no original
sportsbook had prices, so Optic never returned it.

### Cost

4 API calls per fixture instead of 1.  With the 0.2s sleep between
batches, each fixture takes ~0.6s longer.  For a typical fetch of
~30 fixtures, total fetch time increases by ~18s.
