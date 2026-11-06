# Adding Novig (NBX)

Novig is a peer-to-peer sports **exchange**. Before this work it appeared
in `markets_us.market_mapping` only as an `OPTIC_MAPPED_SPORTSBOOKS`
passthrough — we published a Novig row when, and only when, OpticOdds
happened to carry a `Novig` entry in its own `source_ids`. We never
fetched anything from Novig ourselves.

This doc records what that cost us, why Novig is the *easiest* source we
have ever mapped, and the shape of the integration.

## Why bother — the coverage hole (measured 2026-08-14)

Of the **296 fixtures Novig was actively quoting** inside our 168h
horizon:

| | fixtures | |
|---|---|---|
| had Novig rows in `market_mapping` | 132 | 45% |
| in `market_mapping`, but **zero** Novig rows | 79 | 27% |
| fixture absent from `market_mapping` entirely | 85 | 29% |

So **~55% of Novig's live book was invisible to us**, and the gap was not
only at the fixture level. On ATP fixture `20260814BE848BB5` — a fixture
that *did* already carry Novig rows — Optic's passthrough gave us 15 rows
across 5 markets while Novig was actually quoting **40 outcomes across 20
markets**. The passthrough only ever reaches as far as Optic's own
mapping does.

A first live run of this integration stamped **4,972 selections that
Optic never mapped** across just wnba + mlb + mls (313 / 1,418 / 3,241).

## Why it is the easiest source we map: Novig hands us Optic ids

This is the decisive finding, and it is better than Huddle's Sportradar
join (`docs/adding-huddle.md`). The Novig API returns **OpticOdds' own
ids**, on every level we need:

| Novig field | equals | verified |
|---|---|---|
| `event.opticOddsId` | Optic `fixture_id` | 5/5 against `market_mapping`; 100% populated on 2,292 non-future events |
| `competitor.opticOddsId` | Optic team id (the `Fixture.team_map` key) | 158/158 competitors on the live sample |
| `player.opticOddsId` | Optic `Odd.player_id` | 284/284 player-prop markets |

Consequences, all of which make `mappers/exchanges/novig.py` much smaller
than its Kalshi/PX/Polymarket siblings:

* **No `MatchKey(date, home, away)` name matching.** Fixture resolution is
  a dict lookup on the Optic fixture id.
* **No `config/<league>/team_aliases.toml` entries for Novig.** Ever. A
  `NovigConfig` carries only a league name and a market crosswalk.
* **No name normalization drift.** Player entities come from the Optic
  player id, not from spelling.
* **No ticker decoding, no `line_offset`.** The line is an explicit
  numeric `strike` field.

Because there is no guessing anywhere, the rule throughout is **an
unresolvable id is a drop, never a guess**.

## The four things that are easy to get wrong

1. **Sidedness comes from `outcome.index`, never array order.**
   `index 0` = Home / Over / Yes, `index 1` = Away / Under / No — and
   `outcomes[]` is genuinely *not* returned in index order (observed: a
   WNBA assists market listing Under(index=1) first). Trusting position
   silently inverts half the book. `outcome.type` agrees with `index` on
   the markets we map, but the docs warn it is unreliable on three-way
   soccer, so `index` is the only side signal used.

2. **Three-way soccer is three separate Yes/No markets**, not one
   Home/Away market: `MONEYLINE_3_WAY_WIN` (home), `MONEYLINE_3_WAY_WIN`
   (away) and `MONEYLINE_3_WAY_DRAW`, where `No` means "any other result
   including the draw" and has no canonical counterpart. The WIN form
   carries `market.competitor` (whose side the `Yes` leg backs); the DRAW
   form carries none. So a `Shape.THREE_WAY` type emits ONE affirmative
   row and drops the `No` leg — the same handling as Polymarket's
   `THREE_WAY_FIXED`.

3. **Baseball `_1H` is first-five-innings, not a half.** Novig labels the
   market "SF -0.5 1H"; Optic labels the same market `1st_half_run_line`,
   which `leagues/mlb.py` already maps to `FIRST_FIVE_POINT_SPREAD`.
   Mapping these to `FIRST_HALF_*` would key rows that can never merge.
   Note Novig's F5 moneyline is 2-way while Optic/Kalshi price the 3-way,
   so `MONEY_1H` maps to the honest `FIRST_FIVE_MONEYLINE` and mostly
   drops rather than merging onto a differently-settling key.

4. **UFC victory-method markets are `METHOD_OF_VICTORY`, not
   `WIN_BY_KO_SUB_DQ`.** Novig ships one Yes/No market per method
   (`VICTORY_BY_KO_KTO_OR_DQ` / `VICTORY_BY_SUBMISSION` /
   `VICTORY_BY_DECISION`), each carrying `market.competitor`.
   `WIN_BY_KO_SUB_DQ` bundles KO + submission + DQ into one contract and
   would settle differently — but `METHOD_OF_VICTORY` is fighter-scoped
   with the method in `grouping_key`, which is exactly this shape, and
   Optic's `method_of_victory` buckets carry the same canonical keys
   (`fight_props._OPTIC_MOV_SUFFIX`). The method is resolved from
   `market.type` via `fight_props.novig_method_key` and MUST reach
   `grouping_key`: it is part of `pipeline.row_key`, so without it a
   fighter's three method markets collapse onto one key. Only the
   affirmative leg is emitted — Optic emits no `No` side. The fight-level
   `DRAW` stays ignored (Kalshi `draw_or_nc` ≠ Optic `Draw`).

