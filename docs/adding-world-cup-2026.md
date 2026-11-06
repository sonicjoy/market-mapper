# Adding World Cup 2026

> Historical note. Tip/console steps here are retired; see CLAUDE.md.

This is the 2026-06/07 build diary. Its ticker-suffix parsing,
`table_types` / `ignored_ticker_types`, tip `ignore` / `map` pins and
`config/world_cup/team_aliases.toml` are gone. Today Kalshi market type
comes from the typed scope in `mappers/vocab/kalshi_scopes.py` (an
unlisted scope stays unmapped, so no ignore pins), sides from
`custom_strike` (`strike_side`) and lines from `strike_type` +
`floor_strike` (`_typed_line`), both in `mappers/exchanges/kalshi.py`.
Soccer vocab is `mappers/vocab/soccer_markets.py`. Ship by MR with a test
in `tests/mappers/` and the `regression:mapping-gate` row delta.

Plan for mapping Kalshi's FIFA World Cup 2026 markets.  Group stage
runs 11 Jun – early Jul 2026, 72 group games then a 32-team knockout
(104 matches total).

## State of play (probed 2026-06-05)

Kalshi shared a planned list of 27 game-level `KXWC*` series.  As of
today **52 `KXWC*` series are live** (two are false positives:
`KXWCCODWARZONE` is esports, `KXWCCREG` is West Coast Conference
basketball).  The full group stage is posted for the core game-level
types:

| Series       | Open markets | Per game        |
|--------------|-------------:|-----------------|
| KXWCGAME     | 216          | 3 (3-way ML)    |
| KXWCSPREAD   | 288          | 4 lines         |
| KXWCTOTAL    | 432          | 6 lines         |
| KXWC1H       | 216          | 3 (3-way ML)    |
| KXWC1HTOTAL  | 288          | 4 lines         |
| KXWC1HSPREAD | 144          | 2 lines         |
| KXWCBTTS     | 72           | 1               |
| KXWC1HBTTS   | 72           | 1               |
| KXWCTEAMTOTAL| 0            | series up, no markets yet |

Ticker discrepancy vs the planned list: planned `KXWCBTTS1H`
shipped as `KXWC1HBTTS`.  Map what's live, not what was planned.

## Settlement rules (verified from live markets)

Pulled `rules_primary`/`rules_secondary` from open markets:

- **Full-game markets settle on regular time only** — "after 90
  minutes plus stoppage time (does not include extra time or
  penalties)".  This holds for GAME, SPREAD, and TOTAL.  The 3-way
  GAME market has an explicit "Tie" leg, which can therefore win
  even in knockout games (a knockout game tied after 90' settles
  Tie; ET/pens outcomes belong to the not-yet-live MOV/MOF series).
- **1H markets settle after 45 minutes plus stoppage.**
- **Reschedule rule**: cancelled or rescheduled to over two weeks
  away → resolves "to a fair price in accordance with the rules"
  (not void).  Same flavour as other Kalshi sports; the existing
  reschedule handling applies.

Consequence: World Cup semantics match EPL's regular-time markets
exactly, so reusing `MONEYLINE_3WAY` / `POINT_SPREAD` / `GAME_TOTAL`
is sound, including for knockout games.  Verified directly: the
rules text on a settled KXEPLGAME market (26MAY24LFCBRE) is
word-for-word the same template — same 90'+stoppage clause, same
Tie clause, same two-week reschedule clause.

## Optic probe results (2026-06-07)

Probed Optic directly (ad hoc curl against `/v3`, same auth as
`fetch/optic.py`).  Every open question for the moneyline slice
resolved favourably:

- **League id is `fifa_-_world_cup`** (sport `soccer`).  All **72
  group-stage fixtures are active** on it now.
- **The 3-way Moneyline carries a Draw selection on every book
  sampled** — DraftKings, FanDuel, Kalshi, crypto.com all quote
  Home/Away/Draw on fixture `20260611FD9A34B0` (Mexico v South
  Africa).  Draw rows will have Optic rows to merge onto.
- **Kalshi is live in Optic with populated `source_ids`** — the
  `verify_source_ids` cross-check works for WC.  Confirmed tickers:
  `KXWCGAME-26JUN11MEXRSA-MEX / -RSA / -TIE`.  39 Kalshi odds on the
  fixture spanning GAME, SPREAD (Optic "Asian Handicap"), TOTAL
  ("Total Goals", 6-line ladder), 1H, 1HTOTAL, 1HSPREAD, BTTS,
  1HBTTS — matching the live-series table above.
