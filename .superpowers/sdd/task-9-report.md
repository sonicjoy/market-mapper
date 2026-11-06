# Task 9 report: two production-wiring gaps (fetch/optic.py SUPPORTED_LEAGUES, pipeline.run() team_aliases.toml)

**Status:** complete, not blocked.

## Gap 1 — fetch/optic.py league support

**Approach: derived from the wired registry** (the strongly-preferred option; no import cycle). `fetch/optic.py`'s `SUPPORTED_LEAGUES: dict[League, OpticConfig]` is now built as
`{league: cfg.OPTIC for league, cfg in mappers.run.LEAGUES.items()}` instead of nine hand-maintained
`from mappers.leagues.X import OPTIC as X_OPTIC` lines + a parallel literal dict. Verified no cycle:
neither `mappers/run.py` nor any `mappers/leagues/*.py`/`mappers/pipeline.py` imports `fetch.*`.
`--league mls|liga_mx|ucl` now resolves via argparse (`choices=sorted(SUPPORTED_LEAGUES)`) and looks
up the correct `OpticConfig` (`league_id="usa_-_major_league_soccer"` / `"mexico_-_liga_mx"` /
`"uefa_-_champions_league"`) automatically — future leagues wired into `mappers.run.LEAGUES` are
fetchable with zero changes to this file, closing the drift vector for Wave 5 (wnba/ufc).

Also added the 3 missing `LEAGUE_SECRET` entries (`League.MLS/LIGA_MX/UCL → "opticodds_access_key"`,
same non-tennis key every other soccer league uses) — `init_headers(league)` indexes this dict
separately from `SUPPORTED_LEAGUES`, so deriving only the latter would still `KeyError` at fetch
time for these three leagues. `LEAGUE_SECRET` itself stays hand-maintained (out of this task's
explicit derive-ask), see Concerns.

Verified end-to-end at the argparse/config-resolution level (no live network access assumed):
built the same parser fetch/optic.py's `main()` builds and parsed `--league mls|liga_mx|ucl` — all
three resolve cleanly, no `SystemExit`/`invalid choice`.

## Gap 2 — pipeline.run() team_aliases.toml requirement

**Root cause was NOT `load_aliases`.** Read `mappers/shared.py::load_aliases` first per the brief:
it already returns `AliasData({}, set())` for a missing file (`if not path.exists(): return
AliasData({}, set())`) — no crash there, and `player_aliases.toml`'s load is identically tolerant
(no downstream completeness check consumes it outside the PX/Kalshi/crypto sections, which are
already gated on `league.PX`/`league.KALSHI`/`league.CRYPTO` being non-`None`).

The actual hard-require was the **completeness assertion** at the old `pipeline.py:828-837`: `if
missing_from_toml: raise ValueError(...)` ran unconditionally on `optic_teams - team_canonicals`.
For a poly-only league (no toml file → `team_canonicals == set()`), every Optic team abbreviation in
the fixture data is "missing" → guaranteed raise, regardless of KALSHI/PX/CRYPTO all being `None`
(i.e. regardless of whether anything actually needs `team_canonicals`). Reproduced this exactly pre-fix
(`ValueError: Optic abbreviations not in team_aliases.toml: [DAL]\n[HOU]`) using a synthetic MLS
fixture in a tmp cwd with no `config/mls/team_aliases.toml`, confirming the diagnosis before touching
code (TDD red).

**Fix:** guarded the whole completeness block on `toml_path.exists()`. Every currently-wired league
that needs completeness enforcement (ATP/EPL/MLB/NBA/NCAAB/NFL/NHL/WTA/WORLD_CUP) ships a real
`config/<league>/team_aliases.toml` on disk today, so `toml_path.exists()` is `True` for all of them
— behavior is byte-identical for every existing league. Only a league with **no file at all** (the
poly-only case) skips the check; a league whose file exists but is incomplete (or even present-and-
empty) still raises exactly as before — verified by dedicated regression tests (see below).

## Scratch cleanup

