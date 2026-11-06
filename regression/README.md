# Regression harness

Answers one question: *if we swap engine version A for version B,
how do the published mappings change?*  Gates every mapping MR:
refactors must show zero diff; intended changes must have every
removed row explained, or fail.

## Justification

The mapping service decides which markets we can trade: it matches
"the same real-world bet" across Kalshi, ProphetX, crypto.com,
Polymarket and the Optic feed, every 15 minutes, driven by
thousands of small rules.  A wrong mapping means pricing and
trading the wrong contract; a missing one means sitting out
markets we could be making.  Changes to this engine are therefore
high-stakes and, historically, verified by eyeballing — nothing
systematically answered "did this change alter what we publish?"

This harness answers it mechanically.  A replay corpus of
historical fetch ticks plus a versioned projection of "the rows
this engine would publish" lets any two engine versions be run on
identical inputs and set-diffed row by row.  For refactors the
bar is zero diff; for intentional changes every delta must be
matched, waived with a reviewed excuse, or the gate fails.

Mapping rules are code (see `CLAUDE.md`): leagues, vocab, venue
league ids and aliases ship by MR, and this gate is how an MR shows
what it changes.  The BigQuery rule-set tip is legacy that the mapper
still loads while it is removed; the live gate pins it to one exported
file so a delta is always the code's.  Moving a rule off the tip into
code is a change like any other: the gate must show zero diff, or
every delta explained.

History: the harness was first built for the earlier, now retired,
"rules as data" migration (code → BQ snapshots edited through a
console).  Its `config_*` stage compared the old config with the BQ
snapshot rule by rule and caught real transcription defects (dropped
verification provenance; an unverified alias re-labelled
id-verified) — see HISTORY.md.  `plan.md` is from that era.

## The model — three layers

1. **Project** — one versioned rule (`project.py`) reduces any
   engine version's output on a tick to the rows it would publish:
   one line per (9-field bet key × sportsbook stamp), mirroring
   `BigQuery/load_mappings.flatten_rows`.  `VERSION` is baked into
   every saved projection's filename, so a contract change can
   never silently diff against stale files.
2. **Diff** — set-difference two projections (`diff.py`).  Any SHA
   vs any SHA, no setup, no ceremony.  Always available,
   unopinionated.
3. **Gate** — a diff with a distinguished side and a burden of
   proof: candidate vs the blessed baseline (a SHA named in git),
   where every delta is matched, waived, or the gate fails.

Engines run as subprocesses in SHA-pinned worktrees
(`run_engine.sh`); nothing here imports from `mappers/`, so the rig
works against any commit — including engines that don't exist yet.

## Gate policy — three invariants

- **Verdicts are mechanical.**  Field comparison only; no judgment,
  no AI, in the gate.
- **Every excuse is narrow, bounded, dated, attributed, and
  reviewed.**  A waiver is born in the MR it excuses and dies in
  the re-bless commit that absorbs it; expiry is the backstop.
- **Nothing fails silently green.**  Waived counts print on every
  run; expiry, staleness, and ceiling breaches all go loud.

The distinguished "A" is named in `baselines.toml` (per tier, with
its contract version — the gate refuses a mismatch).  Re-blessing =
`bless.py` rewrites the pointer and you commit it; that commit is
the re-bless event, and the waivers it absorbs die in it.  Waiver
lifecycle: born in the MR whose change it excuses; predicate must
name direction+league+sportsbook plus a `max_rows` ceiling and a
dated expiry (≤90 days) — `waivers.py` rejects anything looser.  A
breached ceiling waives nothing; an expired waiver stops matching;
a stale waiver (matched nothing) is reported for deletion.

## Files

