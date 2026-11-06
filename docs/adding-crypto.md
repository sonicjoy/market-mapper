# Adding crypto.com Support

> Historical note. Tip/console steps here are retired; see CLAUDE.md.

This file is the 2026-06/07 build diary. Its `mappers/leagues/` and
`config/<league>/team_aliases.toml` paths are gone. Today crypto.com
mapping is code: per-sport `CryptoConfig` builders in
`mappers/vocab/*_markets.py` (e.g. `basketball_crypto_config`), venue
matching in `mappers/exchanges/crypto_com.py` / `crypto_*.py`, team ids in
`CRYPTO_TEAM_IDS` (`mappers/vocab/crypto_team_ids.py`). Ship by MR with a
test in `tests/mappers/` and the `regression:mapping-gate` row delta. The
live checklist is "In-season validation checklist" at the end.

Integrating crypto.com (a.k.a. crypto.com "Predict") as a new mappable
exchange alongside Kalshi and ProphetX. crypto.com publishes its
prediction-market catalogue over **FIX**, ingested to BigQuery
(`marketmaking-test.raw_ingestion_us.crypto_com_fix_messages2` for raw
messages; `processed_upstream_us.crypto_underlying_securities` and
`crypto_security_def` for the processed catalogue). Each contract =
one selection.

Scope (2026-07): **all repo leagues** with crypto.com coverage enabled:

| League | crypto `meta_league` | period gate (game lines) | Notes |
|--------|---------------------|--------------------------|-------|
| NBA | `NBA` | `Full Game` | Game lines + props (`Full-Game` gate) |
| MLB | `MLB` | `Full-Game` | Game lines validated in BQ; props deferred (no MarketTypes) |
| NFL | `NFL` | `Full Game` | Best-guess — re-validate at season start |
| NHL | `NHL` | `Full Game` | Best-guess (`Puck Line`, `Total Goals`) |
| NCAAB | `CBB` | `Full-Game` | Game lines + 1st/2nd Half spread, total, 3-way ML (verified 2026-10-31) |
| World Cup | `FIFA` | `90 Minutes and Stoppage Time` | Game lines + props + BTTS |
| EPL | `EPL` | soccer gate | Best-guess `meta_league`; not yet in catalogue |
| UCL | `UCL` | soccer gate | 3-way ML validated; full soccer vocab pre-mapped |
| ATP / WTA | `ATP` / `WTA` | `Full Game` | `sport_grouping=TENNIS`; moneyline only |
| ATP Challenger | `ATP` (shared with main tour) | `Full Game` | Crypto.com files Challenger under `meta_league=ATP`; matching scoped to `atp_challenger` Optic fixtures |
| ITF Men / Women | `ITF` (best-guess) | `Full Game` | Not yet in TENNIS catalogue (ATP/WTA only as of 2026-07-29); symbols still `NX.F.OPT.TENNIS` |

WNBA, MLS, esports, and other crypto leagues outside the mmmapper
registry remain out of scope.

## Build status (2026-06-04, branch `mm-794-add-nba-mapping`)

NBA mapper is built, unit-tested, **wired into the pipeline**, covered
by an integration fixture, and **fed by an hourly BigQuery fetcher**.
Soccer is untouched (separate branch later). Commits on the branch,
oldest first:

| # | commit  | what                                                       |
|---|---------|------------------------------------------------------------|
| A | 2f45859 | `crypto_*` stamp fields on `CanonicalRow`                  |
| B | 0470ba5 | `CryptoConfig` dataclass + NBA `CRYPTO` instance           |
| C1| a755c3d | `Selection` Pydantic model + `parse_selection`             |
| C2| 8778a0e | `build_rows` for NBA game lines (+ unit tests)             |
| D | 4cf403c | NBA team aliases (19 feed-confirmed full names)            |
| E | 8a8b71a | wire crypto.com into the pipeline                          |
| F | ea8d7bb | identity-based side resolution (flip cross-wire fix)       |
| G | 7c3e5f9 | NBA integration fixture (NYK/SAS)                          |
| H | 8758f9e | resolve crypto teams by external id, not full name         |

Working method (continue it): **small commits, pipeline working end to
end at every step.** Per commit — run `mise test`, run `pyright` on
touched files, and for anything that could change output run the
stash-and-rerun `--json` checksum (`mappers/CLAUDE.md`) over a *small*
subset of `data/` dirs (the full set is ~1.8M lines and slow). Skip the
checksum for additive/inert changes. Greg reviews each change before
the commit: work it to your own satisfaction, propose a commit message,
then invite review. Commit messages: length proportional to the change;
background rationale belongs here in the doc, not the commit body.

What A–D give you: a `CanonicalRow` that can hold crypto IDs, a
feed-validated NBA `CryptoConfig` (`mappers/leagues/nba.py`), a mapper
(`mappers/exchanges/crypto_com.py`) that turns `Selection`s into
`CanonicalRow`s, and full-name→abbrev aliases. Verified: the 23 NBA
records in `scratch/crypto_com_markets.sample.jsonl` map to 23 correct
rows. Nothing in `pipeline.py` reads any of it yet, so all existing
output is byte-identical.

## Where we are (2026-06-03)

### What the FIX data looks like

We gathered a sample dump (`data/crypto-com-dump.jsonl`, ~268k parsed
FIX messages) and profiled it with `scripts/scan_crypto_com.py`.

- Each line is one `SecurityList` contract = one selection. Repeated
  catalogue snapshots, so dedup by `SecurityID`.
- The real-world mapping context lives in a block of `eventMeta*`
  fields. Cheat-sheet:
  - fixture     ← `eventMetaEXTERNAL_GAME_ID` (+ NAME / HOME / AWAY / EVENT_DATE)
  - market type ← `eventMetaPREDICT_CONTRACT_TYPE`
  - market group← `eventMetaPREDICT_MARKET_TYPE` (Game Line / Team Future / Player Future / blank)
  - selection   ← `eventMetaPREDICT_OUTCOME_TYPE` (Home/Away/Draw/Over/Under) + `eventMetaPREDICT_VALUE` (line)
  - sport/league← `eventMetaSPORTS_GROUPING` / `eventMetaLEAGUE`
- **Game-Line** markets are the mappable ones: `Moneyline`,
  `Moneyline (3-Way)` (soccer, has a Draw), `Spread`, `Total Points`
  (also `Total Goals`, `Puck Line` seen in the live feed).
- Futures/specials (`Team Future`, `Player Future`, blank) and `COMBOS`
  parlay instruments have no `external_game_id` — **out of scope**.

### Source IDs: Optic-primary hybrid (FIX gaps)

As of 2026-07, OpticOdds populates `source_ids` on crypto.com odds with
a descriptive `market_id` that **encodes** the FIX Symbol, e.g.:

```text
Optic: MLB-00001-260727-M-TOT11P5Over-O139_261130-2300_1_PM.NPO
FIX:   NX.F.OPT.MLB-00001-260727-M.O.1.39.20261130
```

The pipeline:

1. Requests `crypto_com` in the Optic odds fetch and preserves
   `source_ids["crypto.com"]` during dedup (display name `crypto.com`).
2. Decodes each Optic `market_id` against the latest FIX catalogue
   (`mappers/exchanges/crypto_optic.py`): generate every `O`-slot split,
   accept only a **unique** catalogue Symbol, and take that row's
   `SecurityID`.
3. Stamps `{security_id, symbol, market_id}` onto the Optic-resolved
   canonical row (fixture/market/selection already from Optic).
4. Keeps the FIX semantic mapper (`crypto_com.build_rows`) for Optic
   gaps and crypto-only markets (e.g. MLB F5). On Optic-vs-FIX symbol
   disagreement for the same `row_key`, **latest source timestamp wins**.
5. Emits `sportsbook="crypto.com"` from the `crypto_com` block only —
   never via `OPTIC_MAPPED_SPORTSBOOKS` (would collide on the MERGE key).

RFQ still joins on `source_ids.symbol`. Optic `market_id` is additive
provenance when present. Malformed / ambiguous Optic IDs are skipped
(FIX may fill); they do not abort the run.

Earlier history (Jun 2026): Optic served crypto.com odds with **null**
`source_ids`, so rows were built ground-up from FIX only. That path
remains the gap/fallback builder.

#### Why `SecurityID`, not `eventCode`

The V2.0 spec (Rules of Engagement appendix) nominates `eventCode` as
the canonical per-contract id and omits a `LEAGUE` field entirely — yet
the live feed carries `LEAGUE` (confirmed) and we stamp `SecurityID`, so
the spec is behind the feed on both counts (the feed, not the PDF, is
ground truth — same as the config-vs-dictionary stance above). We keep
`SecurityID` anyway. Over the 539 contracts in the backfill dump,
`SecurityID` is a clean 1:1 bijection with the (attr-99) `eventCode`,
which is itself byte-identical to `PREDICT_OUTCOME_ID` — so `SecurityID`
identifies a contract exactly as well, and we already retain
`eventCode`'s value as `crypto_outcome_id`. The decider is the join
requirement: `eventCode` lives only in `SecurityList` metadata and
appears in **0** of 185k+ live `SecurityStatus`/`MarketData` messages,
which key on `SecurityID` (and `Symbol`). As a mapping layer feeding the
trading system, we need the id that ties a mapped contract back to its
price/status stream — that's `SecurityID`, not `eventCode`. (Caveat: the
combo-level `eventCode` in a raw message is a parlay grouping, not a
contract id — the per-contract one is inside instrument attribute 99.)

### Architecture decision

crypto.com is just another specialised exchange. The pipeline is
specialised per exchange (own input file + own mapper); the only shared
contract is the OUTPUT (`CanonicalRow` + `MatchKey`). So we add:

1. an input file — `crypto_com_markets.jsonl`
2. a mapper — `mappers/exchanges/crypto_com.py`
3. a `crypto_*` stamp-block on `CanonicalRow`

### Artifacts produced so far (in `scratch/`)

- `crypto_com_cutdown.sql` — cut-down BQ extract (IDs + labels + mapping
  spine; drops FIX plumbing & combos). Verified against test
  (`crypto_com_cutdown_results.json`, `crypto_com_cutdown_check.md`).
- `crypto_com_input_schema.md` — the proposed mapper input format and
  translation rules.
- `crypto_com_markets.sample.jsonl` — 26 real selections (NBA OKC@NYK +
  World Cup Cabo Verde v Saudi 3-way) in the input format, for mapper
  dev before the BQ query is finalised.
- `scripts/scan_crypto_com.py` — profiler for the raw dump.
- `scratch/crypto_com_keys_validate.sql` — aggregates distinct
  `(sport, league, market_type, contract_type, period_type,
  outcome_type)` game-line tuples from the live feed. The key-validation
  query behind the config maps below.

### Config is data-driven from the feed (dictionary is only a cross-check)

The K and PX configs were never built from a vendor dictionary — they
were extrapolated from the market data we actually observed. crypto.com
is the same: the `CryptoConfig` maps are driven by the **distinct
`contract_type` / `outcome_type` / `period_type` values seen in the live
FIX feed**, not transcribed from any catalogue.

There *is* a catalogue — `data/predict_mapping_json.json`, crypto.com's
enum dictionary (per-sport `BettingBetTypes` / `BettingMarketTypes` /
`BettingOutcomeTypes` / `BettingPeriodTypes`). But it lists the
*possible* vocabulary, not what's *offered*, and the live feed
contradicts it in practice (see below). So it's an after-the-fact
cross-check — useful for spotting a newly-offered game-line type — not
the source of truth. The mappable canonical targets all already exist in
`mappers/market_types.py`: `MONEYLINE`, `POINT_SPREAD`, `GAME_TOTAL`,
`MONEYLINE_3WAY`. No new enum members are needed.

#### Game-line vocabulary (game lines are the only mappable group)

Within `market_type == "Game Line"`, the relevant dimensions are:

  - `contract_type`  → canonical `MarketType` (the dict key)
  - `outcome_type`   → side, dispatched on `MarketType.shape`
                       (Home/Away → team abbrev; Over/Under → over/under;
                        Draw → 3-way draw side)
  - `period_type`    → gate to the full-match period (see gotcha below)

Futures and specials (`Team Future`, `Player Future`, `COMBOS`,
politics/specials) have no `external_game_id` and are **out of scope**.
`Player Prop` is **not** in this gameless set — it is game-scoped and
mappable, just not built yet; see "Player Props" below.

#### Validated against the live feed (2026-06-03, last 7 days)

NBA — `league="NBA"`, `period_type="Full Game"`:

| `contract_type` | → `MarketType`        | outcomes seen   |
|-----------------|-----------------------|-----------------|
| `Moneyline`     | `MONEYLINE`           | Home, Away      |
| `Spread`        | `POINT_SPREAD`        | Home, Away      |
| `Total Points`  | `GAME_TOTAL`          | Over, Under     |

Soccer (World Cup) — `league="FIFA"` (also a little `MLS`),
`period_type="90 Minutes and Stoppage Time"`:

| `contract_type`     | → `MarketType`     | outcomes seen      |
|---------------------|--------------------|--------------------|
| `Moneyline (3-Way)` | `MONEYLINE_3WAY`   | Home, Away, Draw   |

Not yet live for FIFA in the sampled window: `Total Goals` (→ `GAME_TOTAL`)
and `Spread` (goal handicap → `POINT_SPREAD`). They appeared in earlier
all-sport windows and will likely show nearer match time — add the keys
when the feed confirms them, don't pre-map from the dictionary.

#### Gotchas the validation surfaced

1. **No NBA 3-way / Draw.** The dictionary lists `Moneyline (3-Way)`,
   `Spread 3-Way`, and a `Draw` outcome for NBA — none are actually
   offered. Don't map them; basketball can't draw.
2. **The period label is per-league and feed-defined.** NBA uses
   `"Full Game"`; soccer uses `"90 Minutes and Stoppage Time"`. Neither
   matches the dictionary's `"Full-Game"`. So the period gate must be a
   per-`CryptoConfig` constant taken from the feed, not a shared literal.
3. **Soccer `Draw` is live in the feed** (n≈52) even though the
   dictionary's soccer `BettingOutcomeTypes` is empty — another reason
   the feed wins over the catalogue.
4. **`FIFA` is the World Cup league label.** No `fifa`/`worldcup` league
   module exists yet (current: EPL/MLB/NBA/NCAAB) — still to build (step
   below). Confirm the Optic canonical schedule carries a Draw selection
   for 3-way, or draw rows stay novel with nothing to merge onto.

#### Proposed `CryptoConfig` shape (design only — not yet written)

A sibling of `PxConfig` / `KalshiConfig`, one instance per league module,
keyed on the feed's game-line vocabulary:

```python
# in mappers/exchanges/crypto_com.py
@dataclass(frozen=True)
class CryptoConfig:
    sport_grouping: str                 # eventMeta SPORTS_GROUPING, e.g. "NBA"
    league: str                         # eventMeta LEAGUE, e.g. "NBA", "FIFA"
    period_type: str                    # full-match gate, per-league (feed-defined)
    contract_types: dict[str, MarketType]   # contract_type -> canonical MarketType

# in mappers/leagues/nba.py
CRYPTO = CryptoConfig(
    sport_grouping="NBA", league="NBA", period_type="Full Game",
    contract_types={
        "Moneyline":    MarketType.MONEYLINE,
        "Spread":       MarketType.POINT_SPREAD,
        "Total Points": MarketType.GAME_TOTAL,
    },
)

# in the (new) soccer/World Cup league module
CRYPTO = CryptoConfig(
    sport_grouping="SOCCER", league="FIFA",
    period_type="90 Minutes and Stoppage Time",
    contract_types={
        "Moneyline (3-Way)": MarketType.MONEYLINE_3WAY,
        # add "Total Goals"/"Spread" once the feed confirms them live
    },
)
```

Same discipline as the existing exchanges: only `contract_type`s with an
explicit `MarketType` mapping produce canonical rows; unmapped game-line
types are skipped/raise rather than carried.

## Next steps

Steps 1–4, the pipeline wiring, and the integration fixture are all
**done** on `mm-794-add-nba-mapping` (`8a8b71a` wire, `ea8d7bb`
identity-based sides, `7c3e5f9` fixture). Remaining: the deferred gold
question below, and the "Later" items.

### DONE — Wire crypto.com into `pipeline.py` (commit `8a8b71a`)

Mirrored how PX and Kalshi are already wired. Concretely:

1. **Load the input file.** In `build_pipeline` (`mappers/pipeline.py`),
   alongside the PX/Kalshi loaders, read
   `data_dir / "crypto_com_markets.jsonl"` via `lines_if_exists` and
   `crypto_com.parse_selection(line)`. For dev before the BQ query
   exists, the stand-in is `scratch/crypto_com_markets.sample.jsonl`.
   Gate the whole crypto block on `league.CRYPTO is not None` so
   leagues without crypto coverage are unaffected.

2. **Resolve each selection's game to a `MatchKey`.** crypto.com gives
   full participant names, so alias-resolve them with the `"crypto"`
   submap from `load_aliases(config/<league>/team_aliases.toml)` —
   `resolve_team(sel.home_participant, crypto_aliases)` etc. The
   game-date side of the key must be derived the **same way the other
   exchanges derive it** (ET date — see how Optic/PX build their
   `MatchKey`; reuse `to_et_str` / the existing date helper, don't
   hand-roll). Group selections by resolved `MatchKey`.

3. **Build rows per matched game.** For each game in the schedule index
   that has crypto selections, call
   `crypto_com.build_rows(start_date, home, away, sels, league.CRYPTO,
   league=league.league)`. `build_rows` already filters to game lines
   at the period gate and raises on unmapped game-line contract_types.

4. **Merge.** crypto rows collapse onto existing Optic/PX/Kalshi rows by
   `row_key` (pipeline.py ~line 140). Make sure the merge stamps the
   `crypto_*` fields onto the merged row the same way `px_*`/`kalshi_*`
   are carried. **crypto rows are novel** (no Optic `source_ids`
   cross-check — see "Source IDs" above), so confirm a crypto row that
   matches *no* Optic row is still carried (novel), not dropped. Check
   how the reconcile/orphan path treats unmatched rows.

5. **Serialize.** Add a conditional `crypto` sub-object to
   `canonical_row_to_json` (pipeline.py:196), mirroring the `kalshi`
   block: emit `security_id`, `symbol`, `market_id`, `outcome_id`,
   `selection_name` (and `side` if useful) when
   `row.crypto_security_id is not None`, else `None`.

**Regression (done):** existing crypto-less data stays byte-identical
apart from the additive `crypto_com:null` (verified over 17.6k rows and
the regenerated NBA/NCAAB snapshots). The new behaviour has its own
fixture — `tests/mappers/fixtures/2026-06-04/09_44` driven by
`test_crypto_integration.py`. The sample's NYK/OKC game (2026-03-04)
predates our Optic `data/` (starts 2026-03-06), and there is no live
crypto feed for the upcoming game — the FIX table holds only sporadic
ad-hoc SecurityList snapshots, not a continuous feed for current
fixtures (in the data as of 2026-06-04, catalogue bursts published
2026-06-02/03; see "Source IDs"). So the fixture takes the **real** March
NYK/OKC crypto selections, relabels the away team OKC→SAS and re-dates
them onto the real upcoming NYK/SAS Optic+Kalshi+PX game (carved from a
prod snapshot, trimmed to game lines). It is a `--json` snapshot, not a
gold file (see gold note below). All 23 selections merge — moneyline
onto all three sources, spread/total onto Optic's line ladder.

### Sides are identity-based (and why the flip is matching-only)

crypto.com side resolution resolves each selection's **own**
participants (`sel.home_participant` / `away_participant`), not the
fixture's home/away position — the same identity principle PX
(competitor_id) and Kalshi (ticker code) use. The NYK/SAS fixture
surfaced why this matters: an earlier positional version cross-wired
the bet whenever the schedule-match flip fired (crypto's home/away
opposite to Optic's). With identity-based sides the flip only
re-attaches a game to the right schedule entry — it never decides which
team a bet is on. That is load-bearing for neutral-site sports (World
Cup soccer), where home/away genuinely disagrees between sources. Fixed
in `ea8d7bb`; `build_rows` asserts the selection's two resolved teams
are exactly the fixture's `{home, away}`.

### Open question (deferred): gold doesn't know about crypto

`canonical_row_to_json` now emits a first-class `crypto_com` block, but
the **gold** path — `gold_row` in `pipeline.py`, checked by
`scripts/check_gold.py` — was deliberately left untouched. Greg's call
(2026-06-04): defer until a crypto row actually lands in a gold file.
The NBA integration fixture uses a `--json` snapshot, not gold, and all
its crypto rows merge — so the gap below hasn't bitten yet. Revisit when
a gold file carries crypto, or the first novel crypto row appears.

The gap: `gold_row` emits a fixed 12-field record (the 8-field merge
key plus the optic/px/kalshi IDs) with no crypto column. Once crypto
data flows:

- A **merged** crypto bet is fine — gold already records its
  optic/px/kalshi IDs, and the crypto match rides along in `--json`.
- A **novel** crypto bet (matched no other source — a crypto-only line,
  or later a soccer 3-way Draw with no Optic 3-way to merge onto) lands
  in gold as a key with all four IDs `null` and no `security_id`.
  Self-consistent (re-running `check_gold` still passes) but blind:
  gold can't say *which* crypto contract, nor catch a crypto mapping
  changing. Matters little for NBA (moneyline/spread/total overlap the
  other books, so crypto almost always merges); matters more for World
  Cup soccer, where novelty is likelier.

If we decide to capture crypto in gold, do **not** regenerate the 84
precious gold files (`run.py` refuses to overwrite them — they encode
mapping correctness earned through betting). The clean route: add
`crypto_security_id` to `gold_row`, and change `check_gold` to compare
an explicit field list (treating an absent key as `null`) so old gold
files stay valid. Naively adding the field breaks all 84 —
`check_gold` compares whole dicts (`if s != c`), so every old row (no
crypto key) would mismatch the new output and fail with spurious empty
"changed" diffs.

### DONE — resolve crypto teams by ID, not by full name

Crypto team resolution now keys on crypto's stable **external team ids**
(`EXTERNAL_HOME_ID` / `EXTERNAL_AWAY_ID`), not full participant names.
The `Selection` model carries `external_home_id` / `external_away_id`;
`load_aliases` accepts a `crypto_id` submap; both call sites
(`crypto_com.py` `build_rows`, `pipeline.py` match loop) resolve on the
ids; the `_resolve_side` / `build_rows` docstrings were rewritten to
match (closing item 9 below). Participant names are retained on
`Selection` for readability/debug only. Verified: `mise test` (198
pass), `pyright` clean, the NBA integration fixture output is
byte-identical (still matches via ids), and the `--json` checksum is
unchanged across a 6-dir NBA subset.

Team ids were confirmed against the live FIX feed (full history,
2026-06-04, via `bq`): exactly the **19** NBA teams already in
`config/nba/team_aliases.toml` carry crypto.com coverage — so the name
backfill (item 8) didn't regress, all 19 now have a real `crypto_id`.
**San Antonio has no crypto.com coverage at all** (absent from both the
backfill dump and the live feed), confirming the earlier suspicion. Its
`crypto_id` is therefore a documented **synthetic sentinel**
(`"SYNTHETIC_SAS"`), existing only for the NYK/SAS integration fixture,
which relabels real OKC selections onto SAS. The sentinel is non-numeric
and never emitted by the feed, so it can't collide with live data — a
strict improvement on the old name *guess* (`"San Antonio Spurs"`),
which could have silently matched or mis-matched real data.

Why names were the wrong key for crypto specifically: PX/Kalshi feeds emit
team *abbreviations* that are usually already the Optic canonical, so
`resolve_team` returns them via its identity path for free and the alias
table only needs the few that differ (`GS`→`GSW`); their numeric id is
just a collision tiebreak, not the lookup key. crypto emits *full names*
(`"Los Angeles Clippers"`), which never equal the canonical abbrev — no
identity free-ride, so every team needs an explicit entry, and a missing
or mis-guessed spelling fails silently or wrong (the SAS guess in the
alias-backfill step). Ids remove that failure mode: immune to
rename/spelling drift, and impossible to guess — they must come from the
feed.

What the feed gives us (verified on the 233 game-line contracts in the
backfill dump):

- `EXTERNAL_HOME_ID` / `EXTERNAL_AWAY_ID` — event-level, **100%
  populated** on game lines, 1:1 with the home/away names. Use these for
  match + side resolution (the home/away ids are always present).
- `TEAM_ID` / `PARTICIPANT` — outcome-level, only ~64% populated (null on
  Over/Under and Draw, which have no team). `TEAM_ID` equals
  `EXTERNAL_HOME_ID`/`EXTERNAL_AWAY_ID` for the team the bet is on.
- `TEAM_ID` ⟷ name is a clean 1:1 (60 ids, no collisions).

As built: a *small* change, not a refactor. `crypto_id` was added to
`load_aliases` `_VALID_KEYS` (a parallel id→abbrev submap; the old
`crypto` name key is kept valid but unused so a stray entry warns rather
than crashes). Both call sites resolve on `sel.external_home_id` /
`sel.external_away_id`. Id resolution is pure string→string — no
collision machinery (ids are globally unique). Ids are opaque in the
TOML, so each entry is commented with its team name. `Selection` gained
the two id fields (`EXTERNAL_HOME_ID` / `EXTERNAL_AWAY_ID` were already
extracted in `crypto_com_cutdown.sql`; the sample input and fixture were
updated to carry them). This supersedes the name-based alias backfill
below — the ids, not names, are now the thing to confirm from the feed.

### DONE — Hourly BigQuery fetcher (`fetch/crypto_com.py`)

> **Amended (2026-06-04).** The *lean, game-lines-only* on-disk output
> this section describes is being replaced by a single **full** format
> shared with the ad-hoc dumper — see "PLANNED — one full on-disk
> format" below. The window/cost/empty-window/dependency notes here all
> still stand; only the written shape and where filtering happens change.

crypto.com is fed from BigQuery, not an HTTP API — the catalogue is read
from `processed_upstream_us.crypto_underlying_securities` (primary) and
`crypto_security_def` (complement); raw FIX messages land in
`marketmaking-test.raw_ingestion_us.crypto_com_fix_messages2`. The
fetcher mirrors the Optic/Kalshi/PX
fetchers (CLI: `--out-dir`, `--max-items`; writes
`crypto_com_markets.jsonl`) and is wired into the `fetch/__main__.py`
orchestrator as a non-required fetcher (like PX/Kalshi — only Optic is
required). It is the first BQ-based fetcher; it uses
`BigQuery/client.py` `ro_client` + `ro_query`.

**Separation of concerns: dumb SQL, smart Python.** The SQL filters to
the SecurityList catalogue in a time window and returns the raw message
(`QUERY` in the module). All the unnesting — what the old SQL did with
one self-join per leaf field — is a recursive walk of the FIX
repeating-group tree in Python (`flatten_message`): per security under
`body.groups.group[]`, read its `field[]` and the `NoInstrAttrib`
group's attribute 99 (a JSON blob of `eventCode`/`eventName`/
`eventMetadata[]`). `to_selection_record` then maps a flattened contract
to the mapper input schema and drops anything that isn't a `Game Line`
(futures/props/specials have no `external_game_id`).

