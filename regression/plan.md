# Regression harness — plan and state

The equivalence gating for the mapping redesign, written for Joe
(and his agent): what the harness is, what is built on branch
`regression-harness`, and what we ask of the redesign.  Module
docstrings carry the detailed contracts — the code is the
reference.  The full build diary, calibration evidence, findings,
and decision log are archived verbatim in `HISTORY.md`.

## Why this exists

The migration from Python/TOML config to the BQ-rules engine needs
an acceptance test stronger than "looks right": run old and new on
identical inputs and explain every difference.  Two consumers:

1. **Refactor gate for the current mapper** — a refactor claims
   zero behavior change; the gate proves it (zero diff over a
   corpus of historical ticks).
2. **Migration gate for the redesign** — old engine + TOML config
   vs new engine + BQ snapshot on identical historical inputs.
   Two-stage, so deltas stay attributable: first DATA equivalence
   (the BQ snapshot is a faithful transcription of the repo
   config — no engine involved), then ENGINE equivalence (both
   engines on the same tick with equivalent rules, diffing the
   would-be published rows pre-load).  Config-transcription errors
   must never masquerade as engine bugs.

The engine A/B diff is expected non-empty BY DESIGN — the new
pipeline fail-closes harder — so acceptance is zero UNEXPLAINED
deltas, never zero deltas: every delta is MATCHED, WAIVED under a
reviewed and bounded excuse, or the gate fails.

## What is built

All of it on branch `regression-harness`, in `regression/` (121
tests, pyright clean, and held to the repo CI quality gate —
bandit, size, and docstring floors — since 2026-08-14).  `regression/` never imports `mappers/`;
engines and extractors run as subprocesses in SHA-pinned worktrees,
and config is only ever read through git objects — never a working
tree.

### Engine regression gate

- **Corpus**: 183 historical fetch ticks (2026-03-06 → 2026-08-13,
  ~7.2 GB) in `gs://rs-marketmaking-mapping/corpus/`, with
  sha256/md5 manifests and per-tick witnessability metadata
  (`manifest.toml`); a `smoke` tier (9 ticks, one per era ×
  exchange-mix) and `full` (everything, the pre-flip gate).
  Four August 2026 ticks (added 2026-08-14, from the prod VM,
  chosen from 12 candidates by marginal-coverage analysis) carry
  the league-expansion era — NFL, NPB, KBO, esports, cricket,
  boxing, CFL, the European cups, and the long-tail soccer
  leagues; 2026-08-12/12_18 joined the smoke tier, blessed at
  fb4154c.  CAVEAT: the August ticks have no gold, so unlike the
  original smoke set their baselines assert "matches legacy",
  NOT "legacy is correct" — on the expansion leagues especially,
  legacy behavior is pinned sight-unseen and a gate PASS
  inherits that caveat.
  `corpus.py` materializes ticks with verify-on-every-use — a hash
  mismatch aborts, drift can never silently change results.
- **`run_engine.sh` + `project.py`**: SHA → worktree →
  `mappers.run <tick> --json` → canonical comparison lines
  (contract v2: 9-field bet key × sportsbook stamp, including the
  optic source_ids passthrough), cached by (sha, tick, leagues,
  contract version).
- **`bless.py` / `gate.py` / `diff.py` / `waivers.py`**: blessed
  baselines in the bucket (smoke tier at main fb4154c); candidate
  vs baseline gating under seven-rule waivers — narrow by
  construction, exact ceilings, breach waives nothing, expiry
  forces renewal commits, every count printed.

### Config-equivalence suite (migration stage 1 — complete)

Five modules sharing one comparison contract:

- **`config_project.py`** — the contract (v1): one canonical line
  per market_rule / entity / alias / canonical_market; equality on
  (kind, key, values); annotations ride along so delta reports are
  self-explaining.  mapping_leagues deferred — and when it joins
  (contract v2), `synthetic/series.toml` is a second repo-config
  source: the reseed adds two `fixture_source=synthetic` league
  rows, an expected delta invisible to v1 (finding 2026-08-14,
  HISTORY.md).
