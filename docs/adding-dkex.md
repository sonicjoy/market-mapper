# Adding DKEX (DraftKings Exchange)

DKEX is DraftKings' own CFTC-regulated event-contract exchange, built on
the Railbird DCM it acquired.  We are standing up as an RFQ **responder**
on its combo market (`~/Code/mm-dkex`), which prices a 2-8 leg combo in a
3-second last-look window.  Every leg of that combo is an ordinary DKEX
single-market ticker, so **nothing can be priced until those tickers are
mapped to our canonical contract identity** -- that is what this
integration is for.

DKEX hands us **no Optic ids** (no fixture, team or player id), but its
REST catalogue **types every market**.  Identity comes from those typed
fields, written out explicitly; **the ticker is an opaque id and is
never parsed** in the mapping path.

## Where the catalogue comes from

| Source | Auth | Freshness | Use |
|---|---|---|---|
| `GET /api/v1/markets` + `POST /api/v1/markets/queries` | none (prod and staging) | live | **production** |
| `railbirdexchange.com/reports/daily-market` CSV | none | **T+1** | raw-table seed, backfill |

`fetch/dkex.py` implements both behind one normalized row shape and
defaults to `--source api`; `--source reports` must be asked for by name
and prints a warning.  The CSV carries only the symbol, so a report row's
typed fields are all `None`; the mapper counts it as `untyped` and skips
it.  It is never back-filled by slicing the symbol.

Prod (`https://api.railbirdexchange.com`, the `DKEX_API_BASE` default
since 2026-10-02) and staging (`https://api.staging.railbirdexchange.com`,
set `DKEX_API_BASE` to it) both answer without a key, with the same
endpoints and row shape.  A key is sent only when `DKEX_API_KEY` is set
or `DKEX_USE_API_KEY_SECRET=1`.

## The typed fields

`POST /api/v1/markets/queries` (batches of 1000) returns, per market, and
`normalize()` flattens onto the catalogue row:

| typed field | row key | what it is |
|---|---|---|
| `parameters.statAchievement` | `stat_achievement` | market token: `WIN`, `MOVY`, `TPTS`, `TMPTS`, `PREY`, `DWIN`, `BTMSC`, ... |
| `parameters.timePeriod` | `time_period` | `FG`, `H1`, `H2`, `Q1`-`Q4`, `IT5`, `I1`-`I9`, `MTH`, ... |
| `parameters.participant` | `participant_id` | `DKT_...` team or `DKP_...` player; absent on game-scoped markets |
| `parameters.strikePrice` | `strike_price` | decimal string on the wire (`"3.5"`), float on the row |
| `parameters.outcomeType` | `outcome_type` | `GTE` (>=) or `GT` (>); absent on moneylines |
| `metadata.competitionId` | `competition_id` | the fixture handle every market on one game shares |
| `metadata.participants[]` | `participants` | `[{id, name, role}]`; `role` is `home`/`away` on team markets, absent on props |
| `subTopic` | `sub_topic` | the league (`NFL`, `NCAAF`, `Brazil - Serie A`) |
| `metadata.leagueName`, `leagueId`, `intakeEventId`, `competitionStartTime` | `league_name`, `league_id`, `intake_event_id`, `event_start` | kept for provenance / start time |

`mappers/exchanges/dkex.py` turns a row into a `DkexMarket`; `DkexConfig`
classifies on `(statAchievement, timePeriod)` -- the same token values the
old symbol segments carried, so the crosswalks in
`mappers/vocab/dkex_markets.py` did not change.

**League.**  `subTopic`, mapped to the venue token by the explicit
`LEAGUE_TOKENS` table in `mappers/exchanges/dkex_leagues.py` (`NCAAF` and `NCAA FCS` -> `CFB`, `Brazil - Serie
A` -> `BSA`, ...); a subTopic that already is the token (`NFL`, `MLB`,
`WNBA`, `NBA`) passes through.  `leagueName` agrees with `subTopic` for
every team sport but names the tournament for tennis (`ATP Chengdu`).