- **Optic competitor abbreviations matched Kalshi's ticker codes**
  (`MEX`/`RSA`) on the probed fixture — same identity free-ride as
  EPL, so `team_aliases.toml` likely only needs the disagreements.
  Still do a systematic sweep of all 72 fixtures vs live KXWCGAME
  tickers (Türkiye, Côte d'Ivoire etc. may diverge).
- **Regular time is safe for moneyline by structure**: only a
  regular-time market can settle Draw, so a 3-way with an explicit
  Draw leg *is* the regular-time market; and Kalshi's Draw leg maps
  to the `-TIE` ticker whose rules we verified settle on
  90'+stoppage.  The ET-inclusive question only bites for
  knockout-round spread/total variants (no Draw leg, so no
  structural protection) — re-check per market type when widening,
  from the Round of 32 (~28 Jun).
- **crypto.com is live in Optic for WC** (3 moneyline odds on the
  probed fixture) but its `source_ids` are null — consistent with
  the NBA finding (`adding-crypto.md`).  Crypto rows stay novel;
  they merge by `row_key`.
- Fetch wiring: `SPORTSBOOK_BATCHES` already includes kalshi +
  prophet_x, so `fetch/optic.py` only needs the `SUPPORTED_LEAGUES`
  entry (`League.WORLD_CUP: "fifa_-_world_cup"`).

## Agreed build order (2026-06-07)

Moneyline-3-way first, Kalshi before crypto, no PX:

1. **`mappers/leagues/world_cup.py` + Kalshi KXWCGAME only**
   (clone from `epl.py`).  All other live `KXWC*` types got tip
   `ignore` pins so the unknown-ticker warning stayed clean.
   Build `config/world_cup/team_aliases.toml` from live KXWCGAME
   tickers vs Optic names.  `PX = None` (make `LeagueConfig.PX`
   optional, as `CRYPTO` already is).  **DONE — see "Built" below.**
2. **Crypto WC moneyline** — `CRYPTO` config (`Moneyline (3-Way)`,
   period `"90 Minutes and Stoppage Time"`), the `_resolve_side`
   THREE_WAY/`_TIE` Draw branch, `crypto_id` aliases.
   **DONE 2026-06-08** — the FIFA game-line feed revived (52 live
   group fixtures, 06-08), built on mm-810.  Verified end to end: 34
   crypto games merged onto Optic+Kalshi, 0 novel, Draw legs onto
   Optic "Draw" / Kalshi `-TIE`.  Aliases seeded from the live feed
   (42 of 48 countries at the time; the last 6 added 2026-06-10 —
   all 48 now mapped).  Full detail in the "Feed revival
   (2026-06-08)" section of `docs/adding-crypto.md`.
3. **Widen later**: Kalshi SPREAD/TOTAL — **DONE 2026-06-07, see
   "Built: Kalshi spread & total" below**; crypto `Total Goals`/
   `Spread` — **DONE 2026-06-10**, then the P2 list.

   Crypto progress: **Anytime Goal Scorer shipped 2026-06-10** (the
   first crypto player prop), and **crypto `Total Goals`/`Spread`
   shipped 2026-06-10** (they appeared live in the 06-09 burst,
   1,050 each).  Remaining: the rest of the player props — full
   detail and ordering in the "Player Props" section of
   `docs/adding-crypto.md`.

Out-of-order addition: **anytime goalscorer (KXWCGOAL) shipped
2026-06-07** ahead of the P2 list — expected to be the most popular
player market with punters, and the probe showed it was pure config
(see "Built: anytime goalscorer").

P2 splits into three tranches by mechanism (agreed 2026-06-07):
the **1H trio** (period-variant clones of the shipped game types —
**DONE 2026-06-07, see "Built: first-half trio"**), the **BTTS
pair** (new MarketType, first game-scoped `YES_NO` — **DONE
2026-06-07, see "Built: BTTS pair"**), and **TEAMTOTAL** (blocked
like GOAL was until Kalshi posted markets 2026-06-10 — **DONE
2026-06-10, see "Built: team total"**).

## Built: step 1 shipped (2026-06-07)

On branch `mm-810-add-world-cup-2026-mappings`.  What landed beyond
the plan above, from the alias sweep
(`scripts/sweep_world_cup_aliases.py` — joins live KXWCGAME tickers
to Optic fixtures via `source_ids`, so every pairing is ground
truth) and verification:

- **Aliases**: 43 of 45 Kalshi codes are identity; only `DZA`→ALG
  and `IRI`→IRN needed entries.  Türkiye and Côte d'Ivoire, the
  expected divergers, are identity (`TUR`, `CIV`).
- **Optic ships an empty `abbreviation` for the three WC debutants**
  (Haiti, Curacao, New Zealand — fresh rows in Optic's soccer DB).
  Solved with `OpticConfig.abbr_overrides`: an unconditional
  per-competitor-id override pinning their canonicals to the Kalshi
  codes (`HTI`/`CUW`/`NZL`), immune to any later Optic backfill.
- **Soccer Kalshi tickers are home-first** (`26JUN11MEXRSA` =
  Mexico home; 68/68 in the sweep), opposite to the away-first US
  convention `resolve_game` assumed.  EPL too (`26MAY17AVLLFC`) —
  every matched EPL game had been mapping via the pipeline's flip
  recovery, warning each time.  Added
  `KalshiConfig.ticker_home_first`, enabled for EPL and WC;
  `mappers/docs/match-logic.md` updated.
- **`fetch.optic --horizon-hours`** override, forwarded by the
  orchestrator, to fetch fixtures beyond the 48h production
  horizon (the group stage enters it 2026-06-09).
- **Live KXWC count moved 52 → 67 series** between the 06-05 and
  06-07 probes; effective tip-overlay `ignored_ticker_types`
  enumerated all 65 non-GAME roots (verified equal to the live list,
  both directions).
- **Verification**: full normal-cycle fetch on the test VM
  (optic 72 fixtures / kalshi 67→1 series, 216 markets / px skip),
  pipeline reconcile **216/216 agreed, 0 novel**, zero warnings;
  existing leagues byte-identical by `--json` checksum.

## Deployment status (2026-06-07, ~11:30Z)

**Live on the test VM.**  The MR to `test` was merged (`4c4297d` —
it carried the WC work, the crypto.com NBA commits, and 7 main
commits `test` was lagging, incl. the mm-516 EPL/PX spread set);
the VM is on `test` at that tip and the hourly cron is re-enabled.

What shipped beyond the build sections below:

- `world_cup` on the fetch line in `infra/run_pipeline.sh`.
- Per-league fixture horizon: `OpticConfig.horizon_hours` (default
  48, World Cup 96).  The fetch cutoff and the pipeline's
  beyond-horizon diagnostics both read the per-league value, so
  they cannot disagree; `fetch.optic --horizon-hours` remains as a
  manual override.  In passing, fetch/optic.py's SUPPORTED_LEAGUES
  now maps League → OpticConfig (was a duplicate league-id table;
  same pattern as fetch/kalshi.py).

**Deployment lag (as of 2026-06-07 ~13:00Z)**: the VM tip carries
step 1 + spread/total only.  The three later tranches — anytime
goalscorer, the 1H trio, and the BTTS pair (the three most recent
"Built" sections) — are commits on the local source branch, not
yet pushed or MR'd to `test`.  Their verification is local
(public-endpoint Kalshi fetches over reused Optic snapshots);
nothing of them runs on the VM until the next push + MR cycle.

Next checks:

- **~19:00Z 2026-06-07**: first WC fixtures (11 Jun evening games)
  enter the 96h window.  Until then expect `world_cup: 0 fixtures`
  and all 936 Kalshi tickers excused as beyond-horizon, zero
  warnings (936, not 1728+ — see the deployment lag note: the VM
  fetches GAME/SPREAD/TOTAL only).  After, expect fixtures to
  fetch, map and load to BQ — eyeball the pipeline log on the VM.
- After a clean soak (~a day of cycles): MR the same source branch
  to `main` and deploy to prod.  The push of the three later
  tranches re-opens the `test` soak for those types first.
- EPL's `ticker_home_first=True` is evidenced by ticker analysis
  (`26MAY17AVLLFC`) but no live EPL fixture has run through it —
  the first mapped game next season confirms it (flip warnings
  would reappear if wrong).

### Deployment update (2026-06-10, ~09:30Z)

Both VMs now run the feature branch tip `0da5c33` (all tranches:
step 1, spread/total, GOAL, 1H trio, BTTS pair, the ignored-roots
extension, team total).  Verified end to end on both environments:
8 in-horizon fixtures mapped, 118 Kalshi team_total rows in the
respective `markets_us.market_mapping` tables, counts identical
test vs prod.  **Prod is on the feature branch, not `main`** —
plan: soak overnight on the branch, and if the hourly cycles stay
clean, merge to `main` 2026-06-11 (before the evening openers) so
`main` catches up to what prod runs.

### Morning review (2026-06-11, before the merge to main)

1. **First-principles sanity check, 2 random rows per type.**  For
   each mapped market type — Kalshi: moneyline 3-way, spread,
   total, team total, BTTS, the 1H trio, 1HBTTS; crypto: 3-way ML,
   Total Goals, Spread, Anytime Goal Scorer — pull 2 random rows
   from prod BQ (test BQ for crypto until prod gets a crypto
   cycle) and re-derive each from scratch, independent of the
   mapper: fetch the underlying Kalshi market and check the rules
   text (teams, threshold = suffix−0.5, 90'+stoppage clause) /
   the crypto contract (outcome, PREDICT_VALUE, period gate)
   against the row's entity/line/side and the Optic selection it
   merged with.

   **DONE 2026-06-10 (a day early — the crypto rows had been
   copied to prod, so everything checked in prod BQ): 26/26 rows
   pass, no blockers for the merge.**  Full evidence in
   `scratch/wc_sanity_check_2026-06-10.md`.  Highlights: all 18
   Kalshi rows re-derived exactly (suffix−0.5 throughout, period
   clauses correct per type, home-first tickers, all five no-leg
   shapes invert correctly); 17/18 Optic source_ids joins exact,
   the 18th being the documented one-sided-book pattern (the
   under-3.5 no-leg of KXWC1HTOTAL-26JUN14AUSTUR-4 — Kalshi
   currently one-sided in Optic, merge target real via FanDuel).
   All 8 crypto contracts matched on participants, EVENT_DATE,
   contract type, outcome, value, and the 90'+ST period gate.
   Side-finding: the sampled CPV@URU moneyline row carries a
   Dec-2025 security_id alongside a Jun-06 "Uruguay to win" pair —
   but the June set is **`Moneyline (2-Way)`** (no Draw leg,
   effectively draw-no-bet), a different product correctly NOT
   mapped, not a re-issue.  So that case doesn't bear on the
   supersession question; the NED–JPN / CIV–ECU prop vintages
   below remain the open item.

2. **Crypto findings to review (Greg)**, from the 2026-06-10
   coverage report:
   - **The feed re-issues contracts** — RESOLVED 2026-06-11.  The
     duplication was wider than first seen (466 prop questions over
     4 games, not just NED–JPN/CIV–ECU), and the original claim
     that "the mapper attached the later issuance" was a sampling
     artifact: the merge was last-write-wins over an unordered BQ
     scan, and the earlier (superseded) vintage had actually won on
     36 of 88 duplicated AGS rows in the 06-10 test-BQ load.
     Supersession (keep the latest contract per question) was
     confirmed as the right rule and built as
     `crypto_com.dedupe_superseded` — full evidence and design in
     `adding-crypto.md` "Built: supersession dedupe".
   - **Test BQ crypto rows trickle in**: 1,665 rows vs ~3,000
     mappable from the wide snapshot (e.g. totals 577 of 1,050)
     because the hourly fetch only sees contracts (re-)issued in
     its 90-minute window.  Expect convergence as the feed
     re-trickles; if totals/spreads are still far short of ~1,050
     by morning, investigate the fetch window instead.  (Caveat
     found 2026-06-11: the FIX table received **zero messages
     dated 06-10** — while the feed is silent there is nothing to
     converge; treat a short count as feed silence first.)

### Merged to main (2026-06-11)

The overnight soak was clean and the feature branch was merged as
planned: **`main` is now `135cdc8`** ("Answer combo-RFQ check:
exclusion stands"), carrying every tranche through team total plus
the crypto supersession dedupe.  **Both the test and prod VMs run
`main` at that tip** — prod is no longer ahead of `main`.

**Corners followed the same day**: `262802e`
(`mm-816-add-kalshi-corners`, cut from the new `main` tip) is now
merged to `main` and deployed — both VMs run `main` with the
corners pair live.  `main` tip is `6bcec29` as of 2026-06-11,
which also carries the GOAL first-posting correction (9 players,
not 17), the NFD base-letter fold in player-name normalization,
and the crypto player-id alias map for WC props.

## Built: Kalshi spread & total (2026-06-07)

Config-only widening of `mappers/leagues/world_cup.py`, no parser
work — the SPREAD/TOTAL suffix shapes are the shared machinery EPL
already runs through, and `ticker_home_first` was set in step 1:

- Kalshi `table_types` += `SPREAD` → `POINT_SPREAD`, `TOTAL` →
  `GAME_TOTAL` (removed tip `ignore` pins; fetch is opt-in on
  `table_types`, so the fetcher now pulls all three).
- Optic `table_types` += `asian_handicap` / `total_goals` — same
  market ids as EPL, both confirmed on the WC probe fixture.
- `OUTPUT_ORDER` += the two new types.

Why safe now: Kalshi settlement for SPREAD/TOTAL was already
verified in the 2026-06-05 rules pull (regular time, EPL template
word-for-word), and the Optic ET-inclusive question is structurally
moot for the group stage — group games cannot go to extra time, so
quoting bases cannot diverge.  **They can diverge from the Round of
32 (~28 Jun) — see the knockout caveat under "Still open".**

One genuine config delta vs EPL surfaced in verification —
**`line_offset=-0.5`**: WC spread/total ticker suffixes are N−0.5
(`KXWCTOTAL-...-3` = "Over 2.5 goals"), the opposite of EPL
(`KXEPLTOTAL-...-3` = "Over 3.5 goals").  Same Kalshi soccer
product, different ticker convention per series — the offset is
per-series, not per-sport.  Caught by `verify_source_ids` on the
first pipeline run (Optic said `RSA3` ⇔ "South Africa −2.5", we
had merged `RSA2`), then confirmed against `yes_sub_title` on all
720 spread/total markets in the 2026-06-07 fetch, zero exceptions.

**Convention flip (Kalshi note, 2026-06-10).**  Kalshi announced it
is standardising soccer spreads/totals on the `−0.5` convention
(ticker N = "over N−0.5" / "win by N", aligning with player props) —
i.e. exactly what WC already shipped.  So the EPL/WC difference above
was a *migration in progress*, not a permanent per-series quirk: WC
was born under the new convention, EPL was still on the old `+0.5`.
EPL's offset is therefore **date-stopped** at the cutover so last
season's `+0.5` gold stays byte-identical while next season uses
`−0.5`: `KalshiConfig.line_offset_after=("2026-06-10", -0.5)` on EPL,
resolved per game via `offset_for(start_date)` in `parse_event_ticker`
(games before the cutover keep `line_offset`).  WC needs no date-stop
(flat `−0.5`).  The cutover date is unambiguous because EPL is
off-season across it; confirm Kalshi's exact flip date — and the new
convention against `yes_sub_title` — on the first live EPL
spread/total game next season.

Verification (local, 2026-06-07 — optic file reused from the
morning fetch, Kalshi refetched via the public endpoints with
`scratch/fetch_kalshi_public.py`): kalshi 3 series / 936 markets
(216+288+432, exactly the live-series table), pipeline 72 events,
936 tickers matched, **reconcile 1584 agreed / 17 novel**, zero
warnings, 55 orphans all classified ladder-extension (0
unexplained).  The 17 novel rows are all the *no* side at the
ladder extreme (10× "under 5.5" from `TOTAL-6`, 7× the underdog
side of the widest spread): Optic corroborates the yes side of the
same tickers but carries no Kalshi quote on the no side —
one-sided book at the extremes, benign.  Optic quarter-lines (AH
−0.75 etc.) have no Kalshi counterpart and stay Optic-only rows,
which is normal.

Why moneyline-only first: crypto's FIFA game lines are *only*
`Moneyline (3-Way)` so far, the slice exercises every new mechanism
(league module, country aliases, neutral-site flips, Draw leg,
optional PX) end to end, and KXWCGAME's explicit Tie leg plus
Optic's confirmed Draw selection give crypto Draw rows something to
merge onto from day one.

## Built: anytime goalscorer (2026-06-07)

KXWCGOAL → Optic `player_goals`, via a new
`PLAYER_GOALS = (player_goals, Scope.PLAYER, Shape.OVER_UNDER)`
MarketType — the first player prop on a soccer league, and pure
config beyond the enum line: zero parser work.

What the probes established (all 2026-06-07):

- **Kalshi has no separate "anytime goalscorer" market** — the
  KXWCGOAL "N+ goals" ladder *is* it (the `-1` leg = at least one
  goal).  KXWCGOAL itself had **0 posted markets** in any status,
  so the structure was taken from the 1,886 finalized KXEPLGOAL
  markets: suffix `{TEAM}{PLAYER_ENC}-{N}` with the player name in
  the title ("Radu Dragusin: 1+ goals"), lines 1 and 2, 16–36
  players per game.  That is exactly the existing
  `(PLAYER, OVER_UNDER)` shape NBA player props parse; the N−0.5
  conversion ("1+" = over 0.5) is hardcoded in that parse branch —
  `line_offset` is spread/total-only, so no offset question arises.
- **Optic `player_goals` is an over-only ladder** at 0.5/1.5/2.5
  per player (deeper for stars), stable `player_id`s, selection
  names identical across books.
- **Optic's `anytime_goal_scorer` market is ignored BY DESIGN**:
  on the probe fixture, all 5 books quoting it (Betano, DK, FD,
  Hard Rock, Unibet) also quoted `player_goals` over 0.5 for the
  identical player set — anytime-only players = 0.  Mapping it
  would add zero odds and double-count each book's price on one
  question.  If a book ever shows up anytime-only, the fold-in is
  to synthesize `line=0.5, side=over` onto the same canonical row.
- **Player identity came essentially free**: both sides normalize
  through `normalize_player_name` (diacritics stripped, so Optic
  "Luis Chávez" ↔ Kalshi "Luis Chavez" agree), and
  `config/world_cup/player_aliases.toml` + the levenshtein orphan
  diagnostic stand ready for genuine divergences.  No alias file
  created yet — `load_aliases` treats missing as empty.
- **Settlement is ET-inclusive** ("entire game (regulation,
  stoppage and any extra time periods)", from finalized KXEPLGOAL
  rules) — the *opposite* basis to GAME/SPREAD/TOTAL.  Moot for the
  group stage, joins the knockout caveat (see "Still open").  Also
  a settlement quirk worth knowing on the trading side: an active
  player who never enters the game settles *to the last fair
  market price before game start* — not void, not No.

Verification (local, on the 2026-06-07 10:30 snapshot, whose Optic
file already carried player_goals odds): 4,759 player_goals rows
across all 72 fixtures, 1,048 players, over-only ladder 0.5–4.5,
zero new warnings; existing market types byte-identical (old code's
full output md5 == new output minus player_goals rows).  Kalshi-side
merge is **unverified until Kalshi posts KXWCGOAL markets** — on
first live fetch, confirm titles match the EPL "X: N+ goals"
pattern and eyeball the player-name match rate / orphan diagnostic.
Expect every Kalshi *under* (no) side to be a novel row,
systematically: Optic's ladder is over-only, so there is nothing
for unders to merge onto — unlike NBA, where books quote both
sides.  This is the spread/total ladder-extreme pattern writ large,
and benign.

## Built: first-half trio (2026-06-07)

KXWC1H / KXWC1HSPREAD / KXWC1HTOTAL →
`FIRST_HALF_WINNER_3WAY` / `FIRST_HALF_POINT_SPREAD` /
`FIRST_HALF_TOTAL` — pure config, zero parser work, no new
MarketTypes.  P2 tranche 1.

What the probe established (scratch/probe_wc_1h.py over all open
markets via the public endpoints, plus the 2026-06-07 10:30 Optic
snapshot, which carries all markets unfiltered):

- **Optic market ids**: `1st_half_moneyline` /
  `1st_half_asian_handicap` / `1st_half_total_goals`, each
  confirmed by Kalshi `source_ids` joins in the snapshot — all 216
  KXWC1H markets joined, including all 72 Draw rows onto `-TIE`
  tickers.  `1st_half_asian_total_goals` quarter-lines have no
  Kalshi counterpart and stay Optic-only, same as full game.
- **KXWC1H is a 3-way with an explicit -TIE leg** (72 TIE + 144
  team markets), same structure as KXWCGAME.  The Kalshi parser
  dispatches by `Shape.THREE_WAY`, not by `MONEYLINE_3WAY`
  specifically, so the TIE handling came free.
- **The N−0.5 suffix convention holds for the 1H series**:
  1HTOTAL `-4` = "Over 3.5 1H goals" (288/288), 1HSPREAD `RSA2` =
  "wins the 1H by over 1.5" (144/144), zero exceptions — so the
  existing `line_offset=-0.5` covers them, no config delta.  (Probe
  gotcha: the sub_titles contain "1H", whose bare "1" must not be
  parsed as the line — anchor on "over".)
- **Settlement is 45'+stoppage** (already verified in the
  2026-06-05 rules pull).  The knockout ET caveat does NOT apply to
  the trio: extra time cannot touch the first half.
- Market counts exactly match the 06-05 live-series table
  (216/288/144).

Verification (local, 2026-06-07 ~12:05Z — Optic file reused from
the 10:30 fetch, Kalshi refetched via `scratch/fetch_kalshi_public.py`,
now 7 series / 1584 markets): pipeline 72 events, 1584 tickers
matched, **reconcile 2550 agreed / 60 novel**, 126 orphans all
classified ladder-extension (0 unexplained), no new warnings.  The
deltas vs the spread/total run are all the established benign
patterns: +43 novel are the *no* side at the 1HTOTAL ladder extreme
(under 3.5 — one-sided book), +71 orphans are the widest 1HSPREAD
rung (±1.5) where Optic's 1H handicap ladder doesn't reach.
Existing market types byte-identical (old code's full `--json`
output md5 == new output minus the three 1H types).

## Built: BTTS pair (2026-06-07)

KXWCBTTS / KXWC1HBTTS → Optic `both_teams_to_score` /
`1st_half_both_teams_to_score`, via two new MarketTypes
`BTTS` (`btts`) / `FIRST_HALF_BTTS` (`1h_btts`), both
`(Scope.GAME, Shape.YES_NO)` — the first game-scoped use of
`YES_NO` (previously only player DD/TD).  P2 tranche 2; the first
tranche since step 1 to need parser work, one small branch per
exchange.

What the probes established (2026-06-07; Optic offline against the
10:30 snapshot, Kalshi via `scratch/probe_wc_btts.py` over all open
markets):

- **Optic**: both market ids carry exactly 2 rows per fixture
  (literal "Yes"/"No" selections, `selection_line`/`points`/
  `player_id`/`team_id` all null) on all 72 fixtures, and **every
  one of the 144 rows per market joined Kalshi via `source_ids`** —
  zero gaps.  Combo/derivative BTTS markets
  (`both_teams_to_score_+_moneyline_3-way`, `*_both_halves`,
  `2nd_half_*`) are skipped by design.
- **Kalshi**: 72 markets/series (1/game), constant `-BTTS` suffix
  (zero deviations), titles uniform 72/72 ("Will both teams
  score?" / "... in the 1st Half?").  The suffix carries no
  information — yes/no live in the market's own sides.
- **Settlement**: full-game BTTS is regular time (same
  90'+stoppage template as GAME/SPREAD/TOTAL), so it JOINS the
  knockout re-check list; 1HBTTS is 1st-half goals only, so the
  caveat does not apply.  Own goals count towards the team awarded
  the goal (`rules_secondary`, both series).

Design (agreed 2026-06-07): rows key as `entity=None, line=None,
side=yes/no` — structurally collision-free, one BTTS question per
game.  Kalshi side: new `GameYesNoTicker` variant (no fields beyond
the base) with a guard raising on a team-code suffix, so a future
team-scoped yes/no series misconfigured as game-scoped fails loud
instead of silently collapsing two team markets onto one game row.
Optic side: the `YES_NO` builder branch splits on scope — PLAYER
keeps the over/under→yes/no conversion (NBA DD/TD encoding), GAME
asserts literal `normalized_selection` yes/no, deliberately loud if
a game-scoped yes/no ever arrives in over/under encoding.  Also
fixed in passing: kalshi.py's module docstring listed an
aspirational `(GAME, YES_NO)` suffix pattern ("no suffix — market
ticker = event ticker") that did not match reality.

Verification (local, 2026-06-07 ~12:44Z — Optic file reused from
the 10:30 fetch, Kalshi refetched via
`scratch/fetch_kalshi_public.py`, now 9 series / 1728 markets):
pipeline 72 events, 1728 tickers matched, **reconcile 2838 agreed /
60 novel** — +288 agreed, +0 novel vs the 1H-trio run, i.e. the
entire BTTS pair (2×72×2) merged agreed.  Zero novel is expected
and meaningful here: both sides of a yes/no quote the same
question, so the one-sided ladder-extreme pattern of the other
types cannot occur.  Orphans unchanged (126, all ladder-extension,
0 unexplained), no new warnings; existing market types
byte-identical (old code's full `--json` md5 == new output minus
the two BTTS types, 12,442 rows both).

## Series sweep (2026-06-10, ~36h before kickoff)

Full live-series probe via the public endpoints: **83 `KXWC*`
series live** (was 67 on 06-07).  Key findings:

- **Kalshi has still posted no per-game player-prop markets**:
  GOAL, SHOT, SOG, AST, SAVE, FIRSTGOAL, SOA all 0 open markets.
  The KXWCGOAL first-posting check stays pending; nothing prop-side
  is buildable or testable until Kalshi posts.
- **HATTRICK is tournament-scoped** ("at least 5 hattricks during
  the WC", 5 open) — not a per-game player prop after all.
  TEAM1STGOAL confirmed tournament-scoped too (1,162 open, "first
  goal for Iraq in the tournament").  Both stay ignored.
- **KXWCTEAMTOTAL posted — 535 open** — the last P2 item unblocked.
  `KXWCTEAMTOTAL-26JUN11MEXRSA-RSA3` = "South Africa over 2.5
  goals": `{TEAM}{N}` suffix, N−0.5 convention holds; the
  `(TEAM, TOTAL)` parse shape already exists and Optic carries a
  Team Total market (1,041 rows in the 06-10 snapshot).  Built
  the same day — see "Built: team total".
- **CORNERS (120 open) / TCORNERS (144) posted** — P3, new
  MarketTypes needed; Optic Total Corners / Team Total Corners
  both present in the snapshot.  **DONE 2026-06-11 — see "Built:
  corners pair".**
- **12 new tournament-scoped roots tip-ignored** (828c661; effective
  overlay `ignored_ticker_types`), classified from live series titles/markets: GAMEGOALS,
  GOALIEGOAL, GOALIEPEN, GOALSALLOWED, GROUPPTS, GS3WINS,
  GSUNDEFEATED, LONGESTPEN, OLIMPICO, TEAMH2H, TEAMTOTALGOALS
  (tournament team goals despite the per-game-sounding name), PRICE
  (ticket prices).  Ten of them had posted markets and were warning
  as unknown ticker types every run (361 markets skipped).
- **Four 0-market per-game candidate roots left to warn on
  purpose**: FTTS / TTSF (both titled "Team To Score First"), SCORE
  (correct score), TEAMFIRSTGOAL.  With 0 markets they warn nothing
  today; the warning on first posting is the signal to classify.
- Optic-side player-prop targets are already rich in the 06-10
  snapshot (Player Shots 6,330 rows, SOG 3,508, Assists 2,264,
  Saves 550, plus 1H variants), so SHOT/SOG/AST/SAVE remain
  expected config-only once Kalshi posts.

## Built: team total (2026-06-10)

KXWCTEAMTOTAL → Optic `team_total`, built the same day the sweep
found it unblocked — the last P2 game-level type.  Config-only,
reusing the TEAM_TOTAL machinery MLB/NBA already run (`{TEAM}{N}`
suffix parse, team-scoped TOTAL shape on both sides):

- Kalshi posted 535 markets over 71 games (only 26JUN14NEDJPN
  missing); every team has lines 1–3, favourites deeper (max 7) —
  hence the non-round count.
- The N−0.5 suffix convention holds: all 535 yes_sub_titles read
  "over N−0.5 goals", zero exceptions, so the existing
  `line_offset` covers it.
- Optic `team_total` (1,041 rows in the 06-10 snapshot): 457
  Kalshi source_ids joins, zero line or side mismatches.
- Settlement is regular time, confirmed from first principles on
  3 randomly sampled markets' rules: threshold = suffix−0.5 and
  the same "90 minutes plus stoppage time (does not include extra
  time or penalties)" clause as GAME/SPREAD/TOTAL — so TEAMTOTAL
  joins the knockout re-check list.

Verification (local, 2026-06-10 ~09:00Z — Optic file reused from
the 03:40 fetch, Kalshi refetched via
`scratch/fetch_kalshi_public.py`, now 10 series / 2,263 markets):
pipeline 54 events, 1,695 tickers matched (+399 — exactly the
in-horizon TEAMTOTAL tickers), reconcile **2,559 agreed / 407
novel** — +457 agreed, matching the source_ids join count exactly.
The +340 reconcile-novels are the established uncorroborated-side
pattern (Kalshi sides merging by row_key onto rows where Optic
carries no Kalshi quote); exactly 1 genuinely novel output row (a
2.5-under whose over side has books — side-asymmetric orphan,
benign).  Existing market types byte-identical (old code's full
`--json` md5 == new output minus the 1,042 team_total rows;
12,990 rows both).  pyright clean, 234 tests pass.

## Built: corners pair (2026-06-11)

KXWCCORNERS / KXWCTCORNERS → Optic `total_corners` /
`team_total_corners`.  Branch `mm-816-add-kalshi-corners`, since
merged to `main` and deployed to both VMs (see "Merged to main").
Context:
a colleague reports Kalshi has launched corners
as "game props" singles (team corners + total corners) — not
available in combos/RFQs yet, but expected.  The 2026-06-10 sweep
had already spotted both roots; the 2026-06-11 probe
(`scratch/probe_wc_corners.py`, public endpoints, all open markets)
confirmed everything needed.  **Built and verified the same day** —
the TEAMTOTAL pattern as planned: two MarketType enum lines plus
world_cup.py config, zero parser work.

Verification (local, 2026-06-11 ~06:20Z — Optic file reused from
the 2026-06-10 08:58 snapshot, Kalshi refetched via
`scratch/fetch_kalshi_public.py`): pipeline 54 events, 1,976
tickers matched, all 264 corners markets (120+144, unchanged from
the probe) merged — 240 + 288 Kalshi sides on 1,444 + 1,555 output
rows.  Reconcile **2,909 agreed / 579 novel**: **+350 agreed vs the
old code on identical inputs — exactly the probe's source_ids join
count**.  The corners side-accounting closes exactly: 350 agreed +
155 reconcile-novel (uncorroborated-side pattern) + 23 orphans =
528 = every corners Kalshi side.  All 23 new orphans classified
side-asymmetric (team-corners ladder rungs where Optic carries no
row at all), 0 unexplained.  Warning sets identical old vs new;
existing market types byte-identical (old full `--json` md5 == new
minus the 2,999 corners rows; 14,049 rows both).  Two rows
re-derived by hand: `KXWCCORNERS-...-7` yes ⇔ over 6.5 ("7+
corners?"), `KXWCTCORNERS-...-MEX6` yes ⇔ Mexico over 5.5
("Mexico: 6+ corners").  pyright clean, 238 tests pass.

The same fetch caught Kalshi's overnight postings — KXWCGOAL's
first markets (see "Still open", resolved) and 8 new/newly-posting
roots warning as unknown ticker types (see "Series watch" below).

Probe gotcha for re-runs: at probe time both roots had tip `ignore`
pins, so `series_tickers()` (opt-in on `table_types`) skipped them —
the probe discovers via raw `discover_series("KXWC")` instead (moot
now the roots are mapped, but the technique applies to any future
tip-ignored root).

What the Kalshi probe established (2026-06-11):

- **KXWCCORNERS** — 120 open markets over 24 games, suffix `-N`
  (bare number), title "9+ corners?", yes_sub_title "9+ corners".
  5-line ladder per game spanning 7–12 combined corners.
  Game-scoped total: rules say "Mexico and South Africa combined
  record at least 9+ corners".
- **KXWCTCORNERS** — 144 open over the same 24 games, suffix
  `{TEAM}{N}` (e.g. `RSA8`), title "South Africa: 8+ corners",
  yes_sub_title "South Africa: 8+".  3 lines per team × 2 teams per
  game; lines range 2–13 by team strength.
- **Only 24 games posted** (Jun 11–17 fixtures) vs TEAMTOTAL's 71 —
  Kalshi is posting corners on a rolling basis.  Counts were
  identical on 06-10 and 06-11.  Expect totals to grow; the fetch
  picks new markets up automatically once the roots are mapped.
- **The N−0.5 suffix convention holds** ("N+" = over N−0.5), so the
  existing `line_offset=-0.5` covers both series.  Verified two
  ways: the rules text reads "at least N+", and the source_ids join
  below.
- **Settlement is ET-INCLUSIVE**: "during the entire game
  (regulation, stoppage and any extra time periods)" — the same
  basis as GOAL, the *opposite* of GAME/SPREAD/TOTAL/TEAMTOTAL's
  90'+stoppage.  Moot for the group stage (no extra time possible);
  joins the knockout re-check list on the MIRRORED side — books
  conventionally settle corners markets on 90', so Optic's knockout
  corners lines may sit on the narrower basis.  See "Still open".
  Standard two-week reschedule clause, same as every other series.

What the Optic side shows (2026-06-10 08:58 snapshot):

- **`total_corners` (1,444 rows) and `team_total_corners` (1,532
  rows) are the merge targets.**  `total_corners`: empty selection,
  `selection_line` over/under, `points` at N.5, no entity.
  `team_total_corners`: selection = team name
  (`normalized_selection` e.g. "mexico"), `team_id` populated,
  over/under at `points` N.5 — same shape as `team_total`.
- **Kalshi source_ids joins: 350 total (180 total-corners, 170
  team-corners), zero line or side mismatches** — yes ⇔ over N−0.5,
  no ⇔ under N−0.5 throughout.  E.g. Optic "Mexico Over 5.5" ⇔
  `KXWCTCORNERS-26JUN11MEXRSA-MEX6` yes; "Under 7.5" ⇔
  `KXWCCORNERS-26JUN11MEXRSA-8` no.  (Snapshot-reading note: the
  local fetch merges per-book odds rows, so there is no per-odds
  sportsbook field — Kalshi presence lives in each row's
  `source_ids`, keyed "Kalshi".)
- **Skipped by design** (no Kalshi counterpart, same policy as the
  goals-market variants): 1H/2H corners variants, odd/even,
  `race_to_N_corners`, `most_corners_3-way`,
  `asian_handicap_corners`, `team_to_kick_first/last_corner`.

Build plan:

1. Two MarketType enum lines, values matching the Optic market ids
   (the `player_goals`/`btts` precedent):
   `TOTAL_CORNERS = ("total_corners", Scope.GAME, Shape.TOTAL)` and
   `TEAM_TOTAL_CORNERS = ("team_total_corners", Scope.TEAM,
   Shape.TOTAL)`.  Both (scope, shape) parse branches already run
   live — `(GAME, TOTAL)` parses the bare `-N` suffix (TOTAL),
   `(TEAM, TOTAL)` parses `{TEAM}{N}` (TEAMTOTAL) — which is why no
   parser work is expected.
2. Tip: Kalshi `map` pins for `CORNERS` / `TCORNERS` (or factory
   `table_types`); tombstone any stale `ignore` pins; Optic
   `table_types` +=
   `total_corners` / `team_total_corners`; `OUTPUT_ORDER` += both
   (proposal: after BTTS, keeping the full-game block together —
   Greg may prefer otherwise).  Also extend the KNOCKOUT CAVEAT
   paragraph in the world_cup.py module docstring: corners join
   GOAL on the mirrored (ET-inclusive on Kalshi) side.  No crypto
   side: the feed's FIFA prop types (shots, fouls, cards, …) are
   skipped wholesale and corners has no confirmed live crypto
   contract type — leave CRYPTO untouched.
3. Verify, the team-total recipe: pyright + tests; fresh
   public-endpoint Kalshi fetch (`scratch/fetch_kalshi_public.py`)
   over a reused all-markets Optic snapshot; expect 12 series and
   +264 Kalshi markets (120+144, more if Kalshi has posted further
   games by then), all tickers matched; reconcile deltas only in
   the two new types, with agreed counts in the vicinity of the
   350 source_ids joins (exact figures depend on the in-horizon
   fixture set and rolling posting); orphans classified
   (expect the ladder-extension and one-sided-extreme patterns of
   the other TOTAL types); no new warnings; existing market types
   byte-identical (old full `--json` md5 == new minus the two
   corners types).

## Built: to-advance (2026-06-28)

KXWCADVANCE → Optic `to_advance`, via a new MarketType
`TO_ADVANCE = ("to_advance", Scope.TEAM, Shape.YES_NO)` — the first
team-scoped use of `YES_NO`.  Hotfix on `mm-832-hotfix-wc-advance-markets`,
cut from `main` and MR'd straight to `main` (knowingly ahead of the
`test` soak — `test` had diverged with crypto player-prop work, but the
divergence analysis showed the parser/build dispatch sites this touches
were untouched there, so the same branch back-merges cleanly).

**The March Madness round-resolution machinery was NOT needed.**
Because the Round of 32 bracket was fixed by 2026-06-28, Kalshi posted
ADVANCE PER-GAME with the matchup baked into the event ticker
(`KXWCADVANCE-26JUN28RSACAN-RSA` = "South Africa advances"), so it
parses with the standard game regex — no `round_dates` / `extra_series`
pass.  The structure is a team-scoped yes/no: bare team-code suffix,
one binary market per team, two markets per tie.

**The regular-time caveat resolved by the merge target, not by code.**
Advance is the team's PROGRESS probability (a 90' tie advances via
ET/penalties), so it maps to Optic `to_advance` (one affirmative odd
per team, `selection`=team, `team_id` set, no line), NOT the 3-way ML
(where a 90' tie settles the Tie leg).  Both sides are then on the same
ET-inclusive basis by construction — the caveat the design section
flagged needs no per-knockout-round re-check for this type.

Parser work (small, one branch per exchange, the BTTS pattern):
- Kalshi: new `TeamYesNoTicker` variant; parse branch `(TEAM, YES_NO)`
  resolves the suffix via `_require_team` (a non-team suffix fails
  loud); `build_rows` emits entity=team yes/no.
- Optic: a `Scope.TEAM` arm under the `YES_NO` branch (entity=team,
  side="yes").  Optic quotes only the affirmative, so each Kalshi
  *no* side is a novel row — the over-only-ladder pattern, by team.

Verification (local, 2026-06-28 — the live `data/2026-06-28/05_12`
snapshot already carried both KXWCADVANCE and Optic `to_advance`, so
no refetch): pyright clean, 251 tests pass (+2 new parse tests).  The
`unknown ticker type 'ADVANCE'` warning is gone.  `--json` before/after
on the snapshot: **+40 rows, all `to_advance`, existing types
byte-identical** (before == after minus to_advance).  The 40 = 10
in-horizon ties × 2 teams × yes/no; **20 yes rows merged Kalshi+Optic
(agreed), 20 no rows Kalshi-novel** — exactly the predicted split.
Kalshi posted 14 ties (28 markets); 4 are beyond the 96h Optic horizon.

## Built: first goalscorer (2026-07-19)

KXWCFIRSTGOAL → Optic `first_goal_scorer`, via the existing
`FIRST_GOAL_SCORER = ("first_goal_scorer", Scope.PLAYER, Shape.YES_NO)`
MarketType (added for the crypto work — crypto's "First Goalscorer"
was already mapped and flowing).  The P3 ledger's "first semantics
don't fit existing shapes — design needed" turned out stale: both
feeds fit the player YES_NO shape with no new parser variants.

Structure (probed live on the final, KXWCFIRSTGOAL-26JUL19ESPARG,
the only fixture ever posted at build time — 8 markets):

- **Kalshi**: `{TEAM}{PLAYER_ENC}` suffix, no line; titles
  "Julian Alvarez: First Goalscorer" — the standard `(PLAYER,
  YES_NO)` parse (the NBA DD/TD branch), player name from the title.
  One extra leg per event, `-NOGOAL` ("No Goal: First Goalscorer"),
  which parses through the same branch to entity `no_goal`.
- **Optic**: one affirmative odd per player (`selection`=name,
  `selection_line`=None, `points`=None, `player_id` set) plus a
  "No goal" selection with `player_id`=null that normalizes to
  `no_goal` — merging with Kalshi's NOGOAL leg for free.  This
  encoding is NEW to the player YES_NO branch (DD/TD arrives as
  over/under 0.5), so optic.build_rows grew a selection_line-is-None
  sub-case: side always "yes"; Kalshi's no sides stay novel, the
  over-only-ladder pattern.
- **No source_ids joins**: Optic carries no `kalshi` odds for this
  market (78 entries on the final: DK 47, FanDuel 31), so the merge
  rides on player-name row keys — the crypto-goalscorer precedent.
  Kalshi short names vs Optic registry names are the existing
  `kalshi =` alias mechanism in player_aliases.toml ("Lamine Yamal"
  → lamine_yamal_nasraoui_ebana merged via the alias added for
  KXWCGOAL on the semi).

Settlement (rules pulled live 2026-07-19): ET-INCLUSIVE ("entire
game (regulation, stoppage and any extra time periods)") — joins
GOAL/corners on the MIRRORED side of the knockout caveat, books
conventionally settling first goalscorer on 90'.  Own goals are
excluded (resolves on the next non-own-goal), matching book
convention.  A player who is active but never enters settles at the
last pre-game price, NOT void — books typically void; trading-risk
note, not a mapping one.

Verification (local, 2026-07-19, live fetch
`data/world_cup/2026-07-19/12_30`): pyright clean, 486 tests pass
(+2 Kalshi parse tests, +3 new optic build_rows unit tests in
test_optic_rows.py — the branch's first unit-level coverage).
Pipeline over the live final: 56 first_goal_scorer rows — all 8
Kalshi markets (7 players + NOGOAL) merged onto Optic yes rows,
8 Kalshi no sides novel as predicted, 40 Optic-only players Kalshi
doesn't post.  The `unknown ticker type 'FIRSTGOAL'` warning is gone.

Shipped hours before the final — the last WC fixture — so the real
payoff is the pattern: EPL's KXEPLFIRSTGOAL still sits in epl.py's
ignored list (alongside GOAL itself) and is now a pure-config lift
for next season.

## Priorities

### P1 — What EPL already supports (all live now)

| Kalshi ticker type | MarketType        |
|--------------------|-------------------|
| GAME               | `MONEYLINE_3WAY`  |
| SPREAD             | `POINT_SPREAD`    |
| TOTAL              | `GAME_TOTAL`      |

Pure league-config work: new `mappers/leagues/world_cup.py` cloned
from `epl.py`.  Notes:

- Kalshi ticker format matches EPL's:
  `KXWCGAME-26JUN27CODUZB-UZB` parses with the same
  `(\d{2})([A-Z]{3})(\d{2})([A-Z]{3})([A-Z]{3})` game regex —
  3-char country codes in place of club codes.
- Needs `config/world_cup/team_aliases.toml` (country codes ↔
  Optic country names).  Optic league id: `fifa_-_world_cup`
  (probed — see "Optic probe results" above; Optic abbrevs matched
  Kalshi codes on the probed fixture).
- Optic soccer markets may quote ET-inclusive lines for
  knockouts — moneyline is safe by structure (see probe results);
  confirm spread/total against their *regular time* variants when
  widening.
- **No PX for the World Cup.**  `LeagueConfig.PX` is now optional
  (`PxConfig | None`); the pipeline skips its whole PX section when
  None, and `fetch.px` prints "no PX coverage, skipping".

### P2 — Remaining live game-level markets

| Kalshi ticker type | MarketType                | Status |
|--------------------|---------------------------|--------|
| 1H                 | `FIRST_HALF_WINNER_3WAY`  | **DONE 2026-06-07** |
| 1HTOTAL            | `FIRST_HALF_TOTAL`        | **DONE 2026-06-07** |
| 1HSPREAD           | `FIRST_HALF_POINT_SPREAD` | **DONE 2026-06-07** |
| TEAMTOTAL          | `TEAM_TOTAL`              | **DONE 2026-06-10** |
| BTTS               | `BTTS`                    | **DONE 2026-06-07** |
| 1HBTTS             | `FIRST_HALF_BTTS`         | **DONE 2026-06-07** |

TEAMTOTAL is config-only once Kalshi posts markets (suffix shape
unverifiable until then) and the Optic team-total-goals id is
confirmed.  **Both arrived 2026-06-10 and it shipped the same
day — see "Built: team total".**

#### Tranche 2 work plan (BTTS + 1HBTTS)

**DONE 2026-06-07 — see "Built: BTTS pair".**  Executed as planned,
in order:

1. **Optic probe** (offline, against an existing all-markets
   snapshot such as `data/2026-06-07/10_30/`): confirm the
   full-game BTTS market id (`1st_half_both_teams_to_score` was
   already seen in the 2026-06-07 snapshot at 144 rows = 72×2, so
   expect `both_teams_to_score`) and the Kalshi `source_ids` joins
   onto both, same join technique as the 1H trio probe.  Note the
   selection shape Optic emits ("Yes"/"No" rows?).
2. **Kalshi probe**: clone `scratch/probe_wc_1h.py` for
   KXWCBTTS/KXWC1HBTTS (public endpoints).  72 markets/series =
   1/game, so the open question is the ticker shape — bare event
   ticker, `-YES`, or other suffix — and whether the current
   `game_ticker_re` matches it.  Capture title/`yes_sub_title`
   patterns for the doc.
3. **Design (Greg decides, not config-only)**: how a game-scoped
   `YES_NO` canonical row keys — presumably `entity=None`,
   `side=yes/no`, `line=None` — what the two new MarketTypes are
   named (e.g. `BTTS` / `FIRST_HALF_BTTS`, market ids `btts` /
   `1h_btts`), what the Optic builder emits for a Yes/No selection
   at game scope, and what parse branch the Kalshi ticker needs
   (the existing `YES_NO` handling is player-scoped and extracts a
   player from the suffix — game scope skips that).  Expect a small
   amount of parser work on both sides, unlike tranche 1.
4. **Build**: the two MarketType enum lines, the parse branches
   from step 3, then tip `map` pins for BTTS/1HBTTS (tombstone
   stale `ignore` pins if any), Optic `table_types`, extend
   `OUTPUT_ORDER`.
5. **Verify**, same recipe as the 1H trio: pyright + tests; fresh
   public-endpoint Kalshi fetch over a reused all-markets Optic
   snapshot; expect 9 series / 1728 markets, all tickers matched,
   reconcile deltas only in the two new types, orphans classified,
   no new warnings; existing types byte-identical (old full
   `--json` md5 == new minus the two new types).  Since both sides
   of a yes/no quote the same question, expect few or no
   systematic novel rows — investigate any that appear rather than
   assuming the ladder-extreme pattern, which can't apply here
   (no ladder).

### P3 — Planned game-level markets not yet live

Map these as Kalshi posts them, roughly in this order of fit:

1. **Corners** (`CORNERS`, `TCORNERS`) — **DONE 2026-06-11, see
   "Built: corners pair" above.**
2. **Team shots / SOG / saves** (`TEAMSHOTS`, `TEAMSOG`,
   `TEAMSAVE`) — existing `TOTAL` shape, team-scoped; new
   MarketTypes only.
3. **Player props** (`SHOTS`, `SOG`, `ASSIST`) — player-scoped
   `OVER_UNDER`/`YES_NO`, same machinery as NBA player props.
4. **Goalscorer set** (`FIRSTGOAL`, `TEAMFIRSTGOAL`, `SOA`) —
   "first" semantics don't fit existing shapes; EPL explicitly
   ignores these today.  Design needed.  (`GOAL`, the anytime
   ladder, turned out to be the tame one of this set and shipped
   2026-06-07 — see "Built: anytime goalscorer".  `FIRSTGOAL`
   followed 2026-07-19 and needed no new shape after all — see
   "Built: first goalscorer".  `TEAMFIRSTGOAL`/`SOA` remain
   unmapped.)
5. **Structurally new** (`1HFT`, `SCORE`, `1HSCORE`, `MOV`,
   `MOF`) — many-outcome markets, no fitting shape.  MOV/MOF are
   knockout-only (Reg/ET/Pens); decide closer to the knockout
   rounds (Round of 32 starts ~28 Jun 2026).

Until mapped, every one of these gets a tip `mapping_market_rules`
`ignore` pin so the unknown-ticker-type warning stays clean and
intentional.

### P4 — Tournament-scoped (may not do at all)

~25 live series: group winners/qualifiers, stage of elimination,
golden boot, player tournament goals, Messi/Ronaldo combos, etc.
Also `KXWCTEAM1STGOAL` and `KXWCPLAYERGOALS`, which despite their
names are tournament-scoped (event tickers like
`KXWCTEAM1STGOAL-26IRQ` — per team per tournament, not per game).

Lowest priority.  If we do any, the entry point is the
advancement markets — see next section.

## Advancement markets — KXWCADVANCE (DONE 2026-06-28)

**Shipped 2026-06-28 on `mm-832-hotfix-wc-advance-markets` (hotfix to
`main`).  The March Madness machinery below was NOT needed** — see
"Built: to-advance" for what actually landed and why.  The plan in
this section is kept as the design rationale (the regular-time caveat
analysis held; the round-resolution scaffolding did not apply).

NCAAB already maps round-advancement markets (`KXMARMADROUND`,
"Will Duke advance past the Round of 32?") to individual games via
`has_tournaments` / `extra_series` / `round_dates` in
`KalshiConfig` (`mappers/leagues/ncaab.py`) and the MARMAD matching
pass in `mappers/pipeline.py`.  An advance-past-round-N market is
a moneyline on the team's round-N game, so it maps once the
bracket fixes the matchup.

The planned `KXWCADVANCE` (not yet live) is the same product:
"advance to the Round of 16" = moneyline on the Round-of-32 game.
The World Cup version is *easier* than March Madness in one way —
knockout rounds play across known fixed dates — and needs one
check: the regular-time caveat (a team can advance via ET/pens
after a 90' tie, so advance ≠ regular-time moneyline; it equals
the *progress* probability, which Optic quotes as "to qualify").
Match it to Optic's qualify market, not the 3-way ML.

Be ready to wire `round_dates` for KXWCADVANCE (or KXWCROUND /
KXWCGROUPQUAL if those turn out to be the per-game-mappable ones)
when the group stage resolves and knockout matchups are known
(~27 Jun 2026).  Setting `round_dates=()` disables the pass, so
the scaffolding can be in the config from day one at zero cost.

## Open questions

Resolved 2026-06-07 (see "Optic probe results"): the Optic league id
(`fifa_-_world_cup`), the Draw selection question (confirmed on all
books), and the regular-time question for moneyline (safe by
structure; spread/total still to confirm per type when widening).

Resolved 2026-06-07, later (see "Built"): country-code alias
coverage — all 72 fixtures swept against live KXWCGAME tickers via
`source_ids`; 2 aliases (`DZA`, `IRI`), 3 empty-abbreviation
debutants handled via `abbr_overrides`, ticker order confirmed
home-first.

Still open:

- **Knockout regular-time re-check (calendar item, ~28 Jun 2026)**:
  with SPREAD/TOTAL/BTTS in `table_types`, knockout fixtures will
  auto-map the moment they enter the horizon — nothing in the code
  forces the per-type re-check.  Unlike moneyline, these types
  have no Draw leg for structural protection: if Optic's knockout
  `asian_handicap`/`total_goals`/`both_teams_to_score` lines are
  ET-inclusive while Kalshi settles on 90'+stoppage, we'd silently
  merge mismatched bases.  (BTTS is conventionally a 90' market
  across books, so it is the least likely to diverge — but it is
  on the list.)  GOAL has the same risk MIRRORED: Kalshi settles it on
  the entire game *including* extra time, while books
  conventionally settle goalscorer markets on 90' — so Optic
  `player_goals` may sit on the narrower basis for knockouts.
  **The corners pair joins the MIRRORED list (probed 2026-06-11)**:
  KXWCCORNERS/KXWCTCORNERS rules read "entire game (regulation,
  stoppage and any extra time periods)" — same ET-inclusive basis
  as GOAL — while books conventionally settle corners on 90', so
  Optic `total_corners`/`team_total_corners` may also sit on the
  narrower basis for knockouts.
  Before the Round of 32, probe a knockout fixture's Optic rows
  (and Kalshi's own odds within them, via `source_ids`) to confirm
  the quoting basis per market type.
- ~~KXWCGOAL first-posting check~~ — **RESOLVED 2026-06-11**:
  Kalshi posted its first 17 GOAL markets overnight — **9 distinct
  players** with 1–3 ladder lines each, opening game MEX–RSA only
  (rolling, like corners; thin slate vs EPL's 16–36 players/game
  and the 46 Optic player_goals players on the same fixture).  All
  three predictions held: titles match the EPL "X: N+ goals"
  pattern exactly (`{TEAM}{PLAYER_ENC}-{N}` suffix, 17/17),
  player-name match vs Optic is 9/9 players (17/17 over sides
  merged) with zero aliases needed — 5 identity, 4 via diacritic
  stripping (Álvaro Fidalgo, César Huerta, Edson Álvarez, Raúl
  Jiménez; config/world_cup/player_aliases.toml still doesn't
  exist) — and all 17 under sides are Kalshi-only novel rows
  (Optic's ladder is over-only), systematically as expected.  The
  structure question is closed, but the sample hasn't exercised
  transliteration divergence: both squads are Latin-script.  When
  romanized-name squads (Iraq, Algeria, Iran, Korea…) post GOAL
  markets, run the orphan diagnostic over that batch — that's
  where a divergence no diacritic-stripping fixes would show.
- "No PX for the World Cup" is assumed, not verified: the local
  probe of PX tournaments failed on denied credentials (the PX
  secrets are IAM-blocked locally).  If it matters, run
  `python -m fetch.explore.px_tournaments` on the test VM (whose
  service account can read the secrets) and grep for a World Cup
  tournament.  PX=None stands either way until someone decides
  otherwise.
- ~~KXWCTEAMTOTAL: re-probe for open markets before the
  tournament~~ — resolved 2026-06-10, 535 open markets, mapped
  the same day (see "Built: team total").
- MOV/MOF/1HFT: still not live as of the 2026-06-10 sweep (83
  KXWC* series; SCORE now has a live series, 0 markets, and warns
  on first posting); re-probe closer to the knockout rounds.
  Any new root surfaces as an unknown ticker type at parse time
  until classified (tip `ignore` or `map`); fetch stays opt-in on
  `table_types` / `extra_series`.
- **Series watch (2026-06-11 fetch): 8 roots now warning as
  unknown ticker types, pending classification.**  Two are the
  deliberate warn-on-first-posting candidates, now posting:
  **FTTS (213 markets — "Team To Score First", per-game)** and
  **SCORE (70 — correct score, per-game; P3 "structurally new")**.
  Six are roots new since the 06-10 sweep: ATTENDSWIFT (1),
  FASTESTGOAL (6), OCCAN/OCMEX/OCUSA (10/11/20 — event tickers
  like `KXWCOCCAN-26JUN13`, no game suffix, likely opening-
  ceremony/host-city novelties), SONG (1).  Classify each (probe
  titles), then map or add a tip `ignore` pin.  FTTS at 213
  markets is the only one with real volume; its "first" semantics
  are the P3 goalscorer-set design problem.