5. **The player entity is `normalize_player_name(odd.selection)`**, NOT
   Optic's own `normalized_selection` field. The latter keeps generational
   suffixes and periods the canonical form strips (`bobby_witt_jr_` vs
   `bobby_witt`, `t_j_rumfield` vs `tj_rumfield`). Using the raw field
   keyed every player prop one character off its Optic twin. The
   source_ids cross-check below caught this on the first live run — every
   Jr/II/period player came back as a CONFLICT.

## Shape of the integration

| Path | Role |
|---|---|
| `fetch/novig.py` | OAuth2 client-credentials → page `/emm/events` → batch `/emm/events/getMarketsByEvents` → `novig_events.jsonl` + `novig_markets.jsonl` |
| `mappers/exchanges/novig.py` | `NovigConfig`, feed model, `build_rows` |
| `mappers/leagues/novig_markets.py` | Shared per-sport market crosswalks |
| `mappers/pipeline.py` | The Novig pass + `attach_novig_row` |
| `BigQuery/load_mappings.py` | Emits the constructed `Novig` sportsbook row |
| `BigQuery/load_novig_raw.py` | Raw stash → `raw_ingestion_us.novig_raw` |
| `infra/run_novig_raw.sh` | 6-hourly whole-book raw cron |

### Guards (identical discipline to Polymarket)

* **Guard #3 — Optic must have priced it.** `attach_novig_row` stamps onto
  an existing Optic row keyed by `row_key`, or drops. Without an Optic
  `market_id` there is nothing for `load_mappings` to join on, so a
  standalone Novig row is never appended.
* **Guard #4 — cross-check against Optic's own Novig ids.**
  `_build_optic_novig_index` maps `outcome_id -> row_key` from Optic's
  `source_ids["Novig"]`. An outcome Optic maps to a *different* row_key
  than we parsed is a side/market disagreement and is **dropped, not
  stamped**; an outcome Optic maps *identically* is left to the
  passthrough so the two paths never both emit for one MERGE key.
  This guard is what caught the player-entity bug above.

### The id triple

Optic's own `source_ids["Novig"]` carries
`{event_id, market_id, selection_id}` — Novig's `event.id`, `market.id`
and `outcome.id`. The constructed rows use the **identical shape**, so a
downstream join cannot tell a constructed row from a passthrough one.
`load_mappings.flatten_rows` gates the constructed emit on
`"Novig" not in optic_src`, exactly as it already does for Polymarket.

## API notes (probed live; the docs disagree with the service)

* Token: `POST /nbx/v1/auth/emm-token` with
  `{grant_type, client_id, client_secret}`. Credentials are
  `novig_client_id` / `novig_client_secret` in Secret Manager. (The
  `auth.novig.us/oauth/token` variant with an `audience` also works —
  both were verified.) Tokens last 30 minutes.
* `GET /nbx/v2/emm/events` rejects `limit` > 100 — page it.
* `POST /nbx/v2/emm/events/getMarketsByEvents` **validates** ≤100 ids but
  **enforces** "Maximum 50 event IDs allowed", and requires a `currency`
  field (`CASH`) the docs never mention. Batching at 50 turns ~300
  per-event round trips into ~6.
* Novig attaches markets only to in-season leagues. On 2026-08-14 only
  ATP, MLB, MLS, NFL, PGA, UFC, WNBA and WTA had open markets; NBA, NHL,
  CFL, the European soccer leagues and the three esports had scheduled
  events with none.

## Wiring a new league

1. Confirm Novig's league string (`GET /emm/events`, the `league` field).
2. Add a `NOVIG = NovigConfig(...)` block to the league module, composing
   a crosswalk from `mappers/leagues/novig_markets.py`, and pass
   `NOVIG=NOVIG` to its `LeagueConfig`.

That is the whole job — `fetch/novig.py` derives its coverage from
`mappers.run.LEAGUES`, so a wired league cannot be forgotten by the
fetcher. The pipeline prints an "unknown market type" warning the first
time Novig ships a type that is in neither `market_types` nor
`ignored_types`, which is the signal to extend the crosswalk.

### Leagues still waiting on Optic

Novig also quotes **NCAAF, Italy Serie A, Bundesliga and Ligue 1**, which
are not in our `League` enum because they are not on our OpticOdds
subscription (`opticodds_us.prices_dedup_state` carries none of them).
Since the pipeline is anchored on the Optic schedule, they can only be
wired once that subscription lands — see `mm-sport-subs-change`. Novig's
**PGA** golf book is out of scope (no `Sport.GOLF`, and a
futures/tournament taxonomy we have no precedent for).

Note the raw stash (`infra/run_novig_raw.sh`) fetches with
`--all-leagues`, so `raw_ingestion_us.novig_raw` accumulates history for
these leagues *before* they are wired.
