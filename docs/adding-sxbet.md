# Adding SX Bet

SX Bet (sx.bet) is a peer-to-peer exchange; the SX RFQ maker (`mmsxbetrfq`)
quotes parlays whose legs name `(marketHash, bettingOutcomeOne)`.  Until
this integration `SX Bet` reached `markets_us.market_mapping` only as an
`OPTIC_MAPPED_SPORTSBOOKS` passthrough -- a row when, and only when, Optic
carried an SX odd -- so the maker mapped every leg itself, by team name.
The owner's goal (2026-10-13): the maker reads mmmapper's rows only, so the
mapping lives in one place with the estate's checks.

## Why bother -- the coverage hole (measured 2026-10-13, prod)

SX's live book was 12,272 markets (`GET /markets/active`).  mmmapper had
rows for 5,098 of them.  Optic carries SX for only part of the book: it
returns **zero** `sx_bet` odds for Leverkusen v Freiburg (2026-10-18) while
SX lists the match and Optic returns 139 Polymarket odds on it.  Bundesliga
had 1,592 Polymarket rows and 0 SX rows in `market_mapping` -- the league
was wired; the passthrough simply had nothing to pass.

| SX live book | markets |
|---|---|
| mmmapper (Optic passthrough) rows | 5,098 |
| on events Optic links to a fixture (`source_ids.event_id`) but no row | 2,035 |
| on events Optic never links (soccer 4,375, NBA 508) | 5,139 |

## The id stamp -- and the trap in it