**Why SecurityList only** — established above ("Source IDs", gotchas):
it is the only message type carrying the `eventMetadata` mapping block.
The other types are the price/status streams the trading system reads.
*(Amended 2026-06-05: the catalogue now also — in practice, only —
arrives as per-contract `SecurityDef` messages, which carry the same
block; the fetcher reads both.  See "Feed change (2026-06-05)" below.)*

**Why a 90-minute window** — the cron runs hourly; the 30-minute overlap
means a snapshot landing near an hour boundary is never missed. Output
is consolidated and sport-agnostic (every league in one file); the
pipeline filters to each league's feed label (`league.CRYPTO.league`),
so the fetcher takes no league filter. Dedup keeps the latest snapshot
per `SecurityID` (a window can span more than one catalogue push).

**Cost** — the table is DAY-partitioned on `publish_time`, so a sub-day
window still scans the current day's partition (~5 GB, ~$0.03). Hourly
that's ~$24/mo. There is no cheaper top-level filter — the message
`type` lives inside the `data` JSON, so the type predicate can't prune
bytes. Accepted; noted so it isn't re-investigated.

**Upstream dependency (the real risk).** SecurityList is *request-driven*
(each carries a `SecurityReqID`); in the current ad-hoc backfill it
arrived in sporadic bursts, not hourly. The 90-min window only sees a
fresh catalogue if **something in prod issues a `SecurityListRequest` at
least hourly** — and that request is the FIX **ingestion service's** job,
not market-mapping's. This is not yet known to be wired upstream (Greg,
2026-06-04: "get on with it"). Until it is, expect empty windows.

**Empty-window handling.** An empty window must not crash the hourly
pipeline. The fetcher writes an empty `crypto_com_markets.jsonl`, prints
a loud WARNING naming the likely cause (upstream request not running),
and exits 0 — a missing/empty crypto file degrades to "no crypto
mappings this run" via the pipeline's `lines_if_exists` gate. Verified
both paths against the ad-hoc June catalogue: a 90-min window today
returns 0 (warns, writes empty — the last SecurityList burst published
2026-06-03 14:58, so nothing lands in a recent 90-min window); a wide
window returns 1071 messages → 690 game-line selections, all valid
`Selection`s, no duplicate `SecurityID`s. The
newest snapshot's `publish_time` is logged each run so a silently-stale
catalogue is visible in the run output, not discovered when a mapping
goes missing.

Pure-function tests (`flatten_message`/`to_selection_record`) live in
`tests/fetch/test_crypto_com.py`; the BQ I/O is exercised manually
against the live feed.

### DONE — one full on-disk format (fetcher + dumper converged, 2026-06-05)

**Decision (Greg, 2026-06-04): it is wrong to have two on-disk formats.**
The production fetcher and any ad-hoc dump write the **same** format,
and it is **full** — every per-contract field, all market types,
*unfiltered*. Filtering and translation to mapper concepts happen at
pipeline **read** time. The browse/scan tool works identically on prod
output or an ad-hoc dump — same bytes either way.

Why: the lean fetcher output hid everything the mapper didn't already
consume (the "missing player props" failure mode), and a second format
meant the browse tool couldn't be pointed at prod data. One full format
decouples the (laborious, paid) BQ fetch from all (free, local,
re-runnable) processing — fetch once, view/filter forever, offline.

The intent in one sentence: **flat JSONL, one full contract per line,
written by either the hourly fetcher or an ad-hoc dump, browsed with jq
or `scan_crypto_com.py`, BQ touched only when you want fresher data.**
The split is *structural vs interpretive*: fetch time makes the bytes
browsable (FIX tree → flat record) but never decides what's mappable;
all interpretation (game-line gate, vocabulary translation, team
resolution) lives in the mapper's read path.

As built:

- `fetch/crypto_com_fix.py` *(module since removed, 2026-07; see SecurityDef
  split below)* — `flatten_message`: the lean mode is gone;
  it always emits the full record (scalars + `attrVal<tag>` +
  `eventMeta*` + eventCode/eventName).
- `fetch/crypto_com.py` — `fetch_contracts(minutes)` is the shared
  query→flatten→dedup helper (stamps `fix_type`/`publish_time`
  provenance; keeps no-SecurityID contracts rather than dropping —
  hide nothing). The fetcher writes the full catalogue, unfiltered.
- The ad-hoc browse downloader (`scripts/dump_crypto_com.py`) is GONE —
  folded into the fetcher (Greg, 2026-06-05: one tool, used cleanly ad
  hoc). `python -m fetch.crypto_com --hours N --out <path>` is the
  ad-hoc form; `--out-dir <dir>` is the cron form. Both print the
  market_group×event_type breakdown teaser. Empty-window semantics
  differ deliberately: cron writes an empty file and exits 0 (must not
  kill the hourly run); ad-hoc `--out` writes nothing (don't clobber a
  good local dump with emptiness).
- `mappers/exchanges/crypto_com.py` — `to_selection_record` moved here
  (the interpretive half); `parse_selection(line) -> Selection | None`
  consumes the full record and returns None for non-game-lines, which
  the pipeline load loop skips. This is where Player Props become
  reachable later (see "Player Props (NBA)").
- Fixture + sample re-cut to the full shape from the *real* dump records
  (all 49 found by SecurityID in `data/crypto_com_dump.jsonl`), with the
  mapper-visible fields overridden from the old lean values so the
  OKC→SAS relabel + re-date is preserved exactly.

Verified: parsed `Selection`s byte-equivalent across formats for all 49
fixture/sample records; `--json` checksum identical over a 4-dir subset
(stash-and-rerun); `mise test` 203 pass; pyright clean. Superseded
dumps deleted (the 333M Jun-3 backfill, the old cutdown results, the
duplicate dump, dev scraps); `data/crypto_com_dump.jsonl` is the
remaining reference dump.

### Feed change (2026-06-05): catalogue arrives as SecurityDef, not SecurityList

What we found probing the live table today (ad-hoc BQ histograms +
fetch of every catalogue message):

- **The table was restarted** — data begins 2026-06-04 09:00 UTC.
  Everything profiled before that date (the 268k-message dump, the
  185k-message eventMetadata check) came from the table's previous
  life.
- **Zero `SecurityList` messages since the restart.** The hourly
  fetcher's old `type = "SecurityList"` filter saw an empty window
  every run.
- **The catalogue now arrives as `SecurityDef` (35=d)** — one contract
  per message, the same per-security FIX subtree promoted to the
  message body, same attribute-99 `eventMetadata` blob.  Each still
  carries a `SecurityReqID` (`seclist_*`), so they are still responses
  to catalogue requests — but delivered as an **incremental trickle of
  new contracts, not full snapshots**: 108 messages over ~30h across
  29 distinct request IDs of 1–18 contracts each.
- **The SecurityDef record is a strict field superset** of the old
  SecurityList record (verified against
  `scratch/crypto_com_markets.sample.jsonl`: no field lost).  New and
  useful: `SecurityDesc` (clean human label), `StrikePrice`/
  `MaturityDate`, the FIX-native strike encoding (`attrVal521/522`),
  and new eventMetadata `EXTERNAL_MARKET_ID` / `EXTERNAL_OUTCOME_ID` /
  `PLAYER_ID`.  Every field the mapper reads is present and verified
  on a live NBA Game Line record.
- Content of the 108: 87 Player Props / 20 Game Lines / 1 blank;
  MLB 58, **FIFA (World Cup) 43**, WNBA 5, NBA 1.  The dump is
  `data/crypto_com_securitydefs.jsonl`.

What we changed (deliberately minimal — early days, the final upstream
format is unknown, so we deal with what we see):

- `fetch/crypto_com_fix.py` *(module since removed, 2026-07; logic lives in
  `fetch/crypto_com_security_def.py`)* — per-security walk extracted to
  `_flatten_security`; `flatten_securitydef` flattens the new envelope
  (body **is** the security; single-entry repeating groups arrive as a
  bare dict, normalised by `_group_entries`).  `flatten_message`
  unchanged in behaviour.
- `fetch/crypto_com.py` — queries both types, dispatches per row
  (`FLATTENERS`), stamps the actual `fix_type`.  Same on-disk record.
- `scripts/scan_crypto_com.py` — accepts both `fix_type` values.

**Deferred to the end (Greg, 2026-06-05): the hourly-cron question.**
Under incremental delivery a 90-min window only ever sees contracts
*added* in that window — "fetch the catalogue hourly" stops meaning
"hold a full catalogue".  Whether the answer is a longer window, local
accumulation, or an upstream full-snapshot request depends on where
the feed format lands; don't design it until the format settles.

**Do not be neurotic about the hourly cron right now (Greg,
2026-06-05).** This is only the second day of development; a reliable
hourly catalogue is a *production* requirement, not a dev one. We work
with the data we have — the ad-hoc dumps (`data/crypto_com_dump.jsonl`,
`data/crypto_com_securitydefs.jsonl`) are sufficient to build and test
mapping. Don't let "the trickle hasn't re-sent the old game lines"
block mapper work (e.g. the World Cup branch).

### Feed check (2026-06-07): nothing new since the Friday dump

Ad-hoc BQ peek (messages per day × `fix_type` since 2026-06-05):

- **No new catalogue messages** since the 4 FIFA `SecurityDef`s of
  2026-06-05 14:09 (player props — still zero post-restart FIFA game
  lines).  No `SecurityList` reappearance either.
- The whole table went quiet after Friday: status stream stopped
  14:09, quote traffic 21:32; Saturday a single quote round-trip at
  12:49; Sunday zero messages of any type.

Consequence for step 2 (crypto WC moneyline): build against
`data/crypto_com_dump.jsonl` — its 155 pre-restart `Moneyline (3-Way)`
contracts (53 group fixtures, 42 country ids) remain the entire FIFA
game-line catalogue.  We're in dev; the feed is in flux — findings
recorded, no action taken.

### Feed revival (2026-06-08) + crypto WC moneyline BUILT

The feed came back the next working day, and step 2 is now built.