**Sentinels are absences.**  A game total, both-teams-to-score, the draw
leg of a 3-way and "No Touchdown Scorer" simply have no
`parameters.participant`.  Only a game total builds from one; every team
or player market needs a resolved participant or drops whole.

## The things that are easy to get wrong

1. **Maturity is not the event start.**  The report's maturity is the
   event time plus exactly 30 days.  The REST row carries
   `competitionStartTime`; only the report path subtracts
   `SETTLEMENT_LAG`.

2. **GT is not GTE.**  `outcomeType == GT` settles on a strict `> strike`
   and keys on the next half-point line (`> 59.5` is over `60.0`).
   Staging on 2026-09-28 lists only `GTE`; the rule stays.

3. **DKEX abbreviates pro cities, Optic spells them out.**  Participant
   names are `DEN Broncos`, `NY Jets`, `LA Dodgers`, `CHI White Sox`;
   Optic has `Denver Broncos`, `New York Jets`.  The shared `names_fit`
   resolves **none** of the 32 NFL, 30 MLB or 8 WNBA staging names on its
   own.  `mappers/exchanges/dkex_names.py` adds one narrow rule: an
   upper-case first word of at most three letters that is the Optic
   abbrev, the initials of the Optic city, or a prefix of its first word,
   followed by exactly the Optic nickname.  College names are school
   names and fit as they are.

4. **`MOVY` is the spread, as a one-sided threshold.**  MOVY on Denver
   with strike 15.5 settles on "DEN wins by >= 15.5" -- the yes side of
   the -15.5 spread on Denver, with the no side the opponent at +15.5.

5. **The period is part of the key.**  `TPTS/FG` vs `TPTS/H1`, `TRUNS/FG`
   vs `TRUNS/IT5`.

## Fixture and entity resolution

Markets cluster on `competitionId`.  An event's home and away teams are
the participants its **team markets** (`WIN`, `MOVY`, `TMPTS`) tag with
`role` -- the sibling markets sharing the competitionId.  Player props
list only the player with no role, and `POST /api/v1/events/queries` on a
prop event ticker lists only players too, so a **props-only event** (its
team markets already closed) has no home/away: it is counted as
`no_roles` and not matched, never guessed from `competitionName`.  On the
2026-09-28 staging book that is 24 of 756 NFL events, 10 of 337 CFB, 93
of 642 MLB, 2 of 128 WNBA and 0 of 129 NBA.

Matching (`mappers/exchanges/dkex_pass.py`):

1. **fixture** -- every exact UTC start minute of the event (a postponed
   event keeps its competitionId and can carry two starts), then the UTC
   day, accepting a candidate only when **both** role-tagged names land on
   it, on different sides, and exactly one candidate does.  The day
   fallback survives DKEX's 16:00 UTC placeholder kickoffs.
2. **team** -- `parameters.participant` id -> the event participant with
   that id -> the fixture side its name matched.  A participant that is
   not one of the event's two teams drops the market.
3. **player** -- the participant's name against the fixture's Optic
   player selections, most specific tier first: exact canonical name,
   then `names_close`, then `names_fit`; a tier with two hits is
   ambiguous and resolves to nothing.  (Optic lists multi-player
   selections such as "Jalen Hurts + DeVonta Smith", which a loose fit
   alone would call ambiguous.)

If DKEX's home/away is the opposite of Optic's, sides follow the names
and the event is counted in `swapped_events`.

Names neither matcher can fit -- measured 2026-09-28: `UConn`, `ULM`,
`UMass`, `Miami OH`, `Miami FL`, `Georgia Bulldogs`, `FIU`, `Athletics`
-- are closed in code: `OPTIC_IDS_BY_DKEX_NAME` in
`mappers/exchanges/dkex_names.py` pins each DKEX display name to the Optic
competitor id(s) it names, one line each with the Optic fixture as
evidence (read by `optic_id_side`). Add the pin, add a case to `tests/mappers/test_dkex_pass.py`,
open the MR and read the `regression:mapping-gate` delta.  Do not widen
`names_close` / `names_fit` to get a bind.  The old tip route
(`(dkex, name)` tip aliases, `scripts/submit_dkex_name_aliases.py`, review
cards) is retired.