| File | Role |
|------|------|
| `project.py` | layer 1: the projection rule (`VERSION` = the contract) |
| `diff.py` | layer 2: set-diff, bucketed report; `--waivers` = gate mode (exit 0 iff no UNEXPLAINED) |
| `gate.py` | layer 3 in one command: candidate SHA vs blessed baseline under waivers |
| `waivers.py` / `waivers.toml` | reviewed excuses: validation, matching, ceilings, expiry |
| `baselines.toml` | the blessed SHA per tier — git owns the reference |
| `run_engine.sh` | SHA + tick -> cached canonical projection (worktree, run, project) |
| `corpus.py` | materialize ticks from the bucket, verified against `MANIFEST.sha256` |
| `config_project.py` | legacy tip-migration stage 1, layer 1: canonical form for CONFIG — market rules, entities, aliases, canonical markets (own `VERSION`) |
| `config_pull.py` | legacy stage 1 side B: BQ rule snapshot -> canonical config lines (COW-coalesced, cached). Side A (`config_extract.py`) has been deleted |
| `config_toml.py` | independent TOML entity reader — a second transcription that catches extractor bugs; counts comment instances (EXPECTED-LOSS) |
| `config_diff.py` | stage 1's gate: both-direction diff, MATCHED / WAIVED / EXPECTED-LOSS / UNEXPLAINED; exit 0 iff no UNEXPLAINED |
| `config_waivers.toml` | audit-bound waivers for config deltas (today: the quoted-key display-name losses) |
| `bless.py` | publish baseline projections of a known-good SHA to the bucket |
| `build_manifest.py` | corpus scan -> `manifest.toml` + integrity records |
| `manifest.toml` | per-tick witnessability (leagues, exchanges) + smoke/full tier |
| `MANIFEST.sha256` / `.md5` | authoritative corpus hashes (md5 = GCS stored hash, enables no-download bucket audit) |
| `gold_audit.py` | one-off audit vs hand-verified gold files (run 2026-08-10, passed; kept for provenance) |
| `live_gate.py` | **the pre-prod CI gate** — candidate vs the SHA prod runs, on fresh prod snapshots + incident cases (see "Live gate") |
| `materialize.py` | prod fetch snapshot (`raw_ingestion_us.*_fetch_raw`) -> replayable tick dir, the files the VM wrote |
| `invariants.py` | rules every published mapping must obey, judged against the raw venue catalogues (no baseline needed) |
| `names.py` | independent name matcher for the invariants (never the engine's own) |
| `swaps.py` | tags gate deltas where a contract moved to the opposite side; only a `side_swap` waiver excuses one |
| `incidents.toml` | permanent regression cases: a snapshot that witnessed an incident + the correct mappings |
| `credentials.py` | read-only impersonated identity for the three gate steps that touch GCP |
| `plan.md` | state, audit facts and asks from the retired rules-as-data redesign (historical) |
| `HISTORY.md` | build diary: calibration evidence, findings, decision log |

## Usage

```bash
# the everyday gate: did my change move anything?  (layer 3)
python -m regression.gate HEAD

# materialize corpus ticks (cache root: $MM_CORPUS_CACHE, else ~/.cache/mm-corpus)
python -m regression.corpus pull --smoke

# unopinionated A/B on any pair of SHAs (layer 2 — always available)
regression/run_engine.sh 451f854 data/2026-07-29/16_19
regression/run_engine.sh e5666a5 data/2026-07-29/16_19
python -m regression.diff \
    ~/.cache/mm-regression/canon/451f854.2026-07-29_16_19.all.v2.jsonl \
    ~/.cache/mm-regression/canon/e5666a5.2026-07-29_16_19.all.v2.jsonl
```

## Live gate (pre-prod, CI)

`regression:mapping-gate` in `.gitlab-ci.yml` runs `python -m
regression.live_gate` on every MR, on `test`, and on `main`; both prod
deploys (`deploy:mapping-pipeline:prod`, `deploy:mapping-console:prod`)
`needs:` it, so a red gate cannot ship.  Built after the 2026-09-29 side
flip (mmmapper `1f843ccc`, epic &91), which moved 22 crypto.com contracts
onto their opponents and passed every existing check.

What it does, in order:

1. **Baseline = what prod is running**: the newest
   `markets_us.market_mapping.mapper_git_commit`, not a blessed pointer.
2. **Pin the rules**: exports the activated tip once
   (`scripts/build_sot_fixture.py`) and runs both engines on that file via
   `MAPPING_SOT_FIXTURE`, so a delta is always the code's, never a tip
   edit's (the tip is legacy; see `CLAUDE.md`).  The tip id joins the projection cache key (`MM_REGRESSION_TAG`).
3. **Fresh inputs**: rebuilds the 2 newest prod fetch snapshots from
   BigQuery (`materialize.py`; each table's result read back as 16 row
   ranges in parallel, ~15 s a tick) — today's leagues, venues and listing
   shapes, which the frozen corpus below cannot witness.  Not covered:
   runshop, DKEX, Huddle (not in the fetch tables).  SX Bet and Underdog
   are diffed on their own stamps and checked for `contract_reused` only
   (no venue-label invariant).
4. **Diff** (`diff.py` gate mode + `swaps.py`): every removed row must be
   waived in `waivers.toml` (born in the MR that causes it); a side swap
   needs a waiver with `side_swap = true`.  Added rows are new coverage:
   counted as NEW ROWS in the report, never gated — step 5 judges them.
   Caveat: the label invariant only covers competitor-sided markets, so a
   wrong bind in a new over/under prop bucket is caught only by
   `optic_disagrees` / `contract_reused`; read the NEW ROWS samples.
5. **Invariants** (`invariants.py`) on the candidate's output against the raw
   catalogues: `venue_label_swapped`, `optic_disagrees`, `contract_reused`.
   A violation prod does not have fails; one prod shares prints as ALREADY
   IN PROD.  A swap that fixes a flip prod has is a CORRECTION, not a delta.
6. **Incidents** (`incidents.toml`): each replays its snapshot and asserts
   the correct mapping of named contracts — these fail even when prod shares
   the bug, because an incident case is a promise.

**In CI it is fanned out** (`--stage`): `regression:mapping-gate:plan`
resolves both SHAs, pins the tip and picks the snapshots once
(`gate-plan/plan.json`); `regression:mapping-gate:run` (`parallel: 5`)
replays one run per job — a replay is mostly serial and needs ~4-6 GiB, so
one 12 GiB pod held only one and five ran back to back — and hands back
canonical rows, violations and incident results (`gate-runs/`);
`regression:mapping-gate` (the job the deploys need) judges them.
`regression:mapping-gate:venv` refreshes the venv cache the others only
pull.  `python -m regression.live_gate` with no `--stage` still does all of
it in one process.

Exit 0 = safe to deploy; 1 = do not deploy (`gate-report/report.md` says
why, `violations_*.jsonl` lists every row); 2 = the gate could not run
(also blocks; nothing fails open).  Measured 2026-09-30 on one full prod
snapshot: ~6 min wall, 2.2 GB peak RSS per engine.

**When it fails on your MR:**

- *Unexplained deltas* (removed rows) you meant: add a waiver to `waivers.toml` in the MR
  (direction + league + sportsbook, a `max_rows` ceiling, an expiry ≤ 90
  days).  Reviewers read it.
- *Side swaps*: almost always a bug.  If it is a deliberate re-orientation,
  the waiver must say `side_swap = true` and the reason must explain it.
- *New violations*: the report prints the venue's own label next to what
  you mapped it to.  Fix the code; there is no waiver for an invariant.
- *Incident case*: you have reintroduced a past incident.

**After an incident**: add an `[[incident]]` to `incidents.toml` in the fix
MR — the snapshot that witnessed it and 2-4 contracts with their correct
Optic selection.

Local run (needs BQ read on `rs-marketmaking`, ~6 min):

```bash
python -m regression.live_gate --candidate HEAD --out /tmp/gate
# faster: one league, one snapshot, explicit baseline
python -m regression.live_gate --candidate HEAD --baseline origin/main \
    --snapshots 0 --snapshot 2026-09-30T15:00 --league ufc --out /tmp/gate
```

## Corpus

183 recorded ticks (2026-03 .. 2026-08) under
`gs://rs-marketmaking-mapping/corpus/data/<date>/<HH_MM>/`.  The
checked-in `MANIFEST.sha256` is the authoritative definition of the
corpus bytes — the bucket is just storage, and `corpus.py` verifies
every file (cached or freshly downloaded) against it on every pull,
so drift fails loud.  `manifest.toml` records what each tick can
witness; a zero diff only means something if the tick could have
witnessed the change.  The `tier` field (smoke = 9 ticks, one per
era × exchange-mix; full = everything) is human-owned and survives
regeneration.

Calibration and verification history: `HISTORY.md`.