`config/mls/` (the untracked Task-8 validation stub, `git status` showed `?? config/mls/`) is
**deleted**, not committed. It's unnecessary now: the Gap-2 fix means a poly-only league needs no
`team_aliases.toml` at all.

## Files changed

- `fetch/optic.py` — `SUPPORTED_LEAGUES` now derived from `mappers.run.LEAGUES`; added 3
  `LEAGUE_SECRET` entries (MLS/LIGA_MX/UCL).
- `mappers/pipeline.py` — `run()`'s team-alias completeness check gated on `toml_path.exists()`.
- `tests/fetch/test_optic_supported_leagues.py` — new: registry-derivation invariant, the 3
  expansion leagues resolve to their real `OpticConfig.league_id`, `LEAGUE_SECRET` coverage,
  argparse-choices membership.
- `tests/mappers/test_pipeline_alias_absent.py` — new: `load_aliases` missing/present-file contract
  (documents the pre-existing correct behavior), `pipeline.run()` no-crash for a poly-only league
  with an absent `team_aliases.toml` (both a dir with no toml and no `config/mls/` dir at all), and
  two regression guards that `run()` still raises when the toml is present-but-incomplete or
  present-but-empty (proves the fix only relaxes the truly-absent case).
- `config/mls/` — deleted (was untracked scratch; not part of the commit).

## Test counts

- New tests only: `tests/fetch/test_optic_supported_leagues.py` → 4 passed. `tests/mappers/
  test_pipeline_alias_absent.py` → 6 passed. Both confirmed RED before the corresponding fix, GREEN
  after (TDD).
- `tests/fetch/` full: 32 passed (28 baseline + 4 new), `GCP_PROJECT=marketmaking-test` (required —
  `fetch/optic.py` reads it at import time; unrelated to this task).
- `tests/mappers/` full (the brief's stated gate): **496 passed, 11 skipped** (490 passed/11 skipped
  baseline + 6 new; no test dropped, no skip count changed, goldens unchanged — no golden-comparing
  integration test touched).
- `tests/` (whole repo) full: 573 passed, 11 skipped.

## Lint

`ruff check --fix` run on all 4 changed/new files. New test files: clean, zero findings.
`fetch/optic.py` and `mappers/pipeline.py`: `--fix` auto-fixed the import-block reordering that fell
out of editing those import lines (unavoidable — isort reorganizes the whole contiguous import block);
I manually reverted two *unrelated* auto-fixes it also applied elsewhere in the same files (a
`clean_odds` `SIM114` if/elif merge, and a `UP017` `datetime.UTC` alias swap) since those touch code
I never intended to change — confirmed both are **pre-existing** findings (present on `git show
HEAD:fetch/optic.py` before this task) by diffing `ruff check` output against the pre-task blob, and
restored them to their original form. Final `ruff check` (no `--fix`) on both changed files shows only
those same pre-existing, line-unmoved findings (`fetch/optic.py`: E402/SIM114/B011/UP017 at their
original locations; `mappers/pipeline.py`: SIM108/UP014, both far from and unrelated to the edited
block) — nothing new introduced by this diff.

## Concerns

- `LEAGUE_SECRET` in `fetch/optic.py` is still a hand-maintained dict (only `SUPPORTED_LEAGUES` was
  asked to be derived). It would drift the same way for a Wave-5 league that isn't a soccer/non-
  tennis default — a `league.sport == Sport.TENNIS` derivation would close this too, but was left
  alone as out-of-scope for this task.
- Did not re-verify `fetch.optic --league mls --out-dir ...` against the live OpticOdds API (needs
  GCP secret access / network, optional per the brief) — verified the fix at the argparse +
  `OpticConfig` resolution layer instead (unit tests + a standalone parser smoke check reusing
  `fetch.optic`'s own `SUPPORTED_LEAGUES`).
- No new `config/liga_mx/` or `config/ucl/` directories were created — correct per the "no
  placeholder TOMLs" mandate; neither league needs one now.