## The raw table

`BigQuery/load_dkex_raw.py` appends a fetched catalogue to
`raw_ingestion_us.dkex_raw`, one row per market with the record verbatim
in `data`.  Its `kind` column carries the SOURCE (`api` / `reports`)
rather than a feed name, because the two DKEX sources differ in
freshness, not in shape -- any query about today's book has to be able to
tell the live catalogue from the T+1 seed.

Seeded in `marketmaking-test` on 2026-09-15 with the 2026-09-14 report:
75,778 open markets, `kind='reports'` (NFL 30,880 / CFB 21,841 /
MLB 15,133 / WNBA 2,451, plus KBO, NPB and the soccer leagues).

```bash
python -m fetch.dkex --source reports --out-dir data/<date>/<hh_mm>   # dev seed
python -m BigQuery.load_dkex_raw --markets data/<date>/<hh_mm>/dkex_markets.jsonl
```

The test table was created by hand for this seed; the schema and its
Terraform now live in the infra repo
(`modules/general_us/schemas/raw_ingestion/dkex_raw.sql` and
`dkex_raw.tf`) so prod does not depend on a hand-made table.

## The pipeline pass

`_run_dkex_pass` in `mappers/pipeline.py`, gated per league on
`LeagueConfig.DKEX`.  It reads `dkex_markets.jsonl`, keeps only open
(`active` / `Open`) contracts (a settled contract maps fine and quotes
into nothing), skips untyped rows, clusters by `competitionId`, resolves
the fixture and entities as above, then `dkex.build_rows` emits **both
canonical sides of each market** and
`attach_dkex_row` stamps them onto Optic rows.  A contract Optic did not
price is dropped, never emitted standalone -- without an Optic market_id
there is nothing for `load_mappings` to join on (the Novig discipline).

### Satellite tickers -- the thing that is easy to miss

One canonical bet legitimately has **more than one DKEX ticker**:

* a game's moneyline is listed as two markets, one per team (`WIN` with
  each team as participant), and
* a player prop is listed as the bare token and its `OU` twin
  (`PPAY` / `PPAYOU`), which settle identically.

Stamping onto the canonical row would let the second ticker overwrite
the first.  Measured 2026-09-15 that lost one of the two moneyline
tickers on **92 of 92** matched events -- and the RFQ responder resolves
a leg BY TICKER, so half the moneyline flow would have been unquotable.
So `attach_dkex_row` appends a **satellite** row instead, exactly as
`attach_crypto_row` does for twin FIX symbols: the satellite inherits the
parent's `optic_id`, sets `dkex_satellite`, and `flatten_rows` emits DKEX
alone for it so it cannot collide with the parent's Optic passthrough
books.  `_source_identity_sql` extends the BigQuery MERGE key with
`market_id|selection_id` for DKEX for the same reason it already does for
Kalshi -- without that the second ticker collides on MERGE and the fix is
undone in the warehouse.

## Soccer

`dkex_markets.SOCCER`, on the soccer `DkexGenericProfile`, for the 13
slugs in `VENUE_TOKEN_BY_SLUG` (`mappers/exchanges/dkex_leagues.py`) (EPL, La Liga, UCL,
UEL, UECL, Serie A, Bundesliga, Ligue 1, Brasileirao, Argentina, MLS,
Liga MX, club friendlies).  Every soccer contract's rules text (read
2026-09-29) settles on **90 minutes plus stoppage time**, extra time and
penalties excluded -- the basis Optic's soccer markets use.

| DKEX | canonical | yes | no |
|---|---|---|---|
| `DWIN/FG`, team | `moneyline_3way` | that team | **`double_chance`** on the other two (away-or-draw) |
| `DWIN/FG`, no participant | `moneyline_3way` | `_TIE` | **`double_chance`** home-or-away |
| `MOVY/FG` | `point_spread` (Optic `asian_handicap`) | team at -N.5 | opponent at +N.5 |
| `TGLS/FG` | `game_total` | over | under |
| `BTMSC/FG` | `btts` | yes | no |
| `SGL1/FG`, player | `player_goals` 0.5 | over | under |

