# AI validation of the exchange mappings

`BigQuery/ai_validation.py` asks Gemini whether each row we publish to
`markets_us.market_mapping` really means what we claim: does the Kalshi ticker /
Polymarket token / crypto.com symbol / Novig outcome we mapped carry the same
contract as our canonical bet? Verdicts land in
`markets_us.market_mapping_ai_validation`.

It exists because the deterministic checks can't see this class of error:

| Check | Catches |
|---|---|
| `verify_source_ids` (`mappers/exchanges/optic.py`) | our match disagrees with Optic's own `source_ids` — only where Optic maps the exchange at all |
| `gap-propose` (legacy) | RFQ legs we failed to map (coverage). Its console Review cards are retired; treat its output as a list of code changes |
| **this job** | a mapping that is structurally valid and semantically wrong: right fixture, wrong side / line / period / player |

Ported from `mm-huddle/mapping/ai_validation.py`; the Kalshi ticker-grammar rules
in the prompt are that repo's, verbatim.

## Running it

```bash
mise run ai-validate -- --dry-run          # runs the SQL, prints counts + first prompt, no spend
mise run ai-validate -- --max-rows 50      # cap a live run
mise run ai-validate -- --sportsbook Kalshi
mise run ai-validate -- --print-sql        # rendered input SQL, nothing else
```

In production it is a GKE CronJob (`deploy/k8s/ai-validation`, own image
`deploy/ai-validation.Dockerfile`, own build/deploy CI jobs), every 2 hours at :17,
running as the `mapping-control-plane` KSA in the `mapping-console` namespace with
`concurrencyPolicy: Forbid`. The Gemini key is read through the Secret Manager
client (the image has no gcloud). The GSA's write access to the verdict and stage
tables is `mm-infrastructure` `modules/mapping_control_plane/ai_validation_iam.tf`.
Only the GKE CronJob `ai-validation` (17 */2) runs it; the VM crontab no longer has a
copy (removed so the two never overlap). The job is
deliberately **not** inside `run_pipeline.sh`: it must never delay or fail a
15-minute mapping tick.
`AI_MAX_ROWS` in the environment caps a run when draining a backlog in slices.

## The never-revisit contract