- **`config_pull.py`** — side B: BQ rule snapshot → canonical
  lines; COW-aware (tip→root coalesce, tombstones, loud on every
  integrity violation); cached forever, snapshots being
  append-only.
- **`config_extract.py`** — side A: git SHA → worktree → seed
  extractor subprocess → canonical lines.
- **`config_toml.py`** — independent TOML entity reader: a second
  transcription of the alias TOMLs that owes nothing to the
  extractor, so extractor bugs surface as deltas; also counts
  comment instances (the EXPECTED-LOSS number).
- **`config_diff.py`** — the gate: both-direction set diff,
  MATCHED / WAIVED / EXPECTED-LOSS / UNEXPLAINED, exit 0 iff no
  UNEXPLAINED; waiver files are mechanically bound to the one
  audit they were reviewed for.

### Current audit facts (2026-08-14)

- **Prod seed S0_cb85f20c3ad7 is a faithful transcription** of the
  config at e1a7136: 13,857/13,857 lines match, zero deltas both
  directions.  Note the scope: this proves LOADER fidelity, not
  extractor fidelity — an extractor bug lands identically on both
  sides of that comparison; the independent TOML reader exists to
  break exactly that tautology.
- **The seed's stamped source_revision (a0ffe0c) is wrong**: 73
  lines postdate it — it was seeded from a dirty working tree
  (ask 8).  Until a clean reseed, seed audits target e1a7136.
- **The extractor loses quoted-section display names**: 40
  entities seed canonical_name null (ask 9), covered meanwhile by
  audit-bound waivers.
- **1,838 of 4,938 TOML comment instances do not migrate**
  (ask 4); printed as EXPECTED-LOSS on every entity audit — the
  burndown metric for the comment-migration work.
- **Test tip P_0eccd9b1a539 carries 43 console edits** over its
  seed — the tip audit's triage list; zero A-only lines, so no
  TOML content has been lost in the console era.

## Asks for Joe

All nine asks, uniquely numbered: 1–5 on the redesign engine, 6–9
on the current seed pipeline.  None have been raised with Joe yet —
this document is their first delivery, as a complete set.  Every
ask was sanity-checked against the shipped code on 2026-08-14; the
evidence and status commentary are archived in `HISTORY.md`
("Redesign asks — background and status" and the roadmap step-5
entries).

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
   today) — drive it to zero.  Scoping, a worked example, and the
   tomlkit approach: "Ask 4 worked notes" below.  (Recast
   mechanically 2026-08-14.)

Cheap win — worth doing early, not blocking:

5. **Put provenance on every output row: the matched rule_id per
   exchange stamp, the snapshot rule_set_id, and a reason code on
   every skip/gap.**  A gate delta then names the rule that
   caused it — triage becomes a lookup instead of a hunt, and
   waiver predicates get real fields.  Additive fields on the
   --json format, so no conflict with ask 1.

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

## Ask 4 worked notes — comment migration without the rabbit hole

Analysis recorded 2026-08-14 so the scoping does not have to be
rediscovered.  The risk in ask 4 is scoping, not technique: the
open-ended version — a general comment-preservation layer for
arbitrary TOML (attachment rules in full generality,
round-tripping, future-proofing) — is a rabbit hole and should
not be built.  The bounded version rests on the comment corpus
being finite and mechanically counted: 4,938 instances, 1,838
lost today, printed on every entity audit.  Write the harvester
against the shapes that actually exist and let the counter be the
definition of done; any ambiguous attachment shows up as residual
count and is resolved by reading the file, case by case.

Why it matters, in one entity
(`config/international_club_friendlies/team_aliases.toml`):

    [MAL]  # Malaga -- Optic abbreviation is MAL, Kalshi uses MCF
    # gap:KXCLUBFGAME-26AUG12MCFFUL (Malaga vs Fulham).  Superseded
    # stub: an earlier fixture auto-stubbed this club as [MCF]
    # because Optic shipped abbreviation "MCF" for it at the time;
    # Optic has since switched to "MAL", which the pipeline keys on.
    kalshi = ["MCF"]