* **The draw is an absence.**  The draw leg has no `parameters.participant`;
  a team leg always has one (an id that does not resolve still keeps its
  participant), so a team leg is never read as the draw.
* **3-way No is double chance** by the same equivalence as Kalshi soccer
  (`mappers/kalshi_complement.py`), and it holds only because both
  settle on the 90-minute result.  The three legs' six rows are six
  distinct canonical rows, so no satellites are needed.
* **Goalscorer.**  A player who does not enter the match settles at the
  last fair price, not No -- the usual anytime-scorer void.  "No
  Goalscorer" has no participant and drops as unbuildable.  Optic listed
  no `player_goals` on these fixtures on 2026-09-29, so goalscorers map
  but have nothing to stamp onto yet; 143 goalscorer-only games carry no
  team markets and count as `no_roles`, like props-only football games.
* **Club names.**  DKEX writes the short name (`Palmeiras`, `Dortmund`,
  `Man City`), Optic the official one (`SE Palmeiras`, `BV Borussia 09
  Dortmund`, `Manchester City FC`).  `dkex_names.club_short_fits`, on for
  soccer only (`DkexConfig.club_short_names`), accepts a DKEX name whose
  every word, in order, is an Optic word or its start (3+ letters), with
  one 4+ letter word landing; apostrophes, `ł`, `ø`, `ß` fold.  The
  exactly-one-side rule still applies: `Sao Paulo` against `São Paulo FC`
  and `Santos FC Sao Paulo` is no side.  Names it cannot fit need an
  `OPTIC_IDS_BY_DKEX_NAME` pin in `mappers/exchanges/dkex_names.py`
  (`Utd` alone reads as `United`); measured 2026-09-29: `Wolves`, `Cologne`,
  `RB Leipzig`, `Paris St-Germain`, `Auxerre`, `Monza Brianza`,
  `Sparta Prague`, `Atl Paranaense`, `Botafogo RJ`, `Internacional RS`,
  `Remo Belem`, `Vitoria Salvador`, `Sao Paulo`, `Atletico Tucuman`,
  `Deportivo Riestra`.

Colombia Primera (`colombia_primera_a` -> `CPL`), Saudi Pro League
(`saudi_pro_league` -> `SAPL`) and Eredivisie (`netherlands_eredivisie` ->
`NER`) read the same soccer crosswalk; tokens are DKEX's ticker prefixes for
subTopics `Colombia - Primera`, `Saudi Arabia - Premier` and
`Netherlands - Eredivisie` (2026-11-03).  Turkey Süper Lig (`TSL`,
`Turkey - Super Ligi`) is not mapped: the run set has no Süper Lig slug yet.

## College basketball

`ncaab` -> `NCAAB` in `VENUE_TOKEN_BY_SLUG`; DKEX's `subTopic` and the ticker
prefix are both `NCAAB`, so `LEAGUE_TOKENS` needs no entry.  It reads the
existing `BASKETBALL` crosswalk (`WIN`, `MOVY`, `TPTS`; MOVY on team X at
strike s is X -s, yes side).

## Tennis, UFC, NBA preseason

Match / bout / game winner only, one crosswalk entry each:
`dkex_markets.TENNIS` (`WIN/MTH`), `dkex_markets.UFC` (`WIN/FT`), and the
NBA's existing `BASKETBALL` table.  Each is a 2-way market with no draw
leg, checked against DKEX's own `rules.description`:

* **Tennis** -- the winner's leg resolves Yes, the other No; a match
  abandoned before a set is played settles at the last fair price.  No
  on one player is Yes on the other.
* **UFC** -- a win by any method is Yes; a draw or no contest settles at
  the last fair price, the same as Optic's 2-way moneyline pushing.
* **NBA** -- `subTopic` `NBA Preseason` is the `NBA` token
  (`LEAGUE_TOKENS`): Optic's `nba` league carries preseason games as
  ordinary fixtures.

Tennis players and fighters are people, so fixture sides resolve through
`dkex_names.person_side_for` (`DkexConfig.person_names`): the exact
canonical name, then `names_close` (same first and last word), unique
side only.  The looser `names_fit` tier is not used for sides.

