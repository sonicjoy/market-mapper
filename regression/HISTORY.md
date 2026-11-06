# Regression harness — build history and decision log

Archived 2026-08-14, when `plan.md` was rewritten as a lean
Joe-facing document.  This file is the pre-rewrite `plan.md`
VERBATIM — the full build diary, calibration evidence, findings,
and decision log for roadmap steps 1–5 — plus one appendix rescued
from `docs/joe-redesign.md` (deleted the same day; the rest of that
file was Joe's own design text, which lives with Joe).  Nothing
here is deleted history: `plan.md` states what is; this file
records how it got that way and why.

---

# Regression harness — state and plan

Status doc for whoever picks this up next (fresh agent or human).
Written 2026-08-07.  Companion to `README.md` (which describes what
exists); this file records what happened, what is decided, what is
merely suggested, and what to build next.

**Working mode (Greg's explicit preference): one step at a time,
building on the MVP, each step reviewed and understood before the
next.  Do not one-shot the remaining roadmap.**

## Why this exists

Two consumers:

1. **Refactor gate for the current mapper** — e.g. the planned
   line-kind refactor (see "Greg's review" in
   `docs/joe-redesign.md`), which must produce ZERO diff.
2. **Migration gate for the ground-up redesign**
   (`docs/joe-redesign.md`) — old engine + TOML config vs new engine +
   BQ seed snapshot on identical inputs, every delta explained or the
   gate fails.  Two-stage: prove the seed snapshot is a faithful
   transcription of the config (data equivalence) BEFORE diffing
   engines, so config-transcription errors never masquerade as engine
   bugs.

## What is done (verified facts)

- **Corpus secured.**  179 usable ticks (2026-03-06 → 2026-07-30,
  987 jsonl files, 5,883,264,419 bytes — the figure first recorded
  here was 6,236 bytes higher, measured pre-cleanup; the manifest
  number is the verified one) uploaded to
  `gs://rs-marketmaking-mapping/corpus/data/<date>/<HH_MM>/`
  (us-east4, uniform bucket-level access).  Byte totals verified
  identical local↔bucket; every line of every file verified valid
  JSON before upload.  Removed beforehand: 3 empty tick dirs, 1 tick
  with no optic file (unusable), stray `.DS_Store`/`.claude` junk,
  empty gold files.  The bucket is PRIMARY; the local `data/` in this
  repo is Greg's fully-populated cache (decision: option 1 — point
  the future cache variable at it; treat as read-only mirror).
- **Harness MVP built, calibrated, promoted** to `regression/`
  (`project.py`, `diff.py`, `run_engine.sh`, 8 tests, pyright clean).
  Calibration on tick 2026-07-29/16_19: determinism byte-identical;
  451f854→f5dd92d zero diff (correct: tick has no cricket/friendlies
  fixtures — "unwitnessable"); 451f854→e5666a5 exactly +238/−0, all
  mlb×polymarket F5 (matches commit); e5666a5→2638e99 zero diff
  (control).  A bash-3.2 empty-array bug in `run_engine.sh` (found by
  Greg reproducing the README) is fixed; both arg paths verified.
- **Comparison contract decided** (see `project.py` docstring):
  grain = (9-field bet key × sportsbook stamp), crypto stamp includes
  `symbol` (twin-symbol grain), the Optic parent pointer
  (fixture_id, optic_market_id) IS compared, `check` block / BQ
  coercions / ordering are NOT.
- **Contract v2 (2026-08-07): optic source_ids passthrough added.**
  Greg's Poly-US question exposed a gap: `load_mappings.flatten_rows`
  publishes BQ rows from TWO paths — constructed exchange blocks AND
  a passthrough of `optic_odds.source_ids` for
  `OPTIC_MAPPED_SPORTSBOOKS` (Polymarket, Polymarket (USA), Novig,
  SX Bet, DraftKings; venues with no fetcher/matcher whose ids
  OpticOdds carries, load-bearing for RFQ tenants — the SX RFQ
  mapper resolves marketHash off them).  That was ~a third of
  published rows (BQ since 2026-07: Poly 17,620 / Kalshi 12,073 /
  Poly USA 8,327 / Novig 6,467 / crypto 4,057 / PX 2,412 / SX
  2,080), invisible to the v1 projector, which also wrongly skipped
  "no exchange stamp" records (12,387 publishable ones in the
  calibration tick alone).  v2 mirrors `flatten_rows` exactly:
  passthrough stamps verbatim, Polymarket dedup (passthrough wins
  over constructed `clob_token_id`, both normalized to
  `{"selection_id"}`), and the loader gates (no optic_odds → no
  rows; line-disagreement drops constructed stamps but keeps
  passthrough; crypto PM.NPO mismatch drops crypto).  The contract
  is now versioned: `project.VERSION` keys the projection cache
  filename (`run_engine.sh`), so contract bumps can never diff
  stale projections against fresh ones.  Done BEFORE step 3 on
  purpose — baselines blessed under v1 would have baked the blind
  spot in.  `PASSTHROUGH` must track `OPTIC_MAPPED_SPORTSBOOKS`
  (deliberate copy; additions there are contract changes here).
  Re-calibration evidence (2026-08-10, tick 2026-07-29/16_19;
  moved here from README when it was condensed): the three known
  diffs reproduce exactly under v2 (IDENTICAL / +238−0 all
  mlb×polymarket / IDENTICAL); v1→v2 row change 14,308→35,176
  reconciles to the row — +14.9k passthrough stamps (novig 6,520 /
  poly_usa 6,806 / sx_bet 1,568; polymarket 1,577→9,949 = 1,088
  constructed + 8,861 passthrough) and every removed constructed
  stamp (crypto 1,861 / kalshi 325 / px 212 / poly 46) attributed
  to the no-optic_odds gate — v1 was counting stamps the loader
  never publishes.  The line-disagreement and crypto PM.NPO gates
  bite zero records on this tick (belt-and-braces).
- **Manifest + integrity records built (step 1, 2026-08-07).**
  `build_manifest.py` generates `manifest.toml` (per-tick
  witnessability: leagues from optic fixtures, exchanges with
  non-empty feeds, aux files, empties; `tier` is human-owned and
  preserved on regeneration), `MANIFEST.sha256` (sha256sum format,
  verifies downloaded/local files) and `MANIFEST.md5` (md5sum
  format; GCS stores an MD5 per object, so bucket drift is
  detectable from a listing alone, no download).  All three checked
  in; the two MANIFEST files also uploaded to
  `gs://rs-marketmaking-mapping/corpus/`.  Generation verified the
  local mirror against the bucket: all 987 files match size+MD5;
  the 7 local-only extras are the known laptop-only files.  Smoke
  tier = 8 ticks (~598 MB, one per era × exchange-mix, incl. the
  calibrated 2026-07-29/16_19); runshop data exists in only 3 ticks
  corpus-wide, so its smoke coverage is a single tick
  (2026-07-18/03_00).  Aux facts learned: `mappings.jsonl`
  (117 ticks) is captured benchmark-format engine output;
  `gold/*.jsonl` = nba 61 / ncaab 60 / mlb 10 ticks;
  `px-orphans.jsonl` in 2 ticks, `kalshi_gaps.jsonl` in 3.

## Key background (read before designing further)

- `docs/joe-redesign.md` — the redesign this gates, including Greg's
  review section (line-kind refactor as precondition; comment
  migration; the equivalence-gate section that this harness
  implements).
- Canonical-row mental model: today exchanges are siblings merged by
  9-field key collision (`pipeline.row_key`); the redesign makes the
  Optic odd the parent and exchange rows its children.  BQ
  `market_mapping` is the long form: key + `sportsbook` (+
  `source_ids.symbol` for crypto twins).
- Engine invariants relied on: `mappers.run <tick> --json` emits the
  benchmark format (`pipeline.canonical_row_to_json`); output is
  deterministic; `--league` restricts scope.

## Roadmap (in order; one step per session-ish)

1. **`manifest.toml`** — DONE 2026-08-07 (see "What is done").
   Per tick: leagues present (from optic fixtures), exchanges
   present (non-empty files), aux/empty files, sizes.  Two tiers:
   `smoke` (8 ticks, one per era × exchange-mix) and `full`
   (everything, pre-flip gate).  Witnessability metadata is the
   point: a zero diff is only meaningful if the tick could have
   witnessed the change.
2. **`corpus.py`** — DONE 2026-08-10.  `ensure_tick` (library) /
   `pull TICK...|--smoke|--full` (CLI) materialization from the
   bucket; verify-on-pull, NOT presence-=-validity (decision
   2026-08-07): EVERY file — cached or freshly downloaded — is
   hashed against `MANIFEST.sha256` on every ensure, a mismatch is
   a corpus-integrity violation and aborts (drift fails loud, never
   silently changes results).  Downloads land as `.part`, renamed
   only after the hash verifies; failed downloads clean up.  Cache
   root (decided 2026-08-10): `MM_CORPUS_CACHE` env var, else
   `~/.cache/mm-corpus` — fixed default, NO auto-detection of repo
   `data/` (verify-on-pull removed auto-detect's safety payoff;
   default matches the `MM_REGRESSION_CACHE` convention).  Greg's
   `.zshrc` points the var at his repo `data/` mirror, so his
   machine never re-downloads.  Verified for real: cached path
   (both directions zero-download), genuine bucket download
   (2026-03-23/06_56 into an empty root), and corruption abort.
   The GCS stored-MD5 no-download bucket audit (vs `MANIFEST.md5`)
   remains available but is not wired into corpus.py — it's an ops
   check, not a pull-path one.
3. **Baselines** — SMOKE TIER BLESSED 2026-08-10: all 8 smoke ticks
   projected at main (fb4154c, contract v2) via `bless.py` and
   published to `gs://rs-marketmaking-mapping/baselines/fb4154c/`
   (19.3 MB).  Regenerable at will (pure function of
   sha+config+tick+contract version — the version is in the
   filename, so contract bumps orphan old baselines), so a cache
   with provenance, NOT time-sensitive.  Full-corpus bless
   deliberately deferred until a pre-flip gate needs it (~12 h of
   engine runs).  First real gate already run: retire-gold
   (d20693c) vs main — IDENTICAL on the calibrated tick.  Gold
   retirement itself is on branch `retire-gold` (pushed), awaiting
   MR through test.  Next real use: gate the line-kind refactor
   (zero diff, no waivers).
   **Gold audit RUN 2026-08-10 — current main is faithful to gold;
   triage awaiting Greg's sign-off.**  `gold_audit.py` re-ran
   current main with `--gold` over all 71 gold ticks (131 league
   files, zero engine failures; the engine's own gold writer on
   both sides, so no format transcription).  Results: 973,055
   matched (95.9%); 4,097 restamped = optic_id null→value on mlb
   team_total (c110eb7 resolving Optic odds that ship no team_id —
   improvement); 292 restamped = kalshi null→value (coverage
   gained); 37,820 new_only = post-April config growth (mlb player
   props, F5, first-inning etc.); 58 gold_only = Kalshi-only
   canonical rows (optic_id AND px_line_id null) on 2026-04-26 +
   2026-04-30 mlb, gone entirely from current output — BUT the BQ
   loader never published optic-less records, so these were never
   market_mapping rows and the v2 projector excludes them by
   construction: baselines are unaffected.  Root cause CONFIRMED
   (2026-08-10, from the audit engine logs — no bisect needed): all
   58 are MLB same-day doubleheaders (COL@NYM 2026-04-26; SF@PHI +
   HOU@BAL 2026-04-30).  9bf039c (2026-07-16, multiple
   ScheduleEntry support) made the engine doubleheader-aware, and
   the policy since is to SKIP Kalshi tickers that cannot be
   disambiguated between the two games (missing > wrong; tracked as
   a kalshi_gaps category).  The gold-era engine emitted these as
   ambiguous kalshi-only rows — gold was over-permissive, the
   current skip is the correct behavior.  Possible future
   enhancement, out of scope here: some tickers embed a tip-off
   time (e.g. KXMLBGAME-26APR26__1340__COLNYM) that could
   disambiguate.  Evidence:
   `gs://rs-marketmaking-mapping/reports/gold-audit-2026-08-10/`
   (triage.jsonl + run log).  Retiring the gold mechanism touches
   engine code (mappers/run.py --gold, pipeline.gold_row) — its own
   MR through test, NOT a regression/ commit.
   Original decision (2026-08-07): before blessing,
   run current main over the ~84 gold ticks (nba 61 / ncaab 60 /
   mlb 10, per manifest `aux`) and one-off diff against the gold
   files, restricted to the three stamps gold covers
   (optic/px/kalshi).  Rationale: the harness is otherwise purely
   relative (engine vs engine) and structurally blind to
   always-been-wrong mappings; gold is the corpus's only
   human-verified truth, so this validates the baselines rather
   than merely freezing them.  Needs a small gold→canonical
   projector (the reader/writer split `project.py` anticipates).
   Each mismatch is a hand-blessing error, a legitimate config
   change since capture (gold was captured against Mar–Jun era
   config), or a real long-standing bug — triage, then RETIRE the
   gold mechanism; don't leave two sources of truth.
4. **Waivers + differ classification** — DONE 2026-08-11 (commit
   after this line's).  Built exactly to the seven rules below:
   `waivers.py` (validation: blanket waivers, unknown keys, and
   >90-day expiry are file errors; matching: mechanical, first
   match in file order wins; breach = ceiling exceeded → waives
   NOTHING), `diff.py --waivers` gate mode (WAIVED counts always
   printed; expired waivers stop matching and report what they
   would have covered; stale waivers named for deletion; invalid
   file exits 2, unexplained deltas exit 1), `baselines.toml`
   (smoke = fb4154c, contract 2; rewritten by bless.py on tier
   blesses — committing it IS the re-bless event), and `gate.py`
   (candidate vs blessed baseline over a tier in one command;
   refuses contract mismatch; downloads baseline projections from
   the bucket into the projection cache on demand).  E2E on the
   real +238 pair: waiver covers → GATE PASS 238/300; ceiling 100 →
   BREACHED, all 238 UNEXPLAINED, exit 1.  Full-driver E2E:
   `gate.py HEAD` vs blessed smoke — see README/commit.  The
   policy rules (agreed with Greg 2026-08-11):

   1. Git owns the reference: `regression/baselines.toml` records
      the blessed SHA per tier; bless.py updates it, so re-blessing
      IS a commit.  The differ reads it; nothing gates against an
      unrecorded baseline.
   2. Every gate delta is classified MATCHED / WAIVED(id) /
      UNEXPLAINED; exit 0 iff UNEXPLAINED = 0.  Matching is purely
      mechanical field comparison; the gate never consults AI.
   3. A waiver is born in the same MR as the change it excuses;
      reviewer approves behavior + excuse together.  No waiver
      lands alone.
   4. A predicate must be narrow by construction: direction +
      league + sportsbook required (more welcome), plus a max_rows
      ceiling and a reason citing a commit/ticket.  The differ
      REJECTS the file if any entry lacks these — a blanket waiver
      is a syntax error, not a style complaint.
   5. Expiry ≤ 30 days at creation.  Renewal is an explicit commit
      with a stated reason; the waivers.toml diff is the audit
      trail.
   6. A waiver dies in the re-bless commit that absorbs its change.
      Stale waivers (matched 0 deltas) are reported every run and
      deleted, not kept "just in case".
   7. Waived deltas are still counted and printed every run —
      green with "WAIVED: 238" visible, never silently green.

   Expiry design (Greg's CI ponder): wall-clock
   expiry makes verdicts time-dependent — fine for this dev-run
   gate and for step 7's scheduled VM runs (an owned alarm), poison
   for per-commit CI.  If CI ever wants the gate: pin each waiver
   to the baseline SHA it excuses against (`against = "<sha>"`,
   refused when the pointer moves — deterministic, event-based
   invalidation) as primary, with a long-stop expiry kept only as
   the anti-rot alarm for the nobody-ever-re-blessed case.
   Honest residual (accepted): wrong-but-new rows inside a waived
   territory, under the ceiling, during the window, pass silently —
   a waiver IS a bounded no-inspect decision; policy keeps the
   region small, bounded, short-lived, and visible.
5. **Data equivalence check (redesign stage 1)** — TOML/config ≡ BQ
   seed snapshot, no engine involved.  CONTRACT v1 BUILT 2026-08-13
   (`regression/config_project.py` + 10 tests, pyright clean): the
   config-side sibling of project.py — writer half only, one line
   per market_rule / entity / alias / canonical_market, keys
   mirroring control_plane/cow_diff natural keys, alias_value in
   the alias key (exception-list semantics), annotations ("a")
   excluded from equality via strip_annotations, absent==null +
   bq-CLI string-scalar coercion, duplicate (t,k) identity a loud
   error, own VERSION=1.  mapping_leagues deferred (decision 4).
   Decisions settled with Greg 2026-08-13: (1) side A trusts
   Joe's extractor for Python config (stage 6 backstops extractor
   bugs THAT CORPUS TICKS CAN WITNESS — thin-league caveat), plus
   an independent TOML reader for entities; (2) seed audit AND tip
   audit as two invocations of one tool; (3) comment loss = counted
   EXPECTED-LOSS bucket implemented as a waiver, never UNEXPLAINED;
   (4) leagues/settings JSON deferred to its own sub-step.
   Contract committed as 9bad637 and PROVEN END-TO-END the same day
   by a by-hand mini seed audit — MLB market rules, side A = Joe's
   extractor run in a worktree pinned at a0ffe0c (the snapshot's
   own source_revision), side B = the 95 MLB rows of prod
   S0_cb85f20c3ad7: 95/95 matched, zero deltas both directions.
   That run IS the spec for the remaining components; its recipe
   and gotchas:
   - Side A: `git worktree add <dir> <source_revision>`, then the
     REPO venv's python inside it:
     `from mappers.seed.extract import extract_snapshot` →
     `dataclasses.asdict` each IR item → feed canon_all.  Needs no
     network/BQ/env; regression-harness branch itself predates
     mappers/seed, so the worktree is mandatory, not optional.
     Remove the worktree after.
   - Side B: `bq query --format=json --max_rows=...` with
     `select * except(rule_set_id)` — there is NO environment
     column on the rule tables; --format=json stringifies scalars
     ("true"/"100"), which canon coerces BY DESIGN (test covers
     it).  mapping_rule_sets.source_revision pairs every snapshot
     to its repo SHA (verified populated).
   Remaining components, in build order (one per session-ish):
   2. **Side-B materializer** — DONE 2026-08-13
      (`regression/config_pull.py` + 15 tests, pyright clean).
      rule_set_id → cached canonical lines file
      (`$MM_REGRESSION_CACHE/config/<project>.<rule_set_id>.v<N>.jsonl`;
      .part-then-rename; snapshots are append-only so the cache
      never expires, `--refresh` re-pulls).  COW-aware as specified:
      receipts walked tip→root, last-write-wins per cow_diff natural
      key, tombstones hide — a deliberate transcription of
      cow_rebuild.py with two loud-not-silent hardenings (lineage
      cycle / dangling parent = error where cow_rebuild quietly
      stops; duplicate natural key within ONE layer = error where it
      lets the first row win).  Wire-format gotcha handled + tested:
      bq CLI JSON stringifies scalars, so tombstone arrives as
      "true"/"false"/null and a truthiness test would delete
      explicitly-live rows.  rule_set_id rides as an annotation on
      every line (post-coalesce it names the layer a row survives
      from — tip-audit delta provenance); canonical_markets read
      from the tip receipt only (candidate creation clones the
      parent's list verbatim, bq_store._insert_receipt).  Verified
      on real data in both projects (via a labeled diagnostic run
      filtering the one collision below, nothing cached): prod
      S0_cb85f20c3ad7 → 2,982(+1) market rules / 3,767 entities
      (= receipt counts) / 7,020 aliases / 88 canonical markets,
      byte-deterministic, and the 95 MLB market_rule lines reproduce
      the by-hand mini audit exactly; test P_0eccd9b1a539 (real
      sparse layer) → the LIV/LFC kalshi alias surfaces from the tip
      layer over the seed parent, correct provenance.
      **FINDING 2026-08-13 (decision needed with Greg/Joe; blocks
      strict materialization of every current prod snapshot):** all
      8 prod seeds carry TWO rules for the natural key (ufc, optic,
      market_id, method_of_victory) — action=map priority 100
      (rule_id 05898797225ae9e3, from ufc.py OPTIC.table_types) AND
      action=ignore priority 50 (rule_id c32db3f13913e0c9, from
      seed/profiles.py INTENTIONAL_OPTIC_IGNORES, note still citing
      docs/ufc_mov_mapping.md's pre-bucketer deferral).  Root cause:
      crossed same-day parallel branches, both merged 2026-08-07 —
      bdaa5e5 re-enabled the MoV mapping while 17fc347 (M1 extract)
      shipped the ignore registry written against the unmapped
      state; neither the extractor nor the loader validates
      natural-key uniqueness, so every seed since emits the
      contradiction.  Note the current engine ignores
      INTENTIONAL_OPTIC_IGNORES entirely (seed-only metadata), so
      live behavior is map — but under the new engine's rule
      interpreter the winner is whatever priority semantics say,
      i.e. exactly the kind of silent behavior fork step 5 exists
      to catch.  This is the only collision: entity keys are clean
      corpus-wide, market rules clean everywhere else.  Options:
      (a) fix main — drop the stale INTENTIONAL_OPTIC_IGNORES entry
      (or re-deliberate the mapping) and reseed; harness stays
      strict (recommended — the config is self-contradictory and an
      audit SHOULD refuse it); (b) add priority to the market_rule
      contract key (VERSION bump) so both lines coexist — papers
      over conflicting actions and diverges from cow_diff identity,
      not recommended.  Side A will hit the same duplicate in
      canon_all, so the seed audit is blocked either way until
      decided.  Also of note: parity.py (Joe's M2 dual-read) keys
      map and ignore rules into separate sets, so it can never see
      this class of conflict.  DECIDED 2026-08-14 with Greg: option
      (a), framed as two asks to Joe — see "Asks for Joe" 6/7.
      WORKAROUND 2026-08-14 (agreed with Greg) so testing proceeds
      while the fix sits with Joe: `config_pull.KNOWN_STALE_ROWS`,
      a pinned drop-list applied before canonicalization (wired
      into side B; component 3 must apply the same shared
      `drop_known_stale` — see its build notes).  Pinned by rule_id (content-addressed from
      league/sportsbook/action-tag/source_key, so event-invalidated:
      any change to the row un-matches the pin and the duplicate
      check goes loud again) with expect-field verification against
      hash collision; drops the IGNORE because that is what the fix
      will do, so today's canonical files equal the post-fix state;
      every drop prints; a pin matching nothing reports itself
      stale for deletion; expiry 2026-09-14 is the anti-rot
      long-stop (expired-and-matching = hard error).  With it, all
      prod snapshots and the test candidate materialize cleanly
      (S0_cb85f20c3ad7: 13,857 lines; P_0eccd9b1a539: 12,454,
      matching the diagnostic dry-runs byte-for-byte on stats).
   3. **Side-A runner** — DONE 2026-08-14
      (`regression/config_extract.py` + 10 tests, pyright clean).
      Python sibling of config_pull.py rather than a shell script
      (the record shaping wants Python; the worktree/cache
      mechanics are run_engine.sh's).  SHA → detached worktree
      under `$CACHE/wt/<sha>` (shared with run_engine.sh, kept for
      reuse) → extractor as a SUBPROCESS python (repo venv, cwd =
      worktree root; `python -c` puts cwd on sys.path) printing one
      JSON payload → records_from_extract (deliberate mirror of
      config_pull.records_from: entity/alias explosion, same
      inheritance; NO rule_set_id annotation — the config has no
      layers) → `drop_known_stale` (the shared MoV pin, verified to
      bite: same content-addressed rule_id on both sides) →
      canon_all → cached as
      `<cache>/config/<sha>.extract.v<N>.jsonl` (.part-then-rename;
      a SHA's config is immutable so the cache never expires,
      `--refresh` re-extracts).  SHAs predating 17fc347 refused by
      name; `missing_profiles` reported LOUDLY but non-fatally
      (profiles only shape ExchangeIR settings on the deferred
      leagues kind — revisit when leagues join the contract; the
      real extractor reports 168 of them, so expect that warning).
      The cross-side test is the load-bearing one: the same logical
      content fed through side A's reader (typed IR payload) and
      side B's (stringified bq wire rows) reaches identical
      compared forms.  Verified for real (2026-08-14): extraction
      is ~1 s/SHA; byte-deterministic across --refresh; e1a7136
      extract = 13,857 lines matching prod seed S0_cb85f20c3ad7
      with ZERO deltas both directions — the first full-corpus seed
      audit dry-run, all four kinds, and it PASSES at the right SHA.
      **FINDING 2026-08-14 (surfaced by that dry-run; DECIDED
      2026-08-14 with Greg — now ask 8 in "Asks for Joe"):**
      `mapping_rule_sets.source_revision` does not determine seed
      content.  S0_cb85f20c3ad7 stamps a0ffe0c (HEAD at seeding,
      committed 2026-08-11 18:07 UTC) but extracting a0ffe0c leaves
      73 lines B-only (22 entities + 51 aliases in atp_challenger /
      international_club_friendlies / itf_men — the churn-heavy
      auto-pin leagues; A-only zero, market rules and canonical
      markets exact).  All 73 landed in git as e1a7136, committed
      2026-08-12 07:02 UTC — AFTER the seed's created_at
      (2026-08-11 22:59 UTC).  So the seeder ran from a DIRTY tree:
      the alias pins existed as local TOML edits when the seed was
      cut and were committed next morning; source_revision stamps
      HEAD without recording the dirt.  Extracting e1a7136 instead
      gives zero deltas, which is what confirms the story (content
      = HEAD + pending TOML edits, nothing else).  Implications:
      a seed audit against the stamped source_revision can report
      UNEXPLAINED deltas that are real irreproducibility, not
      transcription bugs — the gate SHOULD flag them (this is the
      audit doing its job), but component 5's triage needs the
      category.  Attribution (2026-08-14): both bracketing commits
      are Joe's — the seed was cut between his a0ffe0c and his own
      next-morning e1a7136 pinning those aliases, i.e. HIS pending
      TOML edits were in the seeding tree; nothing to repair in BQ
      (content is fine, only the stamp lies; snapshots are
      append-only) — the next clean-tree reseed supersedes it, and
      the MoV fix (ask 6) needs a reseed anyway, so one reseed
      absorbs both.  Until then the harness audits this snapshot
      against e1a7136.
   4. **Independent TOML entity reader** — DONE 2026-08-14
      (`regression/config_toml.py` + 11 tests, pyright clean).
      Parses every `config/*/{team,player}_aliases.toml` at a SHA
      with stdlib tomllib + its own copies of the two
      seed/entities.py comment regexes; emits entity/alias
      canonical lines plus a per-league comment report
      ({files, comments, migrated, lost, unknown_keys}), cached as
      `<sha>.toml.v<N>.jsonl` / `<sha>.toml_report.v<N>.json`.
      Implemented via `git ls-tree`/`git show` — reads git OBJECTS,
      no working directory at all, which satisfies (more strongly)
      the worktree decision below; works at any SHA since TOMLs
      predate mappers/seed.  Unknown section keys warn loudly and
      land in the report (the extractor drops them silently —
      identity-loss hazard its own comments warn about); none exist
      corpus-wide today.  alias_id is not reproduced (content hash
      needing mappers/ code; annotation, never compared).
      Verified at e1a7136: 10,022 lines (3,512 entities / 6,510
      aliases from 49 TOMLs; the 2 `.bak` files are correctly
      ignored by both sides), byte-deterministic; 4,938 comment
      instances, 3,100 migrate / 1,838 lost — THE EXPECTED-LOSS
      number for the differ (supersedes the 2026-08-13 sizing,
      which measured a different tree with a cruder method).
      Reader↔extractor diff is 100% triaged: 765 extractor-only
      lines = the 255 poly_name:* overlay entities + their 510
      aliases (Python config, the accepted decision-1 tautology,
      filtered by key prefix in the differ) and 40 canonical_name
      deltas = the quoted-key bug below.  No reader-only leagues.
      **FINDING 2026-08-14 (extractor bug caught by exactly the
      de-tautologization this component exists for; DECIDED
      2026-08-14 with Greg — now ask 9 in "Asks for Joe"):** the extractor loses
      the display name of every QUOTED TOML section.  Its
      `_SECTION_HEADER` regex captures the key with quotes
      (`"DK.C"`) while tomllib unquotes dict keys (`DK.C`), so
      `display.get(canon)` never matches and canonical_name comes
      out null.  40 entities at e1a7136 — lol 15, world_cup 23
      (its player file quotes every section), europa_conference_
      league ŽAL, ucl 1 — and it is IN PROD SEEDS (verified:
      lol/DK.C canonical_name null in S0_cb85f20c3ad7 vs
      `# Dplus KIA Challengers` in TOML).  One-line fix in
      seed/entities.py (unquote the regex key before the dict
      lookup); reseed covers it (the same reseed asks 6/8 already
      need).  This reader reports TOML truth deliberately, so the
      40 deltas stay visible until fixed — the differ should carry
      them as a waiver citing this ask, never as noise.
      Original decision (2026-08-14, implemented): read the TOMLs
      from the pinned tree at the target SHA, NEVER the live
      checkout — the checkout carries untracked/staged TOMLs
      (Greg's tree does today), and the harness only reads config
      through git objects; the dirty-tree finding is the
      cautionary tale.
   5. **The differ/gate** — DONE 2026-08-14 (`config_diff.py` +
      `config_waivers.toml` + 17 tests, pyright clean; waivers.py
      schema-parameterized for reuse, defaults unchanged for
      diff.py).  As specified: set-diff on strip_annotations both
      directions, full lines printed for deltas (changed values
      paired as CHANGED for readability, still two deltas for
      ceilings), waivers under the step-4 seven rules with
      config-shaped predicates (direction a_only/b_only/both +
      kind + league required; sportsbook/key_prefix narrowing;
      canonical_market deltas deliberately unwaivable), comment
      loss as the [comment_loss] EXPECTED-LOSS accounting (needs
      --comment-report; missing section = unexplained, expired
      section = file error), --only-kinds / --exclude-poly-overlay
      as printed structural scope (partial readers; the decision-1
      poly_name boundary), filename contract-version mismatch
      refused, exit 0 iff zero UNEXPLAINED / 1 otherwise / 2 on an
      invalid waivers file.
      **FOUR REAL AUDITS RUN 2026-08-14 (step 5 is now complete
      end-to-end):**
      - Seed audit, prod S0_cb85f20c3ad7 vs its EFFECTIVE revision
        e1a7136: GATE PASS — 13,857 matched, zero deltas.  The
        prod seed is a faithful transcription of the config.
      - Same seed vs its STAMPED revision a0ffe0c: 73 UNEXPLAINED
        (exit 1) — the gate catches the dirty-tree seeding (ask 8)
        with self-explaining B-only lines.
      - Reader-vs-extractor entity audit at e1a7136 (--only-kinds
        entity,alias --exclude-poly-overlay, waivers, comment
        report): GATE PASS with everything visible — 9,982
        matched, 765 poly overlay excluded and printed, WAIVED
        30+46+2+2 = 80 quoted-key deltas exactly at ceilings
        (ask 9), EXPECTED-LOSS 1,838 comment instances citing the
        comment-migration ask, zero UNEXPLAINED.
      - Tip audit, test P_0eccd9b1a539 vs its lineage source
        0c898cd: 12,411 matched, 43 B-only UNEXPLAINED (exit 1 =
        the triage worklist, correct semantics) — every delta
        carries rule_set_id provenance and they are exactly the
        console pins since seeding, including the long-documented
        LIV→LFC kalshi alias.  Zero A-only: no TOML content lost.
      LESSON from the tip audit, enforced MECHANICALLY (Greg's
      catch 2026-08-14 — the first fix was only a comment, which is
      exactly the discipline-not-mechanics pattern this harness
      rejects): waiver files are PER-AUDIT-INVOCATION.  Reusing the
      entity-audit file on the tip audit silently absorbed one
      legitimate console edit (the Uwinks lol entity matched
      kind+league by accident) — the step-4 "honest residual" seen
      live.  Now bound as data: the waivers file declares
      `audit = "<name>"` (required) and config_diff refuses to
      classify unless --audit matches exactly (exit 2, verified on
      the real pair).  Seed/tip audits run with no waivers file
      until they earn their own.
   UNBLOCKED 2026-08-13: the
   snapshot format now exists in code (`mappers/seed/extract.py`
   builds a SnapshotIR from the live Python+TOML config;
   `BigQuery/mapping_rule_rows.py` defines the row shapes) and in
   prod BQ (8 snapshots, all `created_via='seed'` full clones,
   2,591→2,983 rules tracking config growth; latest
   `S0_cb85f20c3ad7`, 2026-08-11).  Design learnings recorded
   2026-08-13, from tracing the Kalshi MLB SPREAD rule and the NYM
   entity through real prod rows:
   - **COW storage** (main commit eab7b11): a `rule_set_id` is no
     longer self-contained — a logical snapshot is a tip→root
     coalesce with tombstones
     (`mappers/control_plane/cow_rebuild.py`).  Prod so far holds
     only full seed layers; console-made sparse layers exist in
     `marketmaking-test`.  The check must materialize snapshots via
     the coalesce, never a flat `rule_set_id` filter.
   - **Two possible targets**, answering different questions: the
     original seed (pure exporter-fidelity audit) vs the current
     coalesced tip (seed + all console edits since).  Prod today is
     seeds-only so a prod check is purely an exporter audit; the
     tip-vs-TOML question lives in test, and keeps mattering after
     M4.  Decide with Greg which to gate (likely both, separately).
   - **Entities are exception lists on both sides.**  The default
     "exchange code == canonical_key (Optic abbrev)" is engine code
     in both worlds (verified: MLB has 32 team entities, only 4
     carry a kalshi alias).  Absence is load-bearing — compare the
     exception sets exactly, in both directions; "every BQ alias has
     a TOML source" is not sufficient, a surplus BQ alias is as much
     a delta as a missing one.
   - **Comments migrate only partially**: the seed harvests TOML
     comments solely into `entities.canonical_name` (display names,
     `seed/entities.py`).  Market-rule `notes` are null on seeded
     map rules (verified in prod) — verification provenance and
     block-scoped commentary do not migrate.  The check should
     REPORT comment loss explicitly, not treat `notes` as a
     non-compared field.
   - **`rule_id` is content-addressed** and stable across snapshots
     (the SPREAD rule is `fc054b9872ab0b4d` in all 8 seeds) — a
     natural join key for cross-snapshot diffs.
   - **Match vocabulary is tiny**: 2,930/2,983 rules are `exact`,
     the other 53 are px `suffix` (player-prop market names).  The
     canonical comparison form must include `match_operator` and
     `priority`, and should flag any new operator value as a
     contract change (interpreter-creep watch).
   - **Joe's M2 dual-read** (`mappers/seed/dual_read.py`) is a thin
     runtime version of this check — market-rule KEYS only, against
     the unpinned latest rule set, enabled in test.  Step 5
     subsumes it: full-field, all tables, offline, pinned.
6. **Engine A/B with waivers (redesign stage 2)** — smoke per
   iteration, full at milestones; UNEXPLAINED count per
   league×sportsbook over time is the migration burndown.
7. **Forward parallel runs** — same projector/differ pointed at two
   live outputs per tick on the VM.  BQ MERGE/load path is explicitly
   out of scope until here.

## Asks for Joe

The sendable form — all nine asks, uniquely numbered: 1–5 on the
redesign engine, 6–9 on the current seed pipeline.  Asks 1–3 and 5
were raised with Joe via Slack 2026-08-11 (1 in its looser
pre-merge form); 4 and 6–9 have NOT been raised yet.  All
background, evidence, and status commentary lives in "Redesign
asks — background and status" below; asks 6–9 carry their
evidence in the roadmap step-5 entries.

Hard requirements — without these the harness cannot gate the
migration at all:

1. **Keep `mappers.run <tick> --json` working — same benchmark
   format (`pipeline.canonical_row_to_json`) — when classify flips
   to BQ rules.**  This is what lets us diff old engine vs new
   with zero new comparison code.  Likely costs nothing if the
   flip happens in-pipeline (tightened 2026-08-14; subsumes ask 5).
2. **Give the engine its rules only as a pinned snapshot object.**
   Same tick + same rules must give the same answer, or gate diffs
   cannot be attributed.  Three pieces: (a) an export tool,
   rule_set_id → one file — lineage tip→root, coalesced
   last-write-wins with tombstones deleting
   (cow_rebuild.coalesce_* already does this), ALL tables (market
   rules, entities+aliases, canonical markets, leagues/settings),
   JSON rows in the BQ schema shapes, stamped with rule_set_id +
   source_revision; (b) one loading seam — a Snapshot object that
   classify consumes, constructed either from BQ given an EXPLICIT
   rule_set_id (same coalesce) or from the exported file; no
   "latest" defaulting and no BigQuery client inside classify;
   (c) widen the loaded surface — today's loader stops at market
   rules + output orders; the snapshot must also carry
   entities/aliases, canonical markets, and exchange settings.
   (Recast mechanically 2026-08-14.)
3. **Guarantee same tick + same snapshot → byte-identical output,
   as a stated contract.**  The gate's zero-diff verdict is only
   meaningful
   if repeat runs are byte-identical.  Three pieces: (a) the
   Snapshot object sorts its contents canonically on load — BQ
   result order is not guaranteed (load_market_rules has no ORDER
   BY today); (b) rule selection has a total order — priority,
   then a stated tiebreak (e.g. rule_id), never query or insertion
   order; (c) no wall-clock, uuid, or randomness in emitted rows —
   run metadata lives in audit events, not output.  Acceptance is
   one CI-able check: run twice on the same tick + snapshot file,
   byte-compare.  (Recast mechanically 2026-08-14.)

Comment migration:

4. **Migrate TOML comments into snapshot fields instead of
   dropping them.**  Comments are functional config data and the
   TOMLs are deleted at cutover — whatever doesn't migrate is
   destroyed.  Five pieces: (a) harvest with a comment-aware
   parser (tomlkit) in place of the two regexes; (b) route
   standalone/trailing comments to the notes columns that already
   exist and sit null; (c) map the ~59 "auto-stubbed/auto-pinned,
   unverified" markers to a truthful confidence value — today they
   seed confidence="id_verified"; (d) keep canonical_name clean —
   provenance parentheticals move to notes; (e) one design
   decision: a receptacle for block-scoped commentary (file
   preambles fit mapping_leagues.notes).  Acceptance: the harness
   prints the lost-comment count on every entity audit (1,838
   today) — drive it to zero.  (Recast mechanically 2026-08-14.)

Cheap win — worth doing early, not blocking:

5. **Put provenance on every output row: the matched rule_id per
   exchange stamp, the snapshot rule_set_id, and a reason code on
   every skip/gap.**  A gate delta then names the rule that
   caused it — triage becomes a lookup instead of a hunt, and
   waiver predicates get real fields.  Additive fields on the
   --json format, so no conflict with ask 1.  (Old ask 6; old ask
   5 was subsumed into ask 1 and the list renumbered, 2026-08-14.)

On the current seed pipeline — added 2026-08-14, from the side-B
materializer's MoV finding (full detail and evidence in roadmap
step 5):

6. **Remove the ufc entry from `INTENTIONAL_OPTIC_IGNORES`**
   (`mappers/seed/profiles.py`).  It contradicts the live MoV
   mapping (bdaa5e5 satisfied the ignore's own re-enable
   condition), so every seed snapshot carries both a map and an
   ignore rule for the same key.  One line, no live-behavior
   change; the next seed is self-consistent.
7. **Assert natural-key uniqueness within every written layer** —
   (league, sportsbook, source_key_type, source_key) for rules,
   (league, entity_type, canonical_key) for entities — at extract
   time and at load.  (Per-layer, not global: cross-layer
   duplicates are legitimate COW overrides.)  The general fix
   behind ask 6: that collision shipped in all 8 prod seeds
   undetected because nothing in the pipeline catches a
   self-contradictory snapshot (extractor, loader, and dual_read
   are all blind to it); after cutover the winner would be an
   accident of rule tie-breaking.  Ask 6 removes the instance,
   this prevents the class.

Added 2026-08-14, from the side-A runner's source_revision finding
(full detail and evidence in roadmap step 5, component 3):

8. **Make the seeder refuse a dirty working tree** (better: seed
   from a pinned worktree at a named SHA, which makes dirt
   impossible by construction).  Minimum form: `git status
   --porcelain` non-empty → abort.  S0_cb85f20c3ad7 was cut with
   pending TOML edits in the tree, so its stamped source_revision
   does not reproduce its content — and source_revision must be
   trustworthy or every seed audit starts with archaeology.

Added 2026-08-14, from the independent TOML reader's finding (full
detail in roadmap step 5, component 4; agreed with Greg the same
day):

9. **Unquote the section key in seed/entities.py before the
   display-name lookup** (one line: strip the quotes the
   _SECTION_HEADER regex captures, as tomllib does).  Every QUOTED
   TOML section — ["DK.C"], ["ŽAL"], all 23 world_cup player
   sections — currently seeds canonical_name null because the
   regex-keyed display dict and the tomllib-keyed data dict never
   match; 40 entities at e1a7136, in every prod seed, trader-facing
   post-M4.  The reseed asks 6 and 8 need covers this too.
   Assessment on record (2026-08-14): the corpus is verified clean
   of every OTHER raw-text-scan failure mode (zero in-string '#',
   zero escaped keys), so the one-liner is the right fix NOW; the
   move to a comment-aware parser (tomlkit) belongs to the
   comment-migration work, not this bug — see redesign ask 4.
   Acceptance is free: the harness's entity audit verifies the
   fix — the four quoted-key waivers report stale and get deleted.

One reseed after 6, 8, and 9 land absorbs all three, and the
harness re-audit confirms it exactly — the MoV drop-pin and the
four quoted-key waivers all report stale-for-deletion.

### Redesign asks — background and status

Commentary moved here 2026-08-14 to keep the ask list sendable;
nothing dropped.  Consolidated 2026-08-11 from the suggestion
bullets below and the review sections of `docs/joe-redesign.md`,
and raised with Joe via Slack the same day.  Context for Joe: the
harness side is built (roadmap steps 1–4 done) — the gate machinery
can A/B his engine against blessed baselines the day it satisfies
the three hard requirements.  "Documented" below means written in
joe-redesign.md, not agreed by Joe.

- **Ask 1** is implied by joe-redesign.md's gate section, which
  names the pre-load seam; it was never stated there as an
  explicit requirement.  Sanity-checked against shipped code
  2026-08-14 and tightened to a preservation constraint: the new
  engine does not exist yet (dual_read.py: "Live classify still
  uses Python"; M1/M2 are scaffolding around the old engine), the
  redesign is landing inside the existing pipeline (dual_read is
  called from mappers/run.py), and the --json seam sits DOWNSTREAM
  of classify (run.py:325, engine-agnostic serialization of the
  produced rows) — so if the flip happens in-pipeline the ask
  costs nothing.  The format clause (old ask 5, now merged in) is
  the only part that could cost: if the internal row model
  diverges (parent/child Optic-odd restructure) a translation
  layer is needed — and Joe pushing back on that would itself be
  early signal.  Deliberate escalation: a bare any-format artifact
  would do (project.py's reader/writer split anticipated a second
  reader), but one format means the comparison contract cannot
  fork and the gate needs zero new code in its own trust anchor.
- **Ask 2** is already stated as a "testability requirement" in
  joe-redesign.md — the strongest-documented ask.  SHARPENED
  2026-08-13 by the COW storage change (eab7b11): a `rule_set_id`
  is no longer self-contained, so the ask is now *a
  coalesced-snapshot export to file* (tip→root materialized,
  tombstones resolved — `cow_rebuild.coalesce_*` already exists)
  *plus an engine mode that reads rules from that file*.  As of
  main 3ee5f3d neither exists: `mappers/seed/bq_snapshot.py` reads
  live BQ only and always takes the LATEST rule set (no pin
  parameter even against BQ).
  Sanity-checked against shipped code 2026-08-14 (main 4f6132b):
  the coalesce half exists as library code (cow_rebuild.coalesce_*;
  config_pull.py transcribed the whole mechanism in one session, so
  the export CLI is ~a day), but the engine-side half is 0% and the
  existing loader is the wrong shape twice over — latest-only with
  no pin, FLAT single-layer (`where rule_set_id = ...`, no
  coalesce: works in seeds-only prod by luck; the day test's
  latest is a sparse P_ candidate, dual_read compares against a
  fragment and floods false mismatches — latent bug, worth
  mentioning as evidence), and rules+output_orders only (no
  entities/aliases/canonical markets/exchange settings; M2 parity
  needed only rule keys).  Crucially bq_snapshot's ONLY caller is
  dual_read — live classify reads no BQ yet, so there is no
  retrofit: the seam can be designed right from day one, which is
  the timing argument to put in front of Joe.
- **Ask 3**: no wall-clock reads, no ordering nondeterminism.
  Today's engine has the property (the MVP calibration verified
  it); previously only a phrase in this file, rationale recorded
  nowhere.  Sanity-checked 2026-08-14: for the new engine this is
  design-time-free like ask 2, but with concrete evidence of the
  hazard already in shipped code — load_market_rules queries with
  no ORDER BY (BQ row order is not guaranteed), and the MoV
  duplicate showed what accidental tie-breaking looks like (map
  100 vs ignore 50 is decided; two rules at EQUAL priority would
  be decided by arrival order).  dual_read's uuid/now usage is
  audit-only, not output — fine.  The double-run byte-compare
  acceptance is exactly what the MVP calibration does; Joe can
  crib run_engine.sh's mechanics.
- **Ask 4** originally asked for the seed snapshot format, even in
  draft — ANSWERED by shipped code 2026-08-13 (M1): the format
  exists (`mappers/seed/extract.py` + `BigQuery/
  mapping_rule_rows.py`, seeded snapshots in both BQ projects), so
  roadmap step 5 was unblocked (see its entry for design
  learnings).  The comment strategy is the remaining half: the
  seed harvests comments only into entity display names
  (`canonical_name`); verification provenance and block-scoped
  commentary do not migrate (market-rule `notes` verified null in
  prod).  Comments are functional data, and per-row `notes` is
  lossy for block-scoped commentary; see "Comment migration is
  unaddressed" in joe-redesign.md.
  CORRECTION 2026-08-13: the comment ask has NOT actually been
  raised with Joe (Greg).  Sizing done that day to support the
  ask, measured across all 59 config TOMLs (~4,550 comment
  instances, ~118K chars): 2,684 header display names DO migrate
  (but sloppily — provenance parentheticals pollute
  canonical_name, e.g. prod cricket_odi DUR = "Durham
  (KXODIMATCH-26AUG070830MIDDUR gap 2026-08-05)"); 1,053
  standalone provenance/warning/policy lines drop entirely; and
  ~59 "auto-stubbed/auto-pinned, unverified" state markers are
  dropped AND contradicted — verified in prod: VIB4
  (international_club_friendlies) is "# auto-pinned, unverified"
  in TOML but confidence="id_verified" in S0_cb85f20c3ad7.
  Confidence inflation is trader-facing post-M4; the fix is
  mostly easy (extractor already captures the comments; route to
  notes, map markers to a truthful confidence value); the only
  real design decision is block-scoped commentary (no receptacle
  at that scope; file preambles fit mapping_leagues.notes).
  The step-5 independent reader supersedes that sizing with exact
  counts at e1a7136: 4,938 comment instances, 3,100 migrate,
  1,838 lost — the number the gate prints as EXPECTED-LOSS every
  entity-audit run, and the burndown metric once migration lands.
  Sequencing decided with Greg 2026-08-14: WHEN this ask is taken
  up, comment harvesting should move from the two regexes to a
  comment-aware parser (tomlkit — new dependency, justified by
  standalone/block comments which regexes cannot reasonably
  reach); the quoted-key display-name bug (ask 9) gets its
  one-line fix NOW and falls out of the parser
  move automatically later.  Side benefit: the harness's
  independent TOML reader stays regex-based, so reader↔extractor
  redundancy becomes genuinely diverse instead of copied regexes.
  Sanity-checked 2026-08-14 (how much is done): the harvest point
  exists (seed/entities.py already reads the full TOML text — the
  regexes scan it), the destination columns exist and sit null
  (notes on entities and market rules, verified in prod), and the
  display-name channel already works for bare keys — what is
  missing is routing, marker honesty, and the block-scope
  receptacle.  Open detail for piece (c): a truthful marker
  mapping may need a NEW allowed confidence value — the only
  values observed in the IR are "id_verified" and "semantic", and
  unverified must not masquerade as either.
- **Ask 5** (provenance columns; old ask 6 — old ask 5 was
  subsumed into ask 1): sanity-checked 2026-08-14 — the inputs all
  exist (rule_id content-addressed and stable across all 8 seeds,
  confidence on every rule/alias row, rule_set_id names the
  layer), the engine holds the matched rule at emit time, and
  today's kalshi_gaps categories are the reason-code precedent;
  the output side is design-time-free and purely additive to the
  --json format.  `project.py`'s reader/writer split note in
  "Suggestions" below is this ask's harness-side counterpart.

## Suggestions made along the way (assess, don't assume)

Accumulated during design; none are commitments.  A fresh agent
should assess each against the code as it now stands, and raise with
Greg rather than silently implement:

- **Line-kind refactor precedes baseline blessing** so the assertions
  validate the corpus before outputs are frozen (also in
  joe-redesign.md review).
- **Differ should refuse mismatched league restrictions** (parse the
  `.mlb.` vs `.all.` cache-key segment from filenames, or embed a
  header line in the canonical file).
- **Differ "witnessed vs unwitnessable" verdicts** once the manifest
  exists: distinguish "no delta, change not witnessable by this tick"
  from "witnessed, no change".
- **`gold_row`/gold files** — RESOLVED 2026-08-07: one-off audit
  against current main, then retire; folded into roadmap step 3.
- **Asks on the redesign engine** — PROMOTED 2026-08-11 to the
  "Asks on the redesign engine" section above (expanded with status
  and rationale; nothing dropped).
- **`project.py` reader/writer split** when a second emit format
  appears: the canonical-form writer half is the contract and must
  not fork; only the record-walking reader half may.  Redesign
  provenance columns (verify_tier, rule ids, reason codes) should
  ride through as non-compared annotations to enrich delta reports —
  raw material for waiver predicates.
- **Per-SHA venvs** in `run_engine.sh` for SHAs far apart in
  dependency history (currently shares the repo venv — fine for
  nearby SHAs only).
- **Shell smoke test** for `run_engine.sh` arg handling (the bash-3.2
  bug argues for it; shell is where test discipline is weakest).
- **`MANIFEST.sha256` in the bucket** — DONE alongside step 1
  (plus `MANIFEST.md5` for no-download bucket audits); sizes live
  in `manifest.toml` per tick.
- **Non-corpus data extras are laptop-only again** after being
  removed from the bucket (`world_cup/`, crypto.com dumps,
  `predict_mapping_json.json`, `PredictDataDictionary.xlsx`): if any
  matter, upload deliberately to an `aux/` prefix.
  `data/scripts/validate_team_total_ids.py` probably belongs in git.
- **Coverage thinness warning** for the manifest: crypto files are
  EMPTY in most June ticks (real crypto coverage starts ~2026-07-13);
  polymarket ~6 ticks; runshop effectively world_cup only.
- **Reports to the bucket** (`reports/<run_id>/`) once A/B runs
  start, as the burndown history.

## Invariants to preserve

- `regression/` never imports from `mappers/`; engines run as
  subprocesses in SHA-pinned worktrees.
- The canonical comparison form only changes with a deliberate,
  reviewed contract change (it invalidates cached projections and
  baselines — version it if it must move).
- The corpus and its caches are read-only mirrors; new ticks flow
  laptop/VM → bucket → caches.
- Acceptance for migration gates is zero UNEXPLAINED deltas, not
  zero deltas.


---

## Appendix: "Make line first class" (from Greg's review in docs/joe-redesign.md)

Moved here 2026-08-14 when joe-redesign.md was deleted.  DECIDED
with Greg the same day: this is NOT an ask for Joe — the redesign
is too far along for a precondition refactor, so any line-semantics
change lands post facto (an engine_contract_version bump).  Kept
because the correct-score observation may still inform the
redesign's identity model.  Original text:

### Make line first class

`line` is today a bare `float | None` on `CanonicalRow` whose meaning
(present? signed? what encoding?) is borrowed from `Shape` via comments
only — nothing machine-checks that a SPREAD row carries a signed line or
that a MONEYLINE row carries none. Scope and Shape are first-class enums
the code dispatches on; line should get the same treatment, e.g. a
`line_kind` attribute on `Shape` (`NONE` / `SIGNED` / `THRESHOLD` /
`SCORELINE`) with a single shared assertion at row-build time. In this
redesign that matters doubly: the BQ `market_mapping.line` column and the
side/line verify tier need a declared interpretation that rule reviewers
can read from the contract, not reconstruct from parser comments.

Sequencing: this is a refactor of the *current* code and should land
separately, **before** the redesign — arguably as a precondition. Done
now it is a pure refactor (enum attribute + one shared assertion site,
zero-diff verifiable against the gold corpus), and the redesign's v1
engine contract then includes line semantics from day one. Retrofitted
later it becomes an `engine_contract_version` bump plus snapshot
migration. It should also precede baseline blessing, so the assertions
validate the corpus before its outputs are frozen as gold.

**Note — review the correct-score hack.** `correct_score_line()` packs a
discrete scoreline pair into the float (`winner + loser/100`) purely
because line is the free numeric slot in the merge key, and
`optic_verify._line_disagrees` must carve out that shape. This is an
example of a merge-key dimension being overloaded, and there may be more
of its kind — we have already seen H2H need `grouping_key` added for the
same "key needs another dimension" reason. Rather than patching each case
ad hoc, the redesign should adopt a general handling strategy for markets
whose identity doesn't fit `(entity, line, side)`.

---

# Findings recorded after the archive

## 2026-08-14 — Oli's synthetic fixtures vs the harness

Joe flagged that Oliver's synthetic-fixtures work (merged to main
and test, `feat/synthetic-fixtures`) might be an issue for the
harness.  Assessed against the shipped code the same day; verdict:
**the harness is structurally insulated today — no change needed.
Two forward obligations recorded in plan.md** (roadmap step 7 and
the config_project contract-v2 note).

What the pipeline is: a standalone cron on the mapper VM
(`synthetic/run.py`, schedule in `infra/crontab`, config in
`synthetic/series.toml`) that mints `wsdsyn-<event_ticker>`
fixture rows and mapping rows directly into BQ
(`opticodds_us.opticodds_fixtures` + `market_mapping`) for Kalshi
markets Optic has no fixture for — ITF doubles and no-fixture
singles — so they can be priced in-play off the Kalshi book.

Why the harness is insulated (each point checked, not assumed):

1. **The engine never runs synthetic code.**  Generation is an
   out-of-band cron, not part of `mappers.run`; the mapper
   pipeline has zero references to the package or the `wsdsyn`
   prefix (the one grep hit, in `optic_verify.py`, is an
   unrelated "synthetic float" comment about correct-score
   lines).
2. **Synthetic leagues are deliberately out of mapper `LEAGUES`**
   ("this job, not the mapper, writes their rows" — synthetic
   README); only `mappers/seed/profiles.py` knows the doubles
   keys.  A replayed engine at any SHA cannot classify or emit
   synthetic rows.
3. **wsdsyn rows cannot leak into corpus ticks** — three
   independent barriers: recorded `optic_fixtures_odds.jsonl`
   comes from the Optic API fetch; the only BQ-sourced fixture
   path (`BigQuery/optic_from_bq.py` via `run_pipeline_bq.sh`)
   filters `--sport soccer` while synthetic rows are
   `sport_id="tennis"`; and the BQ pipeline stages under
   `data_bq/`, outside the corpus's `data/` namespace.
4. **Config-equivalence audits are blind to it, correctly.**
   Synthetic touches only `mapping_leagues` (two
   `fixture_source=synthetic` league rows via
   `seed/synthetic_leagues.py`, merged by `extract_snapshot`),
   and mapping_leagues is deferred out of contract v1; the
   audits also target e1a7136, which predates synthetic.
5. **No determinism hazard.**  IDs are `wsdsyn-<ticker>`, start
   dates pinned to 00:01Z — nothing random enters any table the
   harness will ever compare.

The two forward obligations (one-liners live in plan.md where
they will trigger):

- **Roadmap step 7 (forward parallel runs):** live
  `market_mapping` now has a third writer that is neither engine
  A nor engine B; the live diff must exclude
  `game_id LIKE 'wsdsyn-%'` rows or the gate reports deltas no
  engine produced.  The job's reconcile is delete-then-insert,
  so a live sampler can also catch sub-second absence windows.
- **Config contract v2 (when mapping_leagues joins):**
  `synthetic/series.toml` becomes a second repo-config source
  feeding the snapshot.  Both audit sides derive from the same
  `extract_snapshot`, so equivalence holds mechanically, but the
  "config = the config/ dir" assumption widens; and the next
  reseed (the one absorbing asks 6/8/9) adds the two doubles
  league rows — an expected delta, invisible to v1.

Cheap empirical confirmation available on demand: the blessed
smoke baseline (fb4154c) predates the synthetic merge, so a
smoke-tier gate run of any post-synthetic SHA doubles as an
engine-drift check across the whole synthetic window.