What survives in BQ today is `MAL -> kalshi ["MCF"]`, confidence
`id_verified`.  The comment IS the verification provenance: why a
club maps to a wrong-looking ticker code, the fixture that proves
it, and the fact Optic already flipped its abbreviation once.
After cutover the file is deleted and the console shows an
inexplicable alias — if Optic flips back, or someone tidies it,
the mapping breaks with no trail.  Sharper still: the ~59
"auto-stubbed, unverified" markers seed `confidence="id_verified"`
— the database actively claims a human verified a machine guess.
Piece (c) is therefore a data-correctness bug, not comment
migration.

Every comment class has a destination that already exists — no
schema work, only plumbing:

- header trailing comment (`[ABL7]  # Alexander Blockx`) ->
  `canonical_name` — already migrates (~3,100 of 4,938);
- standalone block on a section (the Malaga story above) ->
  entity notes — the console schema already writes
  `entity.notes` (`bq_store.py`); it sits null only because
  `EntityIR` does not carry the field;
- `# auto-stubbed, unverified` -> a truthful `confidence` value
  on `AliasIR` (the field exists; the value is hardcoded today);
- file preambles ("Only list a team here once a REAL Kalshi
  ticker proves its code diverges") -> `mapping_leagues.notes`
  (`LeagueIR.notes` exists) — this is the one design decision,
  piece (e).

Technique: tomlkit parses losslessly, and the whole harvester is
one walk of `doc.body` — a table's header comment is
`item.trivia.comment`, standalone comments ride in the body as
`Comment` items, a value's trailing comment is
`value.trivia.comment`.  Replacing the two `entities.py` regexes
with this walk also subsumes the ask-9 quoted-key bug (the
interim one-liner still lands first, per ask 9).  Expected size:
on the order of a hundred lines plus tests.  Offline-only (seed
extractor — a mistake costs a reseed, not an incident),
incremental (each migrated class shrinks the counter; display
names are already done), and non-blocking (asks 1-3 gate the
migration; this one's deadline is "before the TOMLs are
deleted").

## Standing exceptions (all self-retiring)

Every known defect is carried as a visible, bounded, self-retiring
exception — never silently green:

- **`config_pull.KNOWN_STALE_ROWS`** drops the stale ufc MoV
  ignore on both sides (ask 6).  Every drop prints; when the fix
  lands the pin reports itself stale for deletion; expired and
  still matching is a hard error.
- **`config_waivers.toml`** carries the four quoted-key
  display-name waivers (ask 9), bound to the reader-vs-extractor
  audit; they go stale the day the fix lands.
- **Seed audits of S0_cb85f20c3ad7 target e1a7136**, not its
  stamp (ask 8); the next clean reseed ends the exception.
- **`[comment_loss]`** is the standing EXPECTED-LOSS account
  (ask 4); its count shrinks as comment migration lands.

## Remaining roadmap

6. **Engine A/B with waivers (migration stage 2)** — old vs new
   engine over corpus ticks: smoke tier per iteration, full corpus
   at milestones; UNEXPLAINED count per league×sportsbook over
   time is the migration burndown.  Blocked on asks 1–3.
7. **Forward parallel runs** — the same projector/differ pointed
   at two live outputs per tick on the VM.  The BQ MERGE/load path
   is out of scope until here.  NOTE: live `market_mapping` now
   has a third writer — the synthetic-fixtures cron (Oli,
   2026-08) — so the live diff must exclude
   `game_id LIKE 'wsdsyn-%'` rows, and its delete-then-insert
   reconcile can create sub-second absence windows a live sampler
   could catch (finding 2026-08-14, HISTORY.md).

Working mode (Greg's explicit preference): one step at a time,
each step reviewed and understood before the next.

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