Tennis `subTopic` cannot place a match in a league: DKEX writes the
tournament (`ATP Chengdu`, `WTA Adana 125`) or just the tour (`ATP`),
and changed it between two fetches on 2026-09-29.  So the tennis pass
reads every `WIN/MTH` event (`DkexConfig.any_league`) and the fixture
match decides the league: both players must land on one Optic fixture
in that league.  A pairing Optic does not list (staging had
`Anna Siskova vs Fiona Crawley`; Optic had Crawley v Pridankina) and
doubles pairs match nothing.  Bout and match start times are estimates on
both sides (DKEX 02:15, Optic 01:20 for the same bout), so these land
on the same-UTC-day unique fallback.

## Coverage, measured

Local run 2026-09-28: the full staging REST book (568,780 active singles,
all typed, 0 untyped), Optic fixtures fetched the same hour with a
168-hour horizon, and the 2026-09-15 offline SoT fixture that carries the
`dkex` exchange rows.  The same inputs were run through the previous
symbol-parsing pass (origin/main `faa0073a`) for comparison.

| league | events matched (typed / symbol) | stamped + satellites (typed) | (symbol) |
|---|---|---|---|
| NFL | 16 / 16 | 3,821 + 89 | 3,574 + 75 |
| CFB | 50 / 56 | 7,996 + 98 | 8,464 + 98 |
| MLB | 4 / 4 | 2,261 + 8 | 2,104 + 42 |
| WNBA | 4 / 4 | 1,586 + 8 | 1,514 + 8 |

Per (ticker, side), the two paths agree on every contract both stamp.
The differences:

* **493 contracts only the typed pass stamps**, all player props whose
  name the 4-character code could not derive (`Luther Burden III`) or
  whose code collided.
* **37 wrong stamps the symbol pass made, now gone**: `Matt Olson` and
  `Mauricio Dubon` both derive `MAON`, and the old pass put Olson's
  contracts on Dubon's Optic rows (34), and `Nia Brodie` onto
  `Nia Coffey` (3).  By name they resolve apart.
* **6 CFB fixtures only the symbol pass matched** (`UConn`, `ULM`,
  `UMass`, `Miami OH`, `Miami FL`, `Georgia Bulldogs`): it accepted a
  fixture on ONE team's code.  The typed pass requires both role-tagged
  names; these close with `OPTIC_IDS_BY_DKEX_NAME` pins.

The dominant unstamped term is still supply: DKEX lists every half point
of every ladder, and a rung Optic never priced has no canonical row.

## What is wired, and what is not

Wired: `fetch/dkex.py` (typed normalization), `mappers/exchanges/dkex.py`
(typed record, config, row construction), `dkex_catalogue_read.py`,
`dkex_pass.py`, `dkex_names.py`, `mappers/vocab/dkex_markets.py`,
`DkexGenericProfile` + the `LeagueConfig.DKEX` thread through
`mappers/seed/`, `attach_dkex_row` + satellites in `mappers/pipeline.py`,
the `DKEX` emit and MERGE-key extension in `BigQuery/load_mappings.py`,
`BigQuery/load_dkex_raw.py`.  Combos are told apart by
`marketProductTypeName == "COMBO"` / `legs`, never by the ticker.  (The
console / Mapper Chat DKEX tools in `mappers/control_plane/` are retired.)

Not yet wired, in dependency order:

1. **League set.**  `with_code_dkex` (`mappers/seed/tip_factories.py`)
   sets DKEX from `VENUE_TOKEN_BY_SLUG` alone and ignores any tip `dkex`
   row.  A new DKEX league is a line in that table plus a test
   (`tests/mappers/test_dkex.py`) and the gate delta, provided the Optic
   league is already in the run set.
2. NHL, NBA periods, tennis and UFC beyond the winner, and the remaining leagues: needs crosswalks (and
   football `PAST`/`PTKA`/`PTKL`, which staging lists and no crosswalk
   maps).
3. Prod.  Everything above is measured on staging; no prod host or
   credential has been issued.