Each mapping is judged **once ever**. `row_fingerprint` = SHA256 over
`load_mappings.KEY_COLUMNS` (the table's own uniqueness key) **plus** `source_ids`,
and the input SQL left-joins the verdict table on
`(row_fingerprint, prompt_version)` and keeps only unmatched rows — so a judged
mapping never leaves BigQuery, let alone reaches the model. Consequences:

- the same row republished every 15 minutes costs nothing;
- a canonical bet **re-mapped to a different ticker/token/symbol** hashes
  differently and *is* re-judged, which is the point;
- `--revalidate` re-judges the window once, without changing the stored contract.

`_fingerprint_expr()` is derived from `KEY_COLUMNS`, so adding a key column to
`market_mapping` automatically extends the hash. A test asserts that (if it ever
fails, the never-revisit contract is broken, not the test).

### Bumping `PROMPT_VERSION`

Bump the int in `BigQuery/ai_validation.py` whenever you change the prompt or the
verdict semantics — verdicts produced by different rules are not comparable, and
the anti-join would otherwise keep the old ones forever. A bump re-judges
everything in the window, so bump deliberately and add a one-line changelog
comment above the constant.

## Where the spend goes

Levers, biggest first:

1. **the anti-join** — steady state is only mappings that appeared since the last run;
2. **the corroboration skip** — if Optic's own `prices_dedup_state` maps the same
   selection to the same exchange id we did, the row is double-sourced and the
   model adds nothing. `--include-corroborated` overrides. This also drops the
   Polymarket *passthrough* rows (`source_ids` copied from Optic, not matched by
   us). crypto.com is never corroborated by design — our symbol is decoded from
   Optic's `market_id`, so Optic is not an independent witness;
3. **four sportsbooks only** — Kalshi, Polymarket, crypto.com, Novig. Prophet X /
   SX Bet / Runshop are out of scope. Novig is corroboration-eligible like
   Polymarket: most rows are Optic's own `source_ids` passed straight through
   (`mappers/exchanges/optic.py` `OPTIC_MAPPED_SPORTSBOOKS`), and only the
   constructed (id-joined) rows Optic never mapped itself get a model call;
4. **batching** — 25 rows per call, one line per row, and batches partitioned by
   sportsbook so a call only carries that exchange's rule block.

`--dry-run` reports the row count per sportsbook, which is the number to look at
before a first live run in a new window.

Runs against `marketmaking-test` for the upcoming window (`today → +14d`) settle
around **3,700–3,900 rows judged** (Kalshi ~300–410, Polymarket ~2,850,
crypto.com ~610) with a flag count in the **single digits, sometimes zero** — see
the intermittency note below before reading any single number as the truth.

The release run (2026-08-03, prompt v1) via the cron wrapper over the default
`yesterday → +14d` window: **11,606 judged — 19 flagged** (0.16%) — Kalshi 4,924,
Polymarket 5,942, crypto.com 740. Panel 1 (upcoming fixtures only) was **empty**:
every flag sat on a fixture that had already started. Of the 19: **4 are a real
wrong-player cross-wire** (below), 8 the intermittent crypto/Kalshi spread class,
7 the Kalshi player-prop team-prefix false positive.

A near-zero flag count is only meaningful alongside a **negative control**, which
unit tests cannot provide because it costs tokens: inject a swapped fixture, a
flipped yes/no side, and a threshold moved three whole steps into real rows and
confirm all three are still caught while the untouched control passes. It has
passed at every stage, including after the prompt had material *removed* from it —
re-run it after any change that removes material, or you cannot tell a clean queue
from a blind judge.

Measured on `marketmaking-test`, 2026-08-03, window `-1d → +14d` (a cold table, so
this is the **first-fill** backlog, not steady state):

| | candidates | judgeable | calls @25 |
|---|---|---|---|
| default | 12,806 | 11,479 (Kalshi 4,806 · Poly 5,933 · crypto 740) | 461 |
| `--include-corroborated` | 17,564 | 15,945 | 640 |

So the corroboration skip removes ~27% up front, and the anti-join removes
essentially everything on the second run onwards — steady state is just the
mappings that appeared since the last one. Drain a cold start in slices with
`AI_MAX_ROWS` / `--max-rows` rather than in one 461-call run.

Dashboard queries over the verdicts: `docs/ai-validation-grafana.md`.
Published coverage by platform/league (plus configured-vs-published gaps):
`docs/mapping-coverage-grafana.md`.

## Mid-run visibility (and the trap it used to set)

`partition_chunks` keeps every batch single-sportsbook (one rule block per call)
but **interleaves** the batches round-robin, so the three exchanges advance
together. Verdicts MERGE in flushes of `AI_FLUSH_EVERY` (500) plus a final flush
at exit, so the last few hundred verdicts of any run only appear once the process
exits. Track a live run by `judged N/M batches` in the log, not by the table.

This used to be grouped by exchange, which starved the smallest book: crypto.com
was always the last ~25 of 152 batches, so for the entire duration of a re-judge
it held **no rows at the current `prompt_version`** and disappeared from every
version-filtered dashboard panel — indistinguishable from a broken mapping, and
it was reported as one. Interleaving removes the pathology; the flush caveat
remains but now costs at most a few hundred rows of any exchange.

Related: because the MERGE key is `row_fingerprint` alone, a re-judge **updates
rows in place** and `prompt_version` moves forward per row. Panels pin
`prompt_version`, so mid-run a panel shows only the already-rejudged slice. That
is correct and drains as the run proceeds — but do not read it as missing data.

## False-positive classes already fixed (and why they mattered)

### 1. Dates — three failed attempts, then deletion

This one class cost four rounds of pre-release iteration and is the most useful
thing in this document.

- **Round 1**: our `start_date` is UTC, but **Kalshi tickers and Polymarket slugs embed
  the US-Eastern date**, so an evening ET game is the next UTC day
  (`2026-08-02T00:00Z` ↔ ticker `...-26AUG01...`). The first live run flagged
  **100% of Kalshi and Polymarket rows** with `reason: "date mismatch"`.
- **Round 2**: added `DATE(start_date, 'America/New_York') AS et_date` to the prompt line
  and told the judge to compare against `et`, plus "a date alone never fails
  `fixture_ok`". The 100% class went away; **126** tennis and LoL rows then flagged
  on the Polymarket slug date, which is set by *local tournament day* and matches
  neither `date` nor `et`.
- **Round 3**: `strip_slug_date()` removed the slug's date. Polymarket went quiet;
  **10** Kalshi tennis rows then flagged because a Round-of-128 ticker dated
  `26AUG01` legitimately belongs to a match played on the 3rd.
- **Round 4**: gave up on instructing and removed the field. `mask_exchange_dates()`
  blanks the date inside Kalshi tickers and crypto.com symbols, the `OURS` line
  carries no date at all, and the prompt states there is nothing to compare.
  Result: **0 date flags**.

The judge ignored an explicit, emphatic instruction three times. **When a field
cannot be adjudicated, delete it from the prompt — do not ask the model to
discount it.**

That deletion is principled, not just expedient: the exchange's date is the key
the *matcher* used to find the fixture (Kalshi game suffix → Optic fixture via
`game_et_dates`), so re-checking it downstream is circular. `et_date` is still
selected into the verdict table for human triage.

If a whole league starts flagging `fixture_ok=false` at once, suspect a convention
like this one before you suspect the matcher.

### 2. Correct score is winner-anchored, exchanges write home–away

`mappers/shared.py:correct_score_line` packs `winner_goals + loser_goals/100`, and
`side` names the **winner** (`_TIE` for a draw) — our `sl='2:1'` means *the side
scored 2, the opponent 1*, **not** home 2 away 1. Polymarket writes the same
contract in fixture order: `Exact Score: Central Cordoba 1 - 2 San Lorenzo?`.
Compared positionally that reads as a contradiction, and the first run flagged 12
Argentine correct-score rows on exactly that. The prompt now states the anchoring
and tells the judge to reorder around the winner before comparing.

Worth knowing: `polymarket.py`'s `EXACT_SCORE` branch resolves the question's
`team_a`/`team_b` to home/away **by name match**, never by question order — so the
question's order genuinely carries no side information.

### 3. A missing fixture name became a "date mismatch"

55 tennis rows were flagged `fixture_ok=false` with `reason: fixture date
mismatch`. The real cause was upstream of the model: the `fx` CTE filtered
`opticodds_fixtures` by the *same* window as the mapping rows, so a fixture whose
Optic `start_date` had drifted (reschedule, or a kickoff either side of the
boundary) joined to NULL — and `CONCAT()` with one NULL argument returns NULL, not
a partial string. The prompt line then read `ev=''` with only `(YPU6 v ZHA)` to go
on, and the judge fell back to the slug date.

Two fixes: `FIXTURE_PAD_DAYS = 3` of slack on the fixture lookup, `IFNULL` around
each display name — and, because it should never have been fatal anyway, a prompt
rule that **a date alone never fails `fixture_ok`** and that an empty `ev` means
match the short codes as prefixes rather than assume a wrong mapping.

### 4. A Kalshi title describes the YES side

Nine NFL spread rows flagged `side_ok=false`: ours `side=CAR pts=+4.5`, Kalshi
`KXNFLSPREAD-...-ARI5` with **`s=no`** and title *"Arizona wins by over 4.5
points"*. `s=no` is the complement of the title, so Arizona-not-winning-by-4.5+ **is**
Carolina +4.5 — a correct underdog mapping. The model read the team name in the
title and stopped there. The ticker-grammar rules alone weren't enough; the prompt
now states outright that the title always describes the YES side and must be
negated before comparing, with this exact case as the worked example.

### 5. Polymarket slug dates are local tournament days

126 tennis and LoL rows flagged `fixture_ok=false` / `reason: date mismatch` even
after fix 3 gave them proper fixture names — the participants matched *exactly*
(`Emerson Jones v Lanlana Tararudee` vs `Emerson Jones vs. Lanlana Tararudee`).
The trigger was the slug's trailing date, which Polymarket sets by local
tournament day and which therefore agrees with neither our UTC date nor `et`.

Two rounds of prompt hedging did not stop the model reaching for it, so the input
changed instead: `strip_slug_date()` removes the trailing ISO date, and the
Polymarket rules say plainly that no date is shown and none can be judged. When a
field is unjudgeable, remove it rather than asking the model to ignore it.

### The all-in verdict is now derived, not trusted

51 rows came back with `mapping_ok=false` while **every** component verdict passed
— an all-in failure naming no contradiction (the `reason` was always a date we had
already ruled out). `fixture / market / side / line` (+ `entity` on props) are
exhaustive over what a mapping can get wrong, so `derive_mapping_ok()` now computes
`mapping_ok` from them and the model's own all-in answer is discarded; a
disagreement is logged per batch. The model's prose still reaches the reviewer via
`reason`. This makes Panel 1 coherent by construction: nothing appears there
without a named failing component.

### 6. crypto.com writes its own spread signs

One UCL row flagged `side/line`: ours `side=LEV line=+5.5` against
`"PFK Levski Sofia 5.5 to win"`, read by the model as "wins by 5.5" (i.e. −5.5).
It is not. crypto.com puts the sign in the text and lists **both** sides of a
spread — `"Olympique Lyonnais -8.5 to win"` (favourite → our line `-8.5`) and, on
the same game, `"SK Slovan Bratislava 8.5 to win"` (underdog receiving → `+8.5`).
`crypto_com.py` takes `line = sel.value` verbatim from the feed, so our sign
agrees with theirs by construction; a **missing** minus means the plus side.

Worth noting how this one resolved: it was the only flag that looked like a real
find, and checking the sibling rows in `market_mapping` (both signed sides present
and correctly paired) is what settled it. It also failed to reproduce on the next
run — a borderline row that run-to-run variance moves. Verify a lone flag against
neighbouring rows before believing it.

### 7. `grp` is a pairing key the judge read as the line (`PROMPT_VERSION` 2)

The first **production** run flagged 3 crypto.com MLB `run_line` rows — the
KAN v MIN alternate ladder — with `side_ok=false` and
`reason: "Side mismatch: OURS is -4.5, EXCHANGE is +4.5"`. All three were
correct. The raw row for symbol `...O.1.5...` is `line=+4.5`, `points=+4.5`,
market_id `SPDTwins4P5` (crypto's own encoding: no `N` prefix = the plus side;
the minus rungs are `SPDTwinsN4P5`), against
`"Minnesota Twins 4.5 to win"` = +4.5. Ours and theirs agreed.

The only `-4.5` anywhere in that row was **`grouping_key`**. `_ours_line`
renders it as `grp=`, and on spread/handicap rows its number is routinely the
mirror of `line`:

```
line=-5.5 -> grp='default:5.5'     (SPDTwinsN5P5, the minus rungs)
line=+5.5 -> grp='default:-5.5'    (SPDTwins5P5,  the plus rungs)
```

v1 documented `grp` **only** under `entity_ok`, as a carrier for the player
name, so the judge had an unexplained signed number contradicting `line` and
resolved the contradiction the wrong way. This is not one bad fixture: 1,660
rows in a single prod window carry an inverted `grp`, concentrated exactly where
signed lines live — `point_spread` and `set_handicap`, across every book (Kalshi
296, Polymarket `set_handicap` 251, crypto.com 247, Polymarket (USA) 224, SX Bet
199, Prophet X 126, Novig 92).

v2 states in the shared core rules that `grp` is a pairing key, that its sign is
routinely inverted, that side and threshold come from `pts`/`line`/`sl` only, and
that a conflicting sign appearing **only** in `grp` is not a contradiction.

Note this fix adds prompt text where "the general lesson" below prefers
correcting or removing the input — dropping the numeric `grp` from `_ours_line`
(it duplicates `pts`/`line`; non-`default:` keys carry the player name and would
be kept) is the alternative, and remains open. It was left in place
deliberately: `grouping_key` is load-bearing elsewhere and was not to be
disturbed by this hotfix.

This class is very likely a contributing cause of the intermittent spread
polarity documented below — `grp` was in every one of those prompts too.

## Novig: the judge now sees the typed market type and strike

The 2026-10-13 flags on Novig tennis were the judge guessing from free text: a
`SET_SPREAD` of +-1.5 read as a game spread, and `t2.5` in a market description read
as 22.5. Novig types both (`type`, `strike`, and the outcome's `Home/Away/Over/Under`),
so `novig_raw` now feeds them into the prompt line (`type=SET_SPREAD strike=1.5
outcome=Home`) and the Novig rules call them authoritative over text.

No `PROMPT_VERSION` bump: that would re-judge ~27k Novig rows to fix a handful of
false positives. The typed fields apply to every newly judged row; to clear an old
false positive, delete its verdict row and the next run re-judges it.

## False positive: Megan Gustafson ↔ Megan DiLeo (married name)

The first full-window run flagged four Polymarket WNBA player props as
`entity_ok=false`:

```
OURS entity='megan_gustafson' line=15.5 (player_points)  -> POLY 'Megan DiLeo: Points O/U 15.5'
OURS entity='megan_gustafson' line=4.5  (player_rebounds) -> POLY 'Megan DiLeo: Rebounds O/U 4.5'
```

**Same player.** Megan Gustafson married in Jul 2026 and plays as Megan DiLeo
(Portland Fire / ESPN / Polymarket). Optic (and Novig) still use Gustafson.
Polymarket's bridge has only DiLeo markets — there is no second player with a
competing ladder. The mapping is correct; the judge fails on the string mismatch.

Fix shipped as a code alias (not a `PROMPT_VERSION` bump): `megan_dileo` →
`megan_gustafson` in `BASKETBALL_POLY_TEAM_NAME_ALIASES`
(`mappers/vocab/basketball_markets.py`), which poly player-prop entities
resolve through. (The original `config/wnba/player_aliases.toml` copy is gone.)

Existing AI verdict rows stay until a revalidate (or a future prompt rule that
treats married/maiden variants as the same entity). Repro: the four rows above
on fixture `26563-27428-2026-08-06`.

## KNOWN LIMITATION: Kalshi player-prop team prefixes false-flag

Seven Kalshi MLB `player_hits_runs_rbis` rows flagged `entity_ok=false` with
reasons like *"Entity team mismatch: Alan Roden (MIN)"* — while the player names
on both sides are **identical** (`Alan Roden` ↔ `Alan Roden`). The model is
objecting to the `MIN`/`SEA` team prefix inside the Kalshi player code
(`...-MINARODEN18-2`), which our player-prop rows do not carry at all, so it
cannot contradict anything. Identical player names should be `entity_ok=true`
outright.

Unfixed on purpose: the prompt change is one sentence, but it costs a
`PROMPT_VERSION` bump and a full re-judge, so it belongs with the next batch of
rule work rather than on its own.

## KNOWN LIMITATION: spread polarity is intermittent

The judge is unreliable on **spread rows specifically**, and it is not fixed:

| round | spread flags on the same rows |
|---|---|
| 2 | 9 (Kalshi NFL) |
| 3, 4, 5 | 0 |
| 6 | 10 (7 Kalshi, 3 crypto.com) |

Nothing spread-specific changed across rounds 3-5, so **the class comes and goes
with run-to-run variance** (dynamic thinking; `temperature=0` does not make this
deterministic). Two shapes, both false positives:

**Update (`PROMPT_VERSION` 2):** class 7 above is a likely contributing cause of
both shapes. Every one of these prompts also carried a `grp=` whose sign is the
mirror of `line` on exactly these markets, with no rule explaining it — an
unjudgeable input the model could resolve either way, which is what an
intermittent class looks like. Re-measure with the harness before treating the
limitation as still open.

- **Kalshi `s=no`**: ours `side=AGF line=+2.5` against ticker `...-SBH3 s=no`,
  title *"Sabah wins by more than 2.5 goals"*. `s=no` negates it, so the contract
  IS Aarhus +2.5. The model negates the proposition but leaves the `+2.5` with
  Sabah. The first fix ("the title describes the YES side, negate it") was not
  enough — the negation must also **swap which team the handicap belongs to**.
- **crypto.com unsigned**: ours `TOL +0.5` against *"Deportivo Toluca FC 0.5 to
  win"*, read as "wins by 0.5". It isn't — see class 6.

Two consequences for whoever picks this up:

1. **A single run cannot validate a fix here.** A clean run proves nothing while
   the class is intermittent. Use the replay harness:

   ```bash
   GCP_PROJECT=marketmaking-test .venv/bin/python -m scripts.ai_validation_replay \
       --sportsbook Kalshi --market-type point_spread --reps 5
   ```

   It re-judges the same rows N times with production's batching and prints a
   per-row flag rate, so `1/5` reads as noise and `5/5` as a real disagreement.
   Batch composition matters: an oversized single call does **not** reproduce the
   behaviour (a first attempt that put 49 spread rows in one call flagged nothing
   under either the old or the new prompt, which is why the harness mirrors
   production instead).
2. **Don't take these flags at face value on spreads.** Verify against the
   leg's `s=` side and Kalshi's typed `strike_type` / `floor_strike`, or
   crypto's sibling ladder rows, before touching the matcher.

### The general lesson

Six classes in: when a whole league or market type flags the same way, look for a
join, a convention, or an unjudgeable input field **on our side** before touching
the matcher. Every class so far has been ours, not the model's — the component
verdicts have been more reliable than the all-in one, and the most effective fixes
removed or corrected an input rather than adding prompt text.

## Reading the verdicts

```sql
SELECT sportsbook, league, fixture_name, market_type, side, line,
       exchange_ref, exchange_text, reason,
       fixture_ok, market_ok, side_ok, line_ok, entity_ok
FROM markets_us.market_mapping_ai_validation
WHERE NOT mapping_ok
  AND prompt_version = 1
  AND start_date > CURRENT_TIMESTAMP()
ORDER BY start_date
```

A flag means **look at it**, not *definitely wrong* — the prompt is tuned so that
uncertainty resolves to `true` (a false alarm costs more review time than a miss
costs money), but model noise still produces some. `side_ok=false` is a polarity
bug class, `line_ok=false` a threshold one, `market_ok=false` usually a period /
scope mismatch. Cross-check a flagged row with `mappers/eyeball.py` before
touching the matcher.

The job also publishes a grouped rollup to the `application-alerts` Pub/Sub topic
(`BigQuery/alerts.py`) when anything is flagged; `--no-alert` suppresses it.

## Rows the job skips silently

A row with **no exchange-native text** is dropped before batching and logged as a
warning — the model would only be guessing. Causes:

- Kalshi ticker older than the `kalshi_raw` stash window (`infra/cron_kalshi_raw.sh`
  runs every 6h; the SQL looks back 3 days);
- Polymarket token absent from `polymarket_position_token_bridge` (the bridge is
  the matcher's own source, so this normally means a passthrough row);
- crypto.com symbol absent from the FIX catalogue tables.

A large count for one exchange is an upstream-freshness signal, not a mapping
verdict.

## Adding an exchange

Each exchange is one pluggable module in `BigQuery/ai_validation_exchanges/`:

1. Copy a sibling (`kalshi.py`) to `<exchange>.py` and fill in its `SPEC`
   (`ExchangeSpec`, see `base.py`): the CTE(s), the LEFT JOIN(s) into `map m`, the
   columns added to the outer SELECT, the rule-block `prompt`, `corroborated`,
   `lookback_days`, and the `has_text` / `ref` / `side` / `text` / `line` accessors.
2. Add the module's `SPEC` as one line in `_SPECS` in `ai_validation_exchanges/__init__.py`
   (order there is the SQL join order and the order of `SPORTSBOOKS`).
3. Bump `PROMPT_VERSION` only if the new exchange should be judged at once and
   existing verdicts must be re-judged; a new exchange's rows have no verdicts yet.
4. Nothing in `ai_validation.py` changes: `INPUT_SQL`, `SPORTSBOOKS`,
   `CORROBORATED_SPORTSBOOKS`, `EXCHANGE_PROMPTS` and the `exchange_*` dispatchers are
   all derived from the registry. `tests/BigQuery/test_ai_validation_exchanges.py`
   checks every spec is complete and that its CTE and join agree.

## Prerequisites

- `google-genai` (in `requirements.txt`); the import is lazy so only this job needs it.
- Gemini key in Secret Manager as `mm-mapping-bot-gemini-key` (already present in
  `marketmaking-test` and `rs-marketmaking`; the same entry mm-huddle uses). The
  VM's service account needs `secretAccessor` on it. `GOOGLE_API_KEY` in the
  environment wins locally.
- The output table is created idempotently by `ensure_table` on first run; the
  authoritative schema belongs in `mm-infrastructure` Terraform, with the inline
  `SCHEMA` kept in lockstep (same convention as the Polymarket loaders).