A 48h BQ peek (to 2026-06-09) found the catalogue live again on
**2026-06-08, 09:06–14:42 UTC** — both `SecurityList` (175) and
`SecurityDef` (407) this time, plus the full `SecurityStatus` price
stream (1.25M).  Of 691 game lines, **153 were FIFA `Moneyline (3-Way)`
across 52 group fixtures** (outcomes Home/Away/Draw, period "90 Minutes
and Stoppage Time"), 100% carrying `external_game_id` and
`EXTERNAL_HOME_ID`/`AWAY_ID`.  So the FIFA game-line catalogue is no
longer dump-only — it arrives live (still moneyline-only; no `Total
Goals`/`Spread`).  Nothing has arrived since (quiet again on 06-09); the
hourly-cron reliability question stays deferred (production concern).

Built on `mm-810-add-world-cup-2026-mappings`, small commits:

- **Mapper** (`mappers/exchanges/crypto_com.py`): `_resolve_side` gained
  the `THREE_WAY` branch — Home/Away → the selection's own team, Draw →
  `TIE_SIDE` ("_TIE"), the same draw literal Optic and Kalshi emit so a
  crypto draw row merges onto theirs.  A Draw on a 2-way
  moneyline/spread raises (basketball can't draw).  `build_rows` no
  longer stamps a line on 3-way moneyline (it has none).
- **Config** (`mappers/leagues/world_cup.py`): `CRYPTO = CryptoConfig(
  sport_grouping="SOCCER", league="FIFA", period_type="90 Minutes and
  Stoppage Time", contract_types={"Moneyline (3-Way)": MONEYLINE_3WAY})`.
  `Total Goals`/`Spread` get keys when the feed shows them — **added
  2026-06-10, see "Built: crypto spread & total"**.
- **Aliases** (`config/world_cup/team_aliases.toml`): a `crypto_id`
  submap seeded from the live feed — 42 of 48 countries at the time
  (the 6 then-absent — BIH, COD, CZE, IRQ, SWE, TUR — **were added
  2026-06-10 from the live feed; all 48 now mapped**).  An unmapped id
  falls through `resolve_team`'s identity path and just fails to match,
  no crash.
- **Tests**: 3-way unit tests in `test_crypto_com.py` + a single-game
  integration fixture (`tests/mappers/fixtures/2026-06-09/15_00`, USA v
  Paraguay) driven by `test_wc_crypto_integration.py`.

Verified end to end on real data (wide-horizon Optic fetch +
public-endpoint Kalshi + the 06-08 crypto dump): **34 crypto games → 99
rows (66 team + 33 draw), 100% merged onto Optic+Kalshi, 0 novel** —
every Draw leg landing on Optic "Draw" / Kalshi `-TIE`.  The 18
unmatched crypto games are 06-25+ fixtures beyond the Optic horizon,
correctly skipped (not mapping failures).  Existing leagues
byte-identical (`--json` checksum over four WC snapshots).

This closes "Later" item 5 below (the soccer/World Cup league config).
Player props and soccer `Total Goals`/`Spread` remain unbuilt.

### BigQuery load + the ad-hoc loading decision (2026-06-09)

**The load is built.** `BigQuery/load_mappings.py` `flatten_rows` now
emits a `sportsbook="crypto.com"` staging row for every merged crypto
selection, with `source_ids` in crypto's own FIX vocabulary —
`{security_id, symbol}` — the same way Kalshi uses ticker/side and PX
uses event/line.  No schema change: `market_mapping`'s `sportsbook` is
STRING and `source_ids` is JSON, so a crypto row drops in beside the
others.  `mappers.run --table` gained a `crypto_security_id` column.
Tests: `tests/BigQuery/test_flatten_rows.py`.  Because the staging row's
base is Optic-derived (game_id/fixture_id/market_id are REQUIRED), only
crypto rows that **merged** onto an Optic fixture load; a novel crypto
row (no Optic) is skipped — moot for WC moneyline, which always merges.

**Crypto rows are sticky — the key operational fact.** The
`market_mapping` MERGE (`_build_merge_sql`) is a pure upsert
(`WHEN MATCHED UPDATE` / `WHEN NOT MATCHED INSERT`, **no
`WHEN NOT MATCHED BY SOURCE DELETE`**), and there is no TTL/last_updated
purge.  So once a crypto row is loaded it **persists** across later runs
that carry no crypto data: an empty-crypto hour upserts the other books
and leaves the crypto rows untouched.  The one exception is
`_clean_reschedules`, which deletes ALL sportsbook rows for a game whose
start_date changed — and an empty-crypto hour won't re-insert crypto, so
a *rescheduled* fixture loses its crypto rows until crypto re-lands (the
documented "partial-fetch risk").  Widening the fetch window does **not**
fix that — the reschedule can fall in any hour.

**Cron crypto is empty almost always, and that's expected.** The hourly
cron fetches crypto with a 90-min window, but the catalogue
(SecurityList/SecurityDef) publishes in sporadic multi-day bursts, not
hourly — so most cron runs log "no catalogue messages in the window",
write 0 contracts (the designed empty-window path), and the pipeline
continues.  A reliable hourly catalogue is an upstream (FIX-ingestion)
concern, still deferred.

**Decision (Greg, 2026-06-09): populate crypto via AD-HOC loads; do not
engineer robust hourly crypto for the World Cup.** Two facts make this
sound, and there is no great harm in it: (1) the World Cup is a *one-off*
~3-week tournament, not a rolling season needing continuous fresh
coverage; (2) rows are sticky, so a single load while a catalogue burst
exists populates the table durably.  So: fetch a wide window once, write
mappings, load — the rows then stick for the tournament.  The only
ongoing exposure is a rescheduled fixture during an empty-crypto hour
(near-zero for group games; a known narrow risk for the knockouts —
just re-load crypto if a knockout fixture reschedules).

Ad-hoc load done 2026-06-09 (on the test VM,
`GCP_PROJECT=marketmaking-test`): **99 crypto rows across 34 WC fixtures**
(66 team + 33 Draw legs) into `marketmaking-test.markets_us.
market_mapping`, `source_ids = {security_id, symbol}`.  Recipe — the wide
Optic horizon is what lets the 06-13+ crypto fixtures find an Optic
fixture to merge onto:

    # on the VM, env sourced (set -a && source .env && set +a)
    .venv/bin/python -m fetch.optic --league world_cup --horizon-hours 360 --out-dir <dir>
    .venv/bin/python -m fetch.kalshi --league world_cup --out-dir <dir>   # real creds on the VM
    .venv/bin/python -m fetch.crypto_com --hours 36 --out <dir>/crypto_com_markets.jsonl
    .venv/bin/python -m mappers.run --league world_cup <dir> --write-mappings
    .venv/bin/python -m BigQuery.load_mappings <dir>/mappings.jsonl

(The raw FIX feed lives in `marketmaking-test.raw_ingestion_us.
crypto_com_fix_messages2`; mapped rows land in
`marketmaking-test.markets_us.market_mapping`.  Locally, swap
`fetch.kalshi` for `scratch/fetch_kalshi_public.py world_cup <dir>` since
the Kalshi creds are IAM-blocked off-VM.)

**Running the recipe on the PROD VM — two gotchas (hit 2026-06-11).**

1. **The crypto fetch finds nothing on prod.** The raw FIX table
   exists only in `marketmaking-test`; on the prod VM
   (`GCP_PROJECT=rs-marketmaking`) `fetch.crypto_com` queries the
   prod project and reports an empty window every time, whatever
   the `--hours`.  The working route: fetch the snapshot locally
   (or grab an existing `scratch/` dump) and scp it up as
   `<dir>/crypto_com_markets.jsonl`, then resume the recipe from
   `mappers.run`.  (Overriding `GCP_PROJECT=marketmaking-test` for
   just the fetch step would also work *if* the prod VM's service
   account has BQ read on the test project — untested.)
2. **The out-dir must be `data/YYYY-MM-DD/HH_MM`.**  `pipeline.run`
   parses `fetch_time` from the directory layout
   (`pipeline.py` ~line 336) and crashes on any other name — a
   `data/2026-06-11_crypto_reload`-style dir fails before mapping.

### Later (out of scope for the NBA branch)

5. **Soccer / World Cup league config.** The feed labels World Cup
   soccer `sport="SOCCER"`, `league="FIFA"`. No `fifa`/`worldcup` league
   exists in the registry yet (current: EPL/MLB/NBA/NCAAB). Needs a new
   league module — see `docs/adding-soccer.md`. Period gate for
   this module is `"90 Minutes and Stoppage Time"`. The mapper's
   `_resolve_side` does **not** yet handle the `THREE_WAY`/`Draw` branch
   — add it with this module (the 3-way draw side literal is `"_TIE"`).

   **Updated 2026-06-07 — sequencing agreed and Optic probed** (full
   detail in `docs/adding-world-cup-2026.md`):

   - **Build order: Kalshi WC moneyline first, then crypto** (no PX
     for the World Cup). The crypto step is step 2 of the agreed
     build order in that doc.
   - **The Draw question is resolved.** Optic's WC league
     (`fifa_-_world_cup`, all 72 group fixtures active) quotes
     Home/Away/**Draw** on its 3-way moneyline across every book
     sampled, and Kalshi's KXWCGAME carries an explicit `-TIE` leg.
     Draw rows merge; they are not stranded novel.
   - **Team aliases: the `crypto_id` seed already exists.** The
     backfill dump (`data/crypto_com_dump.jsonl`) holds **42 of the
     48** WC countries with feed-confirmed `EXTERNAL_HOME_ID`/
     `EXTERNAL_AWAY_ID` (100% populated on game lines). Names are
     FIFA-style ("IR Iran", "Korea Republic", "Cote d'Ivoire") —
     expect drift vs Optic spellings, which is why the id key
     matters. The 6 missing countries get entries when the feed
     shows them.
   - **What the dumps hold for FIFA** (checked 2026-06-05): 155
     deduped game-line contracts across 53 group fixtures — all
     `Moneyline (3-Way)`, no `Total Goals`/`Spread` yet. 4 fixtures
     are missing one leg of the 3-way (catalogue-trickle gaps), so
     don't assume 3 legs per fixture. The post-restart SecurityDef
     trickle has delivered **zero** FIFA game lines — only player
     props — so the game-line catalogue exists only in the
     pre-restart dump (see the cron note above: work with the data
     we have).

6. **BQ query + fetch wiring — DONE.** See the "Hourly BigQuery fetcher"
   section below. The query was *minimised*, not "refined" — rather than
   teach SQL to emit the input schema (the 400-line monster, or the
   ~130-line cut-down, both unnesting the FIX tree with one self-join per
   leaf), SQL now only filters to SecurityList in a time window and
   returns the raw message; the flatten-to-input-schema is a Python walk
   in `fetch/crypto_com.py` (the `QUERY` constant is the minimal SQL).
   `scratch/crypto_com_cutdown.sql` is kept as-is — the verbose
   self-join extract is still handy for ad-hoc column-level exploration.

8. **NBA alias backfill — DONE (superseded by ids).** All 19
   crypto-covered NBA teams now carry a feed-confirmed `crypto_id` in
   `config/nba/team_aliases.toml`. The live feed (full history,
   2026-06-04) returned exactly those 19 — the other 11 (BKN, CHI, CLE,
   DET, GSW, LAL, MIA, PHX, SAC, SAS, TOR) have no crypto.com coverage,
   so they get no `crypto_id` (add when the feed shows them). The old
   SAS name **guess** is gone; SAS has no feed id at all, so its
   `crypto_id` is a documented synthetic sentinel (`"SYNTHETIC_SAS"`)
   for the integration fixture only — see the DONE section above.

### Remaining items from the V2.0 spec cross-check

These came out of checking the V2.0 Rules-of-Engagement appendix against
the code (2026-06-04). Detail is what's already known — next agent to
plan/implement.

9. **Tighten the "identity-based side" comment — DONE** (with the
   id switch). The `_resolve_side` and `build_rows` docstrings now
   resolve on the feed's `EXTERNAL_HOME_ID` / `EXTERNAL_AWAY_ID` and say
   so. The comment was made honest about what these are: **event-level**
   fields that describe the game (identical across every selection of
   it), with `outcome_type` selecting which of the two teams the bet is
   on. It notes the genuinely per-outcome id would be the outcome-level
   `TEAM_ID`, but that is null on Over/Under and Draw, so we key on the
   always-present event home/away ids and dispatch the no-team outcomes
   on `outcome_type` ("over"/"under", `_TIE`). Orientation-robustness is
   unchanged (we resolve crypto's own home/away, so a schedule flip can't
   cross-wire the bet).

10. **Period gate "Full Game" vs "Full-Game" — confirmed, no action.**
    The spec's MLB example uses `"Full-Game"` (hyphen); its prose (§5)
    says `"Full Game"` (space) — the spec is internally inconsistent. The
    code uses `"Full Game"` (space), feed-validated (see gotcha #2). The
    spec confirms the period label is unreliable as a shared literal,
    which is exactly why the gate is a per-`CryptoConfig` feed-defined
    constant. Recorded so it isn't re-investigated; nothing to change.

## Player Props — first one BUILT (soccer Anytime Goal Scorer)

Re-examined 2026-06-04 (Greg). An earlier draft of this doc — and two
code comments — bundled `Player Prop` with futures/COMBOS as "no
`external_game_id`, out of scope". **That was wrong**, and the live feed
disproves it. Player props are **game-scoped and mappable**; they are a
real workstream, not a write-off. The comments are now corrected
(`mappers/exchanges/crypto_com.py` module docstring;
`fetch/crypto_com.py` `to_selection_record`). This section is the
evidence and the plan; the first prop is now built (below), the rest
remain a plan for the next agent.

### BUILT (2026-06-10): soccer Anytime Goal Scorer, on mm-810

The first crypto player prop is shipped — World Cup **Anytime Goal
Scorer**, the live data the 2026-06-08/09 bursts confirmed (793
contracts, see "Feed revival"). Soccer-first, per the sequencing call
below.

- **Mapping** (`mappers/exchanges/crypto_com.py`): a prop takes its own
  path in `build_rows` (`_player_prop_row`) — player-scoped, no team
  side. Anytime Goal Scorer is crypto's "1+ goals" Yes/No threshold;
  `_resolve_prop_line_side` maps outcome `Yes` → `(line=0.5, side=over)`,
  landing on Optic's over-only `player_goals` ladder and Kalshi's
  KXWCGOAL `1+` leg. The threshold is keyed on the **contract_type**,
  not the MarketType (a future "To Score 2+ Goals" → over 1.5), so it
  belongs to the contract.
- **Config** (`mappers/leagues/world_cup.py`): `CryptoConfig` gained
  `prop_contract_types={"Anytime Goal Scorer": PLAYER_GOALS}` and
  `prop_period_type="90 Minutes and Stoppage Time"`, kept **separate**
  from the game-line `period_type` by discipline (NBA props use
  `"Full-Game"` vs game lines' `"Full Game"`; soccer happens to
  coincide — gotcha #2/#3).
- **Player resolution is NAME-based, NOT the `crypto_player_id` map the
  plan recommended.** The entity is `normalize_player_name(participant)`.
  Rationale: for goalscorer markets Optic, Kalshi *and* crypto all
  normalise player names through the **same** `normalize_player_name`
  (diacritics stripped — "Harry Kané" → `harry_kane`), so crypto gets
  the identity free-ride that teams don't (teams emit full names vs
  Optic abbrevs, which never coincide — hence the team-id key). This
  matches the Kalshi-side WC goalscorer decision ("Built: anytime
  goalscorer" in `docs/adding-world-cup-2026.md`). `player_id`/`team_id`
  are carried on `Selection` for provenance and as the stable key for a
  future id-based map *should a spelling ever fail to merge* — the
  team-id argument (blocker 1) still applies if names drift, it just
  doesn't bite here.
- **Unmapped props are SKIPPED, not raised** — the opposite discipline
  to game lines. `_player_prop_row` returns None for any prop
  contract_type without a canonical target, because the mapped prop set
  is a deliberately chosen subset of the offered set (~17 live FIFA prop
  types); raising would break the pipeline on every shots/fouls/cards
  contract. (For game lines the mapped set *is* the offered set, so an
  unmapped game-line type still raises.)

**Two robustness fixes the at-scale check forced** (validating the
mapper against the whole 2026-06-09 burst, not just the fixture — the
single hand-built record never exercised these):

- **`Selection.outcome_type` made optional.** Soccer `First Goalscorer`
  and the `N+ Saves` ladder carry a **blank** outcome_type (the
  threshold is in the contract_type string). Passing player props
  through `to_selection_record` made `Selection(**rec)` *raise* on every
  one — 612 First Goalscorer + ~96 Saves in the burst, i.e. the pipeline
  would crash the first time it saw one. Blank now parses; those props
  are unmapped and skipped before outcome is read. A game-line call site
  asserts the outcome is present (it always is for game lines).
- **`external_game_id` gate in `to_selection_record`.** The feed
  mislabels a few gameless markets as `Game Line` (PGA "Ryder Cup", no
  game id or teams) which crashed the Selection model. A real game line
  or prop has the game id 100% of the time, so a record without one is
  dropped on read — the same fixture-attachment rule the docstring
  already stated, now enforced where it bites.

**Verified** against the 06-09 burst fetch (`fetch.crypto_com --hours
12`, post combo-exclude): **0 parse crashes over 22,900 records (was
712)**; all **793** Anytime Goal Scorer contracts → `Yes` → `(0.5,
over)` across 702 players / 16 fixtures; all 12,983 other FIFA props
skipped, 0 raised. Integration fixture (USA v Paraguay, Haji Wright)
merges the AGS row onto Optic's real `player_goals` over-0.5 by
normalised entity. `mise test` 226 pass, pyright clean. **Kalshi-side
merge unverified until KXWCGOAL posts markets** (same caveat as the WC
GOAL work) — Optic merge is proven by the fixture; expect Kalshi's
*under* sides to be novel (Optic's ladder is over-only).

#### Next steps (agreed 2026-06-10), in order

1. **Crypto `Total Goals` and `Spread` game lines — DONE 2026-06-10,
   see "Built: crypto spread & total" below.**
2. **Re-verify the combo exclusion against the RFQ flow — DONE
   2026-06-11, exclusion stands.** RFQ legs ride inline in the
   QuoteRequest message; no combo catalogue needed. See "ANSWERED:
   'ignore the combos' HOLDS for the RFQ flow" below.
3. **Then the rest of the player props.** Extend prop coverage beyond
   Anytime Goal Scorer to the other ~16 live FIFA prop types — the
   threshold Yes/No family (`N+ Shots`, `N+ Saves`, `To Score N+ Goals`,
   cards, fouls) and the blank-outcome `First Goalscorer`. This is the
   harder shape (the threshold is baked into the contract_type string,
   so the vocabulary map can't stay a flat `contract_type -> MarketType`
   — see "Soccer props look different"), and each needs a canonical
   target plus a live Optic/Kalshi market to merge onto.
4. **Add BTTS (Both Teams To Score) — DONE 2026-06-19.** The one
   game-scoped market the bucketing missed (a third `Game Prop` group).
   Built as a new market group on `world_cup.py` — see "BUILT
   (2026-06-19): BTTS" below. All 16 crypto BTTS rows in the 06-18 burst
   merged onto Optic+Kalshi, 0 novel.

NBA props stay deferred (no live upcoming data — blocker 4).

### Built: base-letter fold in `normalize_player_name` (2026-06-11)

Measured how the AGS name free-ride actually performs on the
2026-06-11 snapshot: **519/702** crypto AGS players matched an Optic
`Player Goals` name (exactly the 519 player_goals rows the 06-10 load
carried — name matching is precisely what gates the load). Of the 183
misses, ~117 are players Optic doesn't quote (genuine novelty), ~58
are the same player spelled differently — the silent-merge-failure
risk blocker 1 predicted. Fix sequence agreed (easy → hard): first
normalization, then the alias map for the rest.

**The normalization gap:** NFD + Mn-strip folds é→e, ć→c, ş→s but
passes through Latin letters that have **no decomposition** — ı, ß,
ø, ł, đ, æ, œ, ð, þ. So Optic's "Barış Alper Yılmaz" became the
half-normalized `barıs_alper_yılmaz`, unmergeable with crypto's ASCII
`baris_alper_yilmaz`, and every Norwegian/Turkish entity (Ødegaard,
Sørloth, Groß) was non-ASCII forever. Fixed with a hand-audited
`_BASE_LETTER_FOLD` table in `mappers/shared.py` (deliberately not a
library transliterator — every folded letter is chosen and verified).

**Why this was the free moment, and the regression evidence:** the
fold is provably a no-op on everything persisted — zero of the nine
letters appear in prod-VM gold (336 files, 3.35M entity rows, scanned
over ssh), local gold (134 files, 718k rows), or `market_mapping`
(test + prod, all 2026). Subset `--json` checksum byte-identical
(NBA/NCAAB/MLB dirs); the WC diff is exactly the predicted change —
14 Optic players renamed to ASCII, 6 formerly-novel crypto AGS rows
(Bardakçı, Yılmaz, Elmalı, Kadıoğlu, Aydın, Groß) now merged onto
Optic. 519→525 matched.

**Hyphens and apostrophes deliberately KEPT** (the docstring records
this): both live in persisted entities (24 gold players — `de'aaron_
fox`, `karl-anthony_towns` — plus 700+ loaded NBA rows), all sources
spell them consistently for mapped players (8 punctuated crypto WC
rows are loaded and merged), and stripping would have bought exactly
+2 matches. The two asymmetric cases (crypto "N'Dicka" vs Optic
"Ndicka"; "Jean-Jacques" vs "Jean Jacques") go to the alias map.

**The alias-map step — BUILT the same day (2026-06-11), see below.**
The remaining misses were nickname/full-name (Andy/Andrew Robertson),
extra middle names (`garry_rodrigues` vs `garry_mendes_rodrigues`),
and systematic transliteration (crypto `xusanov` vs Optic `khusanov`)
— per-player aliases, not normalization.

### Built: crypto player-id alias map (2026-06-11)

Per-fixture, team-aware matching of the 177 post-fold unmatched AGS
players against Optic's `Player Goals` names produced 120 same-player
candidates, written to `scratch/crypto_player_alias_review.md` ordered
by confidence (A certain / B high / C verify / D doubtful) with the
match basis per row. Greg reviewed and accepted 119, rejecting the one
D (crypto "Ryan Mendes" → Optic "Jordan Mendes" — likely different
players). The candidate generator excludes any Optic name already
exactly matched by another crypto player in the same fixture — that
rule alone killed the Jurriën→Quinten Timber twin trap.

What the candidates revealed: the dominant pattern (~80) is **Optic
quoting full legal/registry names where crypto uses common names** —
Saudi/Qatari/Egyptian legal names ("Almoez Ali" vs "Almoez Ali
Zainalabedeen Mohamed Abdulla") and Brazilian/Cape Verdean registry
names ("Endrick" vs "Endrick Felipe Moreira de Sousa"). The rest:
Anglo nicknames (Gio Reyna, Tim Weah), Uzbek diminutives
(Behruz(jon)), transliteration (X↔Kh), token reorders (Castrop Jens ↔
Jens Castrop), and the two punctuation asymmetries from the
normalization step (N'Dicka, Jean-Jacques).

As built:

- **`config/world_cup/player_aliases.toml`** — 119 entries, canonical
  (Optic) entity first, `crypto_id = ["<PLAYER_ID>"]` per entry,
  commented with crypto's spelling. Keyed on the feed's stable
  PLAYER_ID (100% populated on props, 1:1 with names in the snapshot),
  not the name — the same id-over-name rationale as the team map: a
  crypto respelling can't silently detach an alias. Canonicals with
  apostrophes need quoted TOML keys (`"deroy_d'encarnacao_duarte"`).
- **Zero loader changes** — `load_aliases` already accepts `crypto_id`,
  and `simple_alias_map` gives the id→entity dict.
- **`mappers/exchanges/crypto_com.py`** — `build_rows` takes
  `player_aliases` (default empty); `_player_prop_row` resolves
  `entity = player_aliases.get(player_id) or
  normalize_player_name(participant)`. A miss falls back to the name
  path and at worst stays novel.
- **`mappers/pipeline.py`** — threads
  `player_alias_data.by_exchange["crypto_id"]` into the crypto
  build_rows call.

Verified on the 2026-06-11 snapshot: **all 119 aliases merged** —
exactly 119 formerly-novel crypto AGS rows collapsed onto their Optic
rows (row-key diff: 119 gone, 0 new, 119 Optic rows gained a crypto
block). Final AGS state: **644/702 merged onto Optic, 58 novel** (57
players Optic doesn't quote + the rejected Ryan Mendes). Subset
`--json` checksum byte-identical for other leagues; `mise test` 249
pass; pyright clean.

Maintenance: 32 of 48 teams covered so far. When the remaining teams'
AGS posts (crypto publishes per round), re-run the candidate analysis
on a fresh snapshot, review, append — expect ~60 more entries
tournament-wide. The table serves every future prop type (First
Goalscorer, N+ Shots, …), since they quote the same participants.

### ANSWERED (2026-06-11): "ignore the combos" HOLDS for the RFQ flow

**Verdict: the exclusion STANDS — with caveats.** Every leg of every
combo QuoteRequest rides **inline** in the RFQ message itself
(`NoLegs`/`LegSymbol`/`LegSide`, tags 555/600/624), so the trading
side can resolve a combo to its single-contract legs without the
combo catalogue definitions the fetcher drops. No lean combo→legs
extract is needed. Queries in `scratch/crypto_rfq_combo_check.sql`;
findings, with counts:

1. **The RFQ business is 100% combos.** Across all three QuoteRequest
   sessions (2026-06-05: 385 msgs / 121 distinct combos; 2026-06-09:
   2,710 raw rows → 2,686 deduped msgs / 1,355 distinct QuoteReqIDs —
   not "a handful", the biggest session; 2026-06-10: 882 → 849 / 440),
   **zero** straight-symbol QuoteRequests. Pricing combos is the
   whole quoting business there, not an edge case.
2. **Legs are always inline.** 0 messages without legs, 0 declared-vs-
   actual leg-count mismatches; 2–6 legs per combo. Leg leagues:
   FIFA dominant, plus MLB / TENNIS / WNBA / NBA / NHL / CBB / FIFAF /
   UCL / F1 / SETTLE.
3. **Caveat — the leg key is `LegSymbol`, not securityId.** The RFQ
   carries no `LegSecurityID`, so `symbol` in `source_ids` is the join
   key and must stay loaded (it is — `{security_id, symbol}`). Legs
   matched loaded `source_ids.symbol` **verbatim** in every observed
   match; note symbols come in two forms (with/without a trailing
   `.YYYYMMDD` maturity suffix) and both forms appear in the catalogue
   itself — a robust trading-side join should try exact then
   suffix-stripped.
4. **Caveat — coverage, not combos, is what limits pricability.**
   All-FIFA RFQs whose legs ALL resolve against loaded `market_mapping`
   rows: 168/212 (06-05), 1,260/1,431 (06-09), 507/527 (06-10, 96% —
   improving with each load). Every unmatched FIFA leg classified into
   known buckets: `Moneyline (2-Way)` draw-no-bet (ignored by design),
   unmapped prop types (`6+ Shots` etc.), tail spread lines and
   Optic-unquoted AGS players (novel → skipped at load). Mixed-league
   RFQs (any MLB/TENNIS/WNBA/... leg) never fully resolve — we only
   map WC. If the trading side wants those, that's new league
   coverage, not combo work.
5. **Supersession did not bite.** No RFQ leg was found referencing an
   older vintage where we hold the newer one (the spot-checked
   unresolved AGS legs were single-vintage; they failed for novelty,
   not vintage). The risk stays theoretical — re-check if a
   fully-mapped leg ever fails to resolve.

The original brief follows, kept for the reasoning and the method.

#### The brief as posed (2026-06-11)

**Why this is being re-checked.**  The fetcher excludes all-combo
catalogue messages (`fetch/crypto_com.py` `QUERY` + the
`_assert_not_all_combo` guard; rationale in the QUERY comment and
"one full on-disk format" above): a combo (`Symbol`
`NX.F.OPT.COMBOS-…`) is a parlay bundling 2–3 legs that each
reference an individual single-game contract by securityId; it
carries no `eventMetadata`/`EXTERNAL_GAME_ID`, can't be tied to one
fixture, and a catalogue burst republishes ~4.7 GB of them.  That
reasoning covers *mapping* combos as canonical rows — which remains
out of scope.  What it does NOT cover is the **RFQ flow**: WSD is a
quote-access market maker on crypto.com (Slack, 2026-06-10 evening,
Andrey/Dominic: orders confirmed rejected by crypto, RFQ *creation*
not possible either, order-entry tests used straight symbols like
`NX.F.OPT.FIFA-00004-260617-M.O.1.1`; "combos will have prefix
'combo'").  Our business there is responding to incoming
`QuoteRequest`s.  **If crypto sends QuoteRequests on combo
instruments** (parlays, as Kalshi RFQs are), the trading side must
resolve a combo to its single-contract legs to price it — and the
leg-bearing combo definitions are exactly what the fetcher drops.
Whether anything downstream needs market-mapping's help for that is
the open question; nobody on the trading side was awake to ask, so
check the feed instead.

**The check (all read-only BQ over
`marketmaking-test.raw_ingestion_us.crypto_com_fix_messages2`;
~5 GB/day partitions, keep windows to a day; the type predicate
cannot prune bytes):**

1. **Classify incoming QuoteRequests by instrument.**  Known
   sessions with QuoteRequest traffic: 2026-06-10 11:11–16:01Z
   (882), 2026-06-05 (385), 2026-06-09 (a handful).  For
   `type='QuoteRequest'`, extract the symbol(s)
   (`55=` in `fixText`) and count combo
   (`NX.F.OPT.COMBOS…`/"combo" prefix) vs straight.  If combos
   never appear in QuoteRequests across all sessions, the exclusion
   stands for the quoting business — say so with the sample sizes
   and stop.
2. **If combo QuoteRequests exist, check whether they carry their
   legs inline.**  Inspect the raw `fixText` string: a FIX quote
   request can embed the per-leg repeating group (NoLegs / LegSymbol /
   LegSecurityID, e.g. `|555=…|` / `|600=…|`).  If the legs
   (securityIds) ride in
   the RFQ message itself, the trading service can resolve them
   against our SINGLE mappings (`source_ids.security_id` in
   `market_mapping`) without any combo catalogue — the exclusion
   stands, but note the supersession caveat: an RFQ leg may
   reference an older still-listed vintage, while we keep only the
   latest (see "Built: supersession dedupe"); spot-check a real
   combo RFQ's leg sids against loaded rows.
3. **If combo RFQs reference only the combo securityId** (no legs
   inline), the legs live only in the combo SecurityList
   definitions we drop.  Confirm by pulling one combo's catalogue
   message (`fixText`, look for the per-leg securityId references)
   — then the fix is NOT to un-exclude the 4.7 GB from the mapper
   input, but a separate lean extract (combo securityId → leg
   securityIds, nothing else) for the trading side to join.
   Design that with Greg before building.

**Deliverable**: a verdict written into this section (exclusion
stands / stands-with-caveat / needs the lean extract), with the
queries and counts.

FIFA `Total Goals` → `GAME_TOTAL` and `Spread` → `POINT_SPREAD` added
to `world_cup.py CRYPTO.contract_types`. Config-only on the mapping
side: the game-line machinery already handles both shapes (proven on
NBA), so no parser work.

What the recon confirmed against the live feed:

- **`Total Goals`**: outcomes Over/Under, `PREDICT_VALUE` the total as
  N.5 (0.5–14.5), period `"90 Minutes and Stoppage Time"`.
- **`Spread`**: outcomes Home/Away, `PREDICT_VALUE` the **signed** goal
  handicap as N.5 (Home −2.5 = home favoured by 2.5), same period.
- **No `line_offset` needed** — unlike the Kalshi ticker suffix
  (`adding-world-cup-2026.md`), crypto carries the real line in
  `PREDICT_VALUE`, taken verbatim. The signs align with Optic/Kalshi.

**New finding — `Moneyline (2-Way)` appeared in the same burst.** A
draw-no-bet market (Home/Away, no Draw), with no Kalshi/Optic WC
counterpart we map. Because game-line discipline *raises* on any
unmapped game-line contract_type, it had to be handled in the same
change or it would crash the pipeline. Added a `game_line_ignored`
frozenset to `CryptoConfig` and listed it there — a genuinely-new type
still raises loudly, but this known one is skipped. Ignored for now;
revisit if we ever want draw-no-bet.

Verification (reconcile of crypto spread/total against an Optic+Kalshi
WC snapshot): the 2-way moneyline is skipped with no warning and no
raise; crypto spread/total merge **agreed at common lines and
sign-symmetric** (−2.5 ⇔ +2.5 both merge), confirming the line
convention. The remaining novelty (≈440/750 spread, ≈350/750 total) is
the benign **ladder-extension** pattern — 100% merged at the centre,
novelty growing monotonically to the tails where Optic/Kalshi don't
quote (±7.5+ spreads, 10+ goal totals). A sign or offset error would
have left the centre lines unmerged; they merge fully. `mise test` 229
pass, pyright clean. Tests added in `test_crypto_com.py` (total
over/under, signed spread, 2-way ignored).

**Country aliases completed (2026-06-10).** The 6 World Cup countries
without a `crypto_id` (BIH, COD, CZE, IRQ, SWE, TUR — see "Feed
revival") appeared in the 06-10 feed, so all 48 now carry a feed-
confirmed id in `config/world_cup/team_aliases.toml`.  On the VM run
this took crypto from 40 → **54 games matched, 0 unmatched within the
Optic horizon** (the previously-unresolved games each had one side
falling through to a raw numeric id).

**Game coverage is partial by feed timing, not a bug.** The group
stage is 72 games, but crypto's `Spread`/`Total Goals` covered only
**35 distinct games** (06-11 → 06-21: round 1 + the start of round 2),
versus moneyline on 70.  crypto posts spreads/totals ~10 days ahead
while moneyline is up for the whole tournament; the later rounds get
spread/total when crypto publishes them.  Re-fetch + re-load later in
the tournament to pick them up — rows are sticky, so the 35 stay put
and new games add on.

**Confirmed live + cron-autoloaded (2026-06-18), feed-traced.** The
"re-fetch later picks them up" prediction played out on its own: a
catalogue burst on 2026-06-18 (2,686 `SecurityList` + 54 `SecurityDef`,
published 13:39–15:41 UTC) was picked up **unattended by the hourly
cron on the test VM** — no ad-hoc load — across four consecutive runs
(`last_updated` 13:42, 14:43, 15:42, 16:42 UTC), each mapping the
contracts in its 90-min window.  Result in `marketmaking-test.markets_us.
market_mapping`: **1,131 crypto.com WC rows across 16 games** — 509
`player_goals`, 290 `point_spread`, 284 `game_total`, 48
`moneyline_3way`.  So **FIFA `Total Goals` and `Spread` are now
confirmed live in the feed**, not just config-ready — closing the "add
the keys when the feed confirms them" hedges above (the 2026-06-03
"not yet live for FIFA" note, the `world_cup.py CRYPTO` comment, and the
2026-06-07 "no `Total Goals`/`Spread` yet" dump finding).

Verified the spread/total rows are genuinely from the 06-18 feed (not
sticky carry-over): **all 284 `game_total` + 290 `point_spread`
security_ids (100%) appear as FIX tag-48 SecurityIDs in raw
`crypto_com_fix_messages` rows published on 2026-06-18**, 13:39–15:41
UTC — the same burst window.  Method (precise, no message download):
regexp tag 48 out of `data.fixText` (`\|48=([^|]+)`) over the 06-18
partition only, joined server-side to the mapping rows' `source_ids.
security_id`, returning counts.  Note the security_ids carry an embedded
*issuance* timestamp of 06-03/06-05 (the contracts were created then) —
expected, since crypto creates a contract once and re-broadcasts it; the
06-18 **publish_time** is what proves the feed carried them.  The feed
`Symbol` corroborates the type independently of the mapper (e.g.
`NX.F.OPT.FIFA-…-M.O.2.50.…` = Over 2.5 goals).  The 16-game coverage
here is just this burst's window (vs the 35 from the 06-10 load); sticky
rows mean later bursts add on.

**Loaded to BQ (2026-06-10, `marketmaking-test`).** Ad-hoc load per the
recipe below: **1,664 crypto.com WC rows across 54 games** (409 spread,
576 total, 160 moneyline-3way, 519 player_goals) into
`markets_us.market_mapping`, `source_ids = {security_id, symbol}`.
(Only Optic-merged crypto rows load — novel rows are skipped — so the
loaded spread count 409 is the Optic-merged subset of the 426 that
merged onto Optic-or-Kalshi.)  This supersedes the 06-09 moneyline-only
load (99 rows).  `scratch/demo_crypto_kalshi_mappings.sql` shows the
Kalshi and crypto `source_ids` side by side per canonical bet.
**Prod (`rs-marketmaking`) was loaded the same day pre-dedupe and
reloaded 2026-06-11** — see "Prod carried the defect" in the
supersession section below.

### Built: supersession dedupe (contract re-issuance, 2026-06-11)

The feed **re-issues contracts**: crypto.com re-lists a game's
catalogue in waves, each minting new SecurityIDs/Symbols for the same
betting questions (the symbol's series number and the sid's embedded
issuance timestamp both increase; `EXTERNAL_MARKET_ID`/`OUTCOME_ID`
stay the same — same underlying market, re-wrapped).  The 2026-06-10
snapshot carried **466 World Cup prop questions as two contracts
each** (NED–JPN 194, CIV–ECU 182, GER–CUW 46, BRA–MAR 44), issued
~30–40 min apart on 06-05 and republished seconds apart in the 06-09
catalogue burst.

**The later vintage is the live one** — inferred, with strong
evidence: the *previous* generation of the same game's contracts
(issued 06-02, symbol series 63–1459) was retired by a 19,481-message
`SecurityStatus` (326=50) burst minutes after its replacement was
issued, so retire-on-reissue is the exchange's lifecycle; and all 922
single-vintage NED–JPN props sit in the latest series range — the
earlier-wave slab is stale catalogue residue.  The retirement
messages for *our* pairs were never captured (the ingested table also
missed their original issuance — only 4 SecurityDef messages on
06-05 against ~1,300 contracts minted), so supersession is inferred
from issuance order, not statuses.  Worth asking the FIX-ingestion
owners whether `SecurityStatus` traffic is reliably persisted; it
would give an authoritative "this sid is dead" signal.

Before the fix, both vintages built rows with the same row key and
the pipeline merge kept whichever the **unordered** BigQuery scan
emitted last — nondeterministic, and wrong about half the time
(measured: later vintage won only 241/466; the 06-10 test-BQ load
carried the earlier (dead) sid on 36 of 88 duplicated AGS rows).

The fix: `crypto_com.dedupe_superseded`, applied per matched game in
the pipeline before `build_rows`.  Key = the full feed-vocabulary
question identity (game + home/away ids + market group, contract
type, period, player, outcome, value); winner = max `security_id`
(lexicographic on the embedded issuance timestamp — cross-checked
against the symbol series number on all 466 pairs, zero
disagreements).  The external ids are deliberately NOT the key:
`EXTERNAL_OUTCOME_ID` is blank on 84% of mappable contracts and
`EXTERNAL_MARKET_ID` is a per-player umbrella spanning all of a
player's prop types.  Output is sorted by `security_id`, so row order
no longer depends on scan order.  The pipeline prints a
`N superseded contract vintages dropped` diagnostic when it fires.

Verified over the full 06-10 snapshot: 19,382 mappable selections →
18,719, all 473 multi-vintage questions resolve to the max sid, zero
wrong winners (the non-FIFA drops are crypto's `NX.F.OPT.SETTLE-*`
settlement-test contracts, which never match a fixture anyway).

**Prod carried the defect and was remediated (2026-06-11).**  The
2026-06-10 08:25Z prod load (`rs-marketmaking`, made from the
feature branch before the dedupe existed) was measured directly
against the snapshot's vintage sets: dead sids on **36 of 88**
duplicated AGS rows (NED–JPN 29, CIV–ECU 7) — the same stale
fraction as the test load.  Remediated by an ad-hoc prod reload
(recipe + prod-VM gotchas in "BigQuery load + the ad-hoc loading
decision"): the 06-09-burst snapshot replayed through the fixed
mapper, the MERGE upserting `source_ids` in place.  Verified
after: **0 of 1,678 prod crypto rows carry a superseded sid**; all
88 duplicated-question rows hold the winning vintage.  Two rows
kept their 06-10 stamp (CIV–ECU total 6.5 under, BRA–MAR total 7.5
under) — single-vintage contracts whose lines had drifted off
Optic's ladder by reload time, so the fresh rows were novel →
skipped at load and the sticky originals remain; benign, not a
vintage problem.

No fresher catalogue existed to reload from: the 2026-06-10
11:00–16:00Z "burst" was **7,744 all-combo `SecurityList`
messages** (plus 16 combo `SecurityDef`s; the only real content
was 2 tennis `SecurityDef`s at 15:59Z, correctly the only output
of a fetch over that window).  So the 06-09 burst remains the
latest real single-contract catalogue and no new vintages were
minted on 06-10.  That window also persisted a 105k-message
`SecurityStatus` burst at 15:00Z — so status traffic does reach
the table in volume; whether it reliably covers single-contract
retirements is still the open question above.

### Why the old reasoning was wrong

The "no `external_game_id`" property belongs to **futures**
(`PREDICT_EVENT_TYPE = "Future"`: `Team Future`, `Player Future`), not
props. A **Player Prop** is `PREDICT_EVENT_TYPE = "Game"` and carries the
game id 100% of the time, exactly like a game line. The conflation was
with **Player _Future_** (a season award — "Rookie of the Year",
genuinely gameless), not **Player _Prop_** (an in-game stat line). The
original backfill dump (`data/crypto-com-dump.jsonl`, 539 contracts)
contains **zero** Player Props — only futures — so the claim was
generalised from futures and never tested against an actual prop.

Live feed, last 7 days (2026-06-04, via the FIX table, dedup by
`SecurityID`), `(market_type, event_type)` → game-id fill:

| market_type     | event_type | count | has `external_game_id` |
|-----------------|------------|-------|------------------------|
| Game Line       | Game       | 690   | 690/690 (100%)         |
| **Player Prop** | **Game**   | **8** | **8/8 (100%)**         |
| Player Future   | Future     | 294   | 0/294                  |
| Team Future     | Future     | 475   | 0/475                  |
| Tournament Prop | Tournament | 1     | 0/1                    |
| (blank)         | —          | 9380  | 0/9380                 |

Note `Tournament Prop` (`event_type = Tournament`) is a *futures*-style
prop with no game id — it stays out of scope. Only `Player Prop`
(`event_type = Game`) is in play.

### A prop carries everything needed to map it

A real `Total Rebounds` prop from the live feed (Bruce Brown, DEN @ OKC):

    eventMetaPREDICT_MARKET_TYPE   = Player Prop
    eventMetaPREDICT_CONTRACT_TYPE = Total Rebounds      → PLAYER_REBOUNDS
    eventMetaPREDICT_OUTCOME_TYPE  = Under
    eventMetaPREDICT_VALUE         = 3.5                 → line/side
    eventMetaPREDICT_PERIOD_TYPE   = Full-Game           → NB: hyphen, not "Full Game"
    eventMetaEXTERNAL_GAME_ID      = 20023327            → fixture attach (100% present)
    eventMetaPARTICIPANT           = Bruce Brown         → player name (debug/readable)
    eventMetaPLAYER_ID             = 20002040            → stable player id (resolution key)
    eventMetaTEAM_ID               = 20000020            (= EXTERNAL_AWAY_ID; player's team)

The canonical schema is already prop-ready: `Scope.PLAYER`, the `entity`
field on `CanonicalRow`, and ~40 `PLAYER_*` market types
(`PLAYER_REBOUNDS`, `PLAYER_POINTS`, …) already used by the other
exchanges. So the mapping *target* exists and the feed supplies the
inputs — what's missing is the resolution layer and the wiring below.

### What's genuinely hard (the real blockers, in priority order)

1. **Player-entity resolution — the main new work.** Game lines needed
   only ~19 team-id aliases. Props need crypto's `PLAYER_ID`/name to
   resolve to the *same* `entity` string the other books use. The merge
   key is the **normalised player name** — `normalize_player_name` in
   `mappers/shared.py` (NFD → strip diacritics/periods/generational
   suffixes → lowercase → underscores; e.g. "Nikola Jokić" →
   `nikola_jokic`). Two options: (a) run crypto's `PARTICIPANT` through
   `normalize_player_name` and rely on it colliding with the other
   sources, or (b) build a `crypto_player_id` → canonical alias map.
   **Recommend (b)** — stable, immune to spelling/rename drift, can't be
   mis-guessed — exactly the argument that drove the team switch from
   names to ids (commit `8758f9e`). The risk with (a): crypto spells a
   name differently from Optic and the prop silently fails to merge.
   Note (b) is **new plumbing, not just another submap**: teams resolve
   via the `crypto_id` key in `load_aliases`, but players today resolve
   by *normalised name* (`normalize_player_name` + an optional
   `player_aliases.toml` consumed through `simple_alias_map`). A
   `crypto_player_id` map means adding an **id-keyed player path** (a new
   valid key, or a dedicated id→canonical file) — distinct from how
   Kalshi/PX/Optic players resolve. Budget for that, it isn't free.

   *Possible aid (not committed to yet):* Optic's `/v3/players` endpoint
   returns the full canonical roster per league (Optic player id, name,
   team, sportradar id). That wouldn't change the merge key — Kalshi/PX/
   crypto don't speak Optic or sportradar ids (crypto's feed carries no
   sportradar ids; checked the SecurityList capture) — but it would let
   us build the alias map semi-automatically: fuzzy-match crypto
   `PARTICIPANT` names against the roster *offline*, human-review, emit
   the TOML. Also enables a pre-flight lint (flag names that won't merge
   before game day) and same-normalised-name collision detection.
2. **Not every prop contract_type has a clean canonical target.**
   `Total Rebounds` → `PLAYER_REBOUNDS` is clean. `First Field Goal
   Scorer` (a Yes/No first-scorer market, `OUTCOME_TYPE = Yes`) has **no
   obvious existing `MarketType`** — map the ones with a target, and
   raise/skip the rest, the same discipline as unmapped game lines.
3. **Period gate differs.** Props use `"Full-Game"` (hyphen); game lines
   use `"Full Game"` (space). The prop gate is a *separate* feed-defined
   constant — do **not** reuse the game-line `period_type`. (This is
   gotcha #10 biting for real, on props rather than game lines.)
4. **Coverage is thin and historical — for NBA.** Only 8 NBA prop
   contracts in 7 days, 2 types (`Total Rebounds`, `First Field Goal
   Scorer`), `EVENT_DATE`s late-Feb backfill — no evidence NBA props flow
   for upcoming games at tradeable volume. **Updated 2026-06-09: soccer
   is different — the data is live.** The 2026-06-08 catalogue burst
   carried **~60 FIFA Player-Prop contracts across 17 types** (`1+ Shots
   on Target`, `Anytime Goal Scorer`, `To Receive A Red Card`, `5+
   Saves`, …) on *upcoming* World Cup fixtures, 100% with
   `external_game_id`/`PLAYER_ID`. So for soccer the "no upcoming
   evidence" caveat no longer holds (see "Soccer props look different").
   The upstream `SecurityListRequest` / bursty-catalogue dependency still
   applies — same as game lines.
5. **Novelty.** Like all crypto rows, props are novel (no Optic
   `source_ids`) and only useful if Optic/PX/Kalshi carry the matching
   player prop to price against.

### Sequencing (2026-06-09): soccer is where the live data is

This plan was written NBA-first, before the World Cup work.  Two things
have changed and a cold agent should weigh them before starting:

- **The scaffolding now exists for soccer.** `mappers/leagues/world_cup.py`
  has a `CRYPTO` config (3-way moneyline shipped), so the prop fields in
  step 3 hang off the *existing* `world_cup.py CRYPTO` (or `nba.py
  CRYPTO`), and the player-alias file would be
  `config/world_cup/player_aliases.toml` — which already stands ready
  (`load_aliases` treats a missing file as empty; the WC goalscorer work
  established this path).
- **Soccer has live prop data; NBA does not** (blocker 4).  But the
  shapes differ: **NBA props are the easier shape** (Over/Under stat
  lines, a flat `contract_type → MarketType` map), while **soccer props
  are where the flow is but harder** — threshold Yes/No with the line
  baked into the `contract_type` string, plus blank `outcome_type` on
  `First Goalscorer` (see "Soccer props look different").

The steps below are written NBA-first; for soccer, swap the league
module and add threshold-string parsing to the vocabulary step.

### Implementation plan (small commits, pipeline green at each step)

1. **Stop dropping props on read.** `to_selection_record` lives in
   `mappers/exchanges/crypto_com.py` (the mapper's read path — **not**
   the fetcher, which writes the full unfiltered catalogue since the
   2026-06-05 format change), and returns `None` for everything but
   `Game Line`. Widen it to also pass `Player Prop`, carrying the player
   fields (`PLAYER_ID`, `PARTICIPANT`, `TEAM_ID`) into the input record.
   Keep futures, blank specials and `Tournament Prop` dropped (no game id).
2. **Extend the `Selection` model** with optional player fields
   (`player_id`, `participant`, `team_id`), populated only for props.
3. **Prop vocabulary on `CryptoConfig`.** Add a `prop_contract_types`
   map (crypto `contract_type` → `MarketType`) and a `prop_period_type`
   (`"Full-Game"`) constant, kept separate from the game-line `period_type`.
   Seed from the feed (`Total Rebounds` → `PLAYER_REBOUNDS`), not the
   catalogue — same data-driven discipline as the game-line config.
4. **Player-id alias map.** A `crypto_player_id` submap (or
   `config/nba/player_aliases.toml`) — confirm ids from the live feed,
   comment each entry with the player name, exactly as the team-id map
   was built. This is where most of the effort lives. (Optionally
   seeded from the Optic `/v3/players` roster — see the note under
   blocker 1; not committed to yet.)
5. **`build_rows` prop branch.** When `market_group == "Player Prop"`:
   gate on `prop_period_type`, map `contract_type` → `MarketType`,
   resolve the player from `player_id` via the alias map, set `entity` =
   canonical player name, and dispatch the side on the prop's shape
   (Over/Under for stat lines; Yes/No for scorer markets). Reuse the
   identity discipline — resolve crypto's own player, never a position.
6. **Fixture + tests.** Add a real prop to the integration fixture
   (a `Total Rebounds` for NBA, or a `1+ Shots on Target` for soccer);
   assert it maps to the right `PLAYER_*` row with the right
   `entity`/`line`/`side`. Re-run the `--json` checksum over a small
   subset (`mappers/CLAUDE.md`).

**No loader change needed.** Once a prop maps, `BigQuery.load_mappings`
`flatten_rows` already emits it as a `sportsbook="crypto.com"` row with
`entity` carried in the MERGE key — the crypto load is built (see
"BigQuery load + the ad-hoc loading decision"). So props reach
`market_mapping` for free; the work is all in the mapper + alias map.

**Decide first (Greg):** (a) player-entity resolution by normalised name
vs a `crypto_player_id` alias map (recommend the id map, per the team-id
precedent — but note it is new id-keyed plumbing, blocker 1); (b) whether
to seed only the prop types with a clean canonical target and skip the
rest, or hold props until coverage thickens; (c) **NBA-first** (easier
Over/Under shape, but only historical data) vs **soccer-first** (live
data on `world_cup.py`, but threshold-Yes/No parsing) — see the
sequencing note above.

### Soccer props look different (2026-06-05, from the SecurityDef dump)

The 43 FIFA records in `data/crypto_com_securitydefs.jsonl` are **all
Player Props** (zero game lines), 100% with `external_game_id`, all
carrying `PLAYER_ID`/`TEAM_ID`/`PARTICIPANT`. Two findings amend the
NBA-derived plan above:

1. **Soccer props are threshold-style Yes/No, not Over/Under.**
   `"1+ Shots"`, `"6+ Shots"`, `"2+ Saves"`, `"To Score 2+ Goals"`,
   `"Anytime Goal Scorer"` — outcome is `Yes` and `PREDICT_VALUE` is
   empty; the line is baked into the `contract_type` string. So the
   prop vocabulary map can't be a flat `contract_type → MarketType`
   for soccer — the threshold needs parsing out of the string (or one
   map entry per threshold). `First Goalscorer` has a **blank**
   outcome_type (NBA's First Field Goal Scorer was `Yes`).
2. **The soccer prop period gate is `"90 Minutes and Stoppage Time"`
   — same as soccer game lines.** The NBA "props use `Full-Game`
   (hyphen) vs game lines' `Full Game` (space)" gotcha does not
   generalise. The per-league feed-defined-constant discipline holds;
   keep the prop gate a separate constant anyway, they just happen to
   coincide for soccer.

## BUILT (2026-06-19): BTTS (Both Teams To Score) — Game Prop group

Shipped on branch `test`. crypto.com's `Game Prop` market group is now
a third mappable group alongside Game Line and Player Prop, with soccer
**Both Teams To Score** as its first (and so far only) type.

What was built — four small edits, no new resolution layer:

- **`to_selection_record`** (`mappers/exchanges/crypto_com.py`): the
  read gate now passes `"Game Prop"` alongside `Game Line` / `Player
  Prop`. A BTTS record (no player, blank `PREDICT_VALUE`,
  `external_game_id` 100% present) parses unchanged.
- **`_resolve_side`**: a `Shape.YES_NO` branch — `Yes → "yes"`,
  `No → "no"` (the literals Optic and Kalshi emit). crypto lists only
  the Yes side; `No` is handled defensively.
- **`_game_prop_row` + a `GAME_PROP` branch in `build_rows`**: game
  props are game-scoped like game lines (fixture resolved by event id)
  but carry no team side — the row keys `entity=None, line=None,
  side=yes/no`. Unmapped game-prop types are **skipped, not raised**
  (the player-prop discipline — the group is a chosen subset crypto may
  extend — *not* the game-line raise).
- **Config** (`mappers/leagues/world_cup.py`): `CryptoConfig` gained
  `game_prop_contract_types={"Both Teams To Score": MarketType.BTTS}`
  and `game_prop_period_type="90 Minutes and Stoppage Time"`, kept
  separate from the game-line / prop maps by the per-group discipline.

The canonical target (`MarketType.BTTS`), the Optic
`both_teams_to_score` and Kalshi `KXWCBTTS` mappings, and the
`"yes"`/`"no"` merge literal all already existed and were join-verified
(144/144, 2026-06-07) — so no loader change and nothing to add on the
other two books. `dedupe_superseded` needed no change (its key already
covers `market_group`/`contract_type`/`period`/`outcome_type`).

Feed facts confirmed against the 2026-06-18 burst
(`/tmp/crypto_0618_1539.jsonl`, copied off the test VM): **48 FIFA BTTS
contracts**, all `Game Prop` / outcome `Yes` only / blank value / period
`"90 Minutes and Stoppage Time"` (same gate as soccer game lines) / 100%
`external_game_id`. No first-half BTTS in the feed — crypto has full-game
BTTS only, so Optic/Kalshi's `FIRST_HALF_BTTS` gets no crypto counterpart.

Verified end to end on that burst (Optic+Kalshi from
`data/2026-06-18/05_55`): **16 crypto BTTS rows, all 16 merged onto
Optic+Kalshi, 0 novel, side `yes`** (16 games overlap the Optic horizon;
the Yes side lands on the 16 Optic *yes* rows, the *no* rows stay
their-side-only — the over-only `player_goals` pattern). Stash-and-rerun
`--json` diff over the same burst: same row count, **exactly 16 rows
changed (all `btts`, gaining a crypto block), 0 added/removed** — nothing
else in WC output moved, and non-WC leagues are unaffected (the new
branch is gated on `game_prop_*` config only `world_cup` sets).
`mise test` 283 pass (4 new BTTS tests), pyright clean on touched files.

The cold-agent brief that drove this follows, kept for the reasoning.

## Next (was): add BTTS (Both Teams To Score) — Game Prop group (2026-06-19)

Found by the RFQ-coverage audit below. BTTS is the one game-scoped
market our bucketing never accounted for: every earlier section sorts
crypto markets into **Game Line** (mappable), **Player Prop** (mappable,
in progress), or gameless **futures/specials** (out of scope). BTTS is
none of these — `PREDICT_MARKET_TYPE = "Game Prop"`, a fourth group —
and it slipped through because no game-line and no player-prop key
matches it, so the pipeline silently produces nothing for it. The audit
blob has 39 `Both Teams To Score` contracts, **100% with
`external_game_id`**, outcome `Yes` only (a Yes/No game-level question,
not Over/Under, not per-player). So it is genuinely mappable and small.

Why it's the cheapest gap left (do it before the long tail of player
props): one contract_type, one outcome, game-scoped (no player-entity
resolution — the hard part of props, blocker 1, does not apply), and
Optic and Kalshi both quote BTTS for the World Cup, so rows should
**merge, not strand novel**. The whole job is a new market group, not a
new resolution layer.

Plan for a cold agent (small commits, pipeline green at each step):

1. **Canonical target.** Check `mappers/market_types.py` for an existing
   BTTS `MarketType` (the other exchanges' soccer coverage may already
   have one — grep Optic/Kalshi configs). If none exists, add it. BTTS
   is a binary Yes/No at the **game** scope (`Scope` is game, not
   player) — model it like the other team/game Yes/No markets, not like
   a player prop.
2. **Confirm the merge target is live.** Before building, verify Optic's
   WC feed and Kalshi's WC series actually quote BTTS and find the
   canonical side literal they use for Yes/No (the way `_TIE` was
   confirmed for the 3-way draw — see "Feed revival"). If neither book
   quotes it, BTTS rows are novel and only load if they merge (the
   Optic-base load constraint, "BigQuery load" section) — so this gates
   the whole step.
3. **A `Game Prop` path in the mapper** (`mappers/exchanges/
   crypto_com.py`). `Game Prop` is a new `market_group` value alongside
   `Game Line` / `Player Prop` in `build_rows`. It is **game-scoped with
   no team side** (like a player prop minus the player): resolve the
   fixture by `EXTERNAL_HOME_ID`/`AWAY_ID` as usual, but the row has no
   `entity` and no team — just the game + market_type + side. Map
   outcome `Yes` → the canonical Yes/No side. Confirm the period gate
   (expect `"90 Minutes and Stoppage Time"`, same as soccer game lines —
   verify in the feed, don't assume).
4. **Config** (`mappers/leagues/world_cup.py`). Add a `game_prop_*`
   vocabulary map to `CryptoConfig` — `{"Both Teams To Score": <BTTS
   MarketType>}` — kept separate from `contract_types` (game lines) and
   `prop_contract_types` (player props), with its own period constant,
   per the per-group-constant discipline. **Discipline question to
   settle with Greg:** game lines *raise* on an unmapped type, props
   *skip*. For a brand-new `Game Prop` group where we map only BTTS and
   crypto may offer other game props later, **skip** is the safer
   default (mirror the prop rule) — confirm before building.
5. **Fixture + tests.** Add a real BTTS selection to a WC integration
   fixture; assert it maps to the BTTS row with the right side and
   merges onto Optic/Kalshi. Re-run the `--json` checksum over a small
   subset (`mappers/CLAUDE.md`).

No loader change needed — `flatten_rows` already emits any merged crypto
row (see "BigQuery load"); a game-scoped row with no `entity` loads the
same as a game line.

## Replicating the RFQ-coverage audit (2026-06-19)

The method that surfaced the BTTS gap and ranked the unmapped FIFA
demand. Use it to re-check coverage after any new burst, or for a new
sport. The question it answers: **of the symbols punters actually ask us
to quote (RFQ legs), which do we map, and which don't we — weighted by
how often they're requested.**

**Step 1 — RFQ-weighted coverage, straight from BQ.** Join the distinct
leg symbols in incoming `QuoteRequest`s against loaded `market_mapping`
rows, both sides normalised by stripping the trailing `.YYYYMMDD`
maturity suffix (legs and catalogue symbols both appear in two vintaged
forms — see combos caveat 3). This is the query at the top of this
investigation; it groups by `league × mapped? × market_type`. The
telltale of a gap is a row with `mapped=false` and a large
`total_requests`. On the 2026-06-19 run FIFA showed **2,026 unmapped
distinct symbols / 260k requests** against the mapped buckets
(moneyline_3way, game_total, player_goals, point_spread).

Note the symbol suffix is `…-M.O.<market#>.<outcome#>.<maturity>` —
**numeric ids, not the contract-type string** — so the symbol alone
won't tell you *what* an unmapped leg is. That's what step 2 is for.

**Step 2 — name the unmapped types from a local catalogue blob.** The
RFQ leg symbols don't self-describe, but the catalogue does. Fetch a
wide window once and profile it offline (the "fetch once, view forever"
principle — "one full on-disk format"):

    .venv/bin/python -m fetch.crypto_com --hours 24 --out scratch/crypto_com_24h.jsonl

Then break the league down by market group × contract type, deduped by
contract, with `jq`. The blob is the flat full record; the fields are
`eventMetaLEAGUE` / `eventMetaPREDICT_MARKET_TYPE` (the group:
Game Line / Player Prop / Game Prop / Team Future / …) /
`eventMetaPREDICT_CONTRACT_TYPE` / `eventMetaPREDICT_OUTCOME_TYPE`:

    jq -r 'select(.eventMetaLEAGUE=="FIFA")
      | [.Symbol, (.eventMetaPREDICT_MARKET_TYPE//"BLANK"),
         (.eventMetaPREDICT_CONTRACT_TYPE//"BLANK"),
         (.eventMetaPREDICT_OUTCOME_TYPE//"BLANK")] | @tsv' \
      scratch/crypto_com_24h.jsonl \
      | sort -u | awk -F'\t' '{print $2" || "$3" || "$4}' \
      | sort | uniq -c | sort -rn

Read the result against what the mapper builds: anything not under a
mapped `contract_type` (game lines) or `prop_contract_types` (props) is
unmapped. **Always check `external_game_id` fill before calling
something a gap** — a high count with `NO_GAME_ID` is a gameless
future/special and correctly out of scope (Team Future, Player Future,
Tournament Prop all came back `NO_GAME_ID`); a high count *with* a game
id is a real mappable gap (this is exactly how BTTS was caught):

    jq -r 'select(.eventMetaLEAGUE=="FIFA"
                  and .eventMetaPREDICT_MARKET_TYPE=="Game Prop")
      | (.eventMetaEXTERNAL_GAME_ID // "NO_GAME_ID")' \
      scratch/crypto_com_24h.jsonl \
      | awk '{print ($0=="NO_GAME_ID")?"no_game_id":"has_game_id"}' \
      | sort | uniq -c

**What the 2026-06-19 audit concluded.** The unmapped FIFA demand is
overwhelmingly **the rest of the player props** (next-step 3 above) —
~20 unmapped prop contract types, each 480–840 contracts: the
`To Score N+ Goals` family, `First Goalscorer` (570, blank outcome), the
Shots / Shots-on-Target ladders, Fouls, Assists, Cards, Saves. Plus two
small game lines: `Moneyline (2-Way)` draw-no-bet (deliberately ignored,
`game_line_ignored`) and the new **BTTS** gap (39, game-scoped — see
"Next: add BTTS"). Everything else with high counts was gameless and
correctly out of scope. The per-type RFQ *request* ranking (which
omission costs the most pricing opportunity) needs a further BQ join of
unmapped leg symbols → catalogue `symbol→contract_type`; not yet run,
but the catalogue counts make the qualitative ranking clear (props
dominate, BTTS and 2-way are tiny by contract count).

## In-season validation checklist (off-season best-guess leagues)

NFL, NHL, NCAAB, and EPL were enabled from vendor dictionary / sparse
historical data before their 2026–27 game-line catalogues appeared in
`processed_upstream_us`.  At each season start:

1. **Profile the live feed** — `python -m fetch.crypto_com --hours 96
   --out scratch/crypto_<league>.jsonl` then
   `python scripts/scan_crypto_com.py scratch/crypto_<league>.jsonl`.
2. **Confirm `period_type`** — compare distinct `PREDICT_PERIOD_TYPE`
   values against `CryptoConfig.period_type` / `contract_period_types`
   from the sport's builder (`mappers/vocab/<sport>_markets.py`, or
   `mappers/exchanges/crypto_soccer.py` / `crypto_tennis.py` /
   `crypto_esports.py`).  The
   mapper normalizes hyphen vs space (`Full-Game` vs `Full Game`) at the
   period gate. A new period string is skipped for that leg and stays an
   RFQ gap until you add it in code.
3. **Confirm game-line `contract_type` strings** — novel types are
   skipped during map runs and stay RFQ gaps; add them to the builder's
   `contract_types` or `game_line_ignored` in that builder.
4. **Team `crypto_id`s** — add evidenced ids to `CRYPTO_TEAM_IDS` in
   `mappers/vocab/crypto_team_ids.py` (id evidence only, no name matching)
   with a case in `tests/mappers/test_crypto_team_ids.py`. No tip
   `crypto_id` pins.
5. **Ship** — run `GCP_PROJECT=rs-marketmaking .venv/bin/pytest -q`, open
   the MR and read the `regression:mapping-gate` row delta. Removed rows
   need a waiver in `regression/waivers.toml`.
6. **Classify a leftover by hand** — `python scripts/print_crypto_gap_sql.py
   --league <league>`. Each leftover is a code change (steps 2-4), not a
   gap-propose card.