Optic's `source_ids["SX Bet"]` is `{event_id: <sportXeventId>, market_id:
<marketHash>, selection_id: "<marketHash>|one" | "<marketHash>|two"}`.
**The suffix is the MAKER's outcome**: Optic reads SX's order book, where an
order on outcome one is what a taker on outcome *two* lifts.  So the `|one`
row is the selection a taker gets on SX outcome two.

Proof: hash `0xe995d877...` has SX `outcomeOneName` "Over 5.5"; its `|one`
row says `under`.  24 h of prod SX RFQ legs keyed this way agreed with the
maker's own mapping on 91/91 sides; keyed the naive way, on 0.
`sxbet.selection_id(hash, outcome)` is the only place the suffix is
written; constructed rows use Optic's exact shape, so downstream cannot tell
a constructed row from a passthrough one.  (Until ~2026-08 the
`selection_id` was a rotating orderHash and the passthrough was unusable.)

## Shape of the integration

| Path | Role |
|---|---|
| `fetch/sxbet.py` | public `/markets/active`, all pages (max `pageSize` 100) → `sxbet_markets.jsonl` |
| `mappers/exchanges/sxbet.py` | `SxMarket`, `SxConfig`, outcome parsing, `build_rows`, `selection_id` |
| `mappers/exchanges/sxbet_leagues.py` | SX `leagueId` → league slug (tennis by label prefix); `config_for` |
| `mappers/vocab/sxbet_markets.py` | SX type id → canonical `MarketType`, per sport |
| `mappers/exchanges/sxbet_pass.py` | catalogue grouping, fixture match, sides, cross-check |
| `mappers/pipeline.py` | `LeagueConfig.SXBET`, `attach_sxbet_row`, `_run_sxbet_pass`, record `sxbet` |
| `mappers/seed/tip_factories.py` | `with_code_sxbet` (code decides, like DKEX) |
| `BigQuery/load_mappings.py` | the constructed `SX Bet` row, gated on `"SX Bet" not in optic_src` |

### Typed fields (each convention measured on the 12,272-market book)

* `type` is the market AND its period (53 = Asian handicap halftime); vendor
  table captured in the workspace's `docs/sxbet/data_samples/sx_market_types_2026-10-13.md`.
* A spread's `line` is outcome ONE's handicap ("Dodgers -1.5" / "Brewers
  +1.5", line -1.5): 0 exceptions in 5,079 spreads.  A level handicap is
  unsigned ("Eintracht Frankfurt 0").
* A 2-way moneyline's outcome one is `teamOneName`: 0 exceptions in 574.
* The 1X2 (type 1) is three binaries: "X" / "Not X", "Tie" / "Not tie".
  Only the affirmative outcome is built -- "Not X" is the double chance on
  the other two, and the SX maker refuses every Not-X leg (owner decision
  2026-07-16).  Lifting that is an owner call, then a double-chance row here.
* The period also sits on the outcome names ("(1st half)", "(sets)",
  "(1st 5 Innings)") and is stripped before names are read.

### Crosswalk

Every entry in `mappers/vocab/sxbet_markets.py` is one Optic already agrees
with: each (sport, type) was read off the SX markets Optic itself maps, and
each landed on exactly one canonical type.  Types Optic never maps for SX
stay out until a rules check (soccer 52 "12", American-football half/quarter
winners, hockey totals "including overtime", baseball F5 "12", anytime TD).

### League table

`sxbet_leagues.SLUG_BY_LEAGUE_ID` is evidence-backed, entry by entry:
Optic-linked leagues from Optic's own event links; the rest by kickoff
second + a distinctive word of each team name landing on exactly one Optic
fixture, all in one Optic league the mapper runs (match counts in the file).
Not mapped: SX 1516 "Women's World Cup" (the women's WC qualifiers are not in
the run set -- onboard the league first) and 1593 "Olympics Womens Soccer" (no
fixture matched).

### Fixture and side resolution (`sxbet_pass`)

1. **Optic's event link first.**  An Optic odd on one of the run's fixtures
   that carries `source_ids["SX Bet"].event_id` names the SX event's fixture.
   An event Optic puts on two fixtures is trusted nowhere.
2. **Sides on a linked event** come from Optic's own SX ids where it has
   them: an outcome Optic maps to a row names that row's side, so SX's long
   college names ("Tulane Green Wave") need no name rule.  The name matcher
   must not disagree.
3. **Otherwise kickoff + both names**: exact UTC minute, then the UTC day,
   both SX team names landing on different sides of exactly one candidate
   (`dkex_names.team_side_for`, club short names for soccer;
   `person_side_for` for tennis / MMA).  **No one-name fallback**: DKEX's
   "anchored" rule (exact minute, one team lands, unique fixture) was dropped
   for SX on 2026-10-14 (owner: mis-mapping risk to a minimum) -- an event
   whose two teams do not both land stays unmapped.
4. **Guard #3** (`attach_sxbet_row`): no Optic row for the canonical key →
   dropped, never standalone.
5. **Guard #4** (Novig): a constructed (hash, side) Optic maps to the SAME
   row is left to the passthrough; to a DIFFERENT row is a disagreement and
   is dropped.  On the first ten-league run that was **0 conflicts in 4,512 overlaps**.

One marketHash carries both outcomes, so a second hash landing on an already
stamped row is `duplicate` and dropped (no satellites; no SX market lists one
canonical bet twice today -- the tally would show it).

## Coverage, measured

Local run 2026-10-13 ~16:30Z, prod inputs (Optic fetch + the live SX book),
ten leagues:

| league | events matched | stamped (new) | agree with Optic |
|---|---|---|---|
| germany_bundesliga | 9 / 9 | 279 | 0 (Optic carries no SX here) |
| netherlands_eredivisie | 9 / 9 | 241 | 0 |
| liga_mx | 8 / 9 | 216 | 0 |
| mls | 30 / 30 | 362 | 570 |
| ucl | 18 / 18 | 253 | 493 |
| ncaaf | 60 / 62 | 1,733 | 1,320 |
| nfl | 14 / 27 | 886 | 1,474 |
| wta | 14 / 15 | 280 | 514 |
| atp_challenger | 8 / 8 | 114 | 0 |
| nhl | 16 / 16 | 33 | 141 |

Unmatched events were beyond Optic's fetch horizon (NFL in November) or a
single NCAAF name pair.  `SXBET_DEBUG=1` prints examples per failure reason.

The same run over **every** SX-mapped league (46 slugs, 2026-10-13 ~17:00Z):
478 of 569 events matched, **9,027 rows stamped that Optic never mapped,
7,639 overlaps with Optic's own SX ids, 0 conflicts**.  SX markets with an
mmmapper row on at least one side went from **5,098 to 8,863 of 12,369**
(the maker's own name join held ~9,100).  What is left: fixtures past Optic's
horizon (NBA's season had not started; most of the 508 NBA markets), lines
Optic does not price (1,879 rows), and leagues not in the run set (women's WC
qualifiers).

## Wiring a new league

1. Find SX's `leagueId` (`GET /leagues/active`) and prove the pairing on
   live events -- Optic's event link, or kickoff + names on one Optic league.
2. Add `leagueId: "<league slug>"` to `SLUG_BY_LEAGUE_ID` in
   `mappers/exchanges/sxbet_leagues.py` with the evidence in the comment.
   The slug must already be in the run set (its Optic fixtures fetched).
   The run set still loads from the retiring tip (`load_tip_leagues` in
   `mappers/seed/tip_leagues.py`); that is debt, so never add a tip row to
   get a league in.
3. Add a case to `tests/mappers/test_sxbet.py` or
   `tests/mappers/test_sxbet_pass.py`, run
   `GCP_PROJECT=rs-marketmaking .venv/bin/pytest -q`, open the MR and read
   the `regression:mapping-gate` row delta. Removed rows need a waiver in
   `regression/waivers.toml`.

A new SX market type shows up as `unmapped type(s)` on the pass's summary
line: read what Optic maps it to before adding it to the crosswalk.

## What is not wired yet

* AI validation does not judge SX, and there is no SX side-check
  after a load (`plans/sxbet-mmmapper-mapping-plan.md` in the workspace).
* Name pins are code (`mappers/exchanges/sxbet_names.py`, by Optic competitor id, one evidenced line each);
  gap-propose's SX classifier reports `needs_name_or_optic` gaps; each is a code change there, not a console card.
