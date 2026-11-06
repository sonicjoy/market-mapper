# Task TN2 report — per-question-form name-granularity mechanism

Scope: ONLY the shared mechanism (option 1 from
`wave-tennis-probe-findings.md` section C.2). No tennis recognizer,
MarketType, or league config touched (separate later task).

## Mechanism

**Field**: `ParsedMarket.name_granularity: Literal["full", "surname"] = "full"`
(`mappers/exchanges/polymarket.py`). Every existing rule/market never sets
it, so every existing `ParsedMarket` construction is unaffected.

**Helpers** (new, next to `_name_match`/`_norm_name` in `polymarket.py`):

- `_match_name(poly_value, fixture_name, style, granularity) -> bool`
  — `granularity="full"`: reduces to exactly
  `_name_match(poly_value, _norm_name(fixture_name, style), style)`, the
  literal call pattern every consumer used before this task.
  `granularity="surname"`: compares `_norm_name(poly_value, style)` against
  `_norm_name(fixture_name, style).rsplit("_", 1)[-1]` (last underscore-token
  of the normalized full name — reproduces the probe's "last whitespace
  token" convention; hyphenated names like `"Auger-Aliassime"` stay one
  token since `normalize_player_name` never splits hyphens).
- `_fixture_surname_collision(home_name, away_name, style) -> bool` — true
  when a fixture's two competitors share the same last-token surname (e.g.
  two "Silva"s); the collision guard used by all three consumers.

**Three threaded consumers** (all read `parsed.name_granularity` /
`granularity` computed from it):

1. `build_rows`'s `TEAM_LABEL` branch — outcome-label→competitor resolution
   now calls `_match_name(lab, home_name/away_name, style, granularity)`
   instead of `_name_match(lab, _norm_name(home_name, style), style)`; gated
   by a `_fixture_surname_collision` guard when `granularity=="surname"`.
2. `build_rows`'s `SPREAD_TEAM` branch — **both** the entity→competitor
   resolution (as the task named) **and** the per-outcome label→competitor
   resolution loop in the same branch, threaded identically. See "Deviation"
   below for why the outcome-label loop was included too.
3. `pipeline._match_poly_fixture` — reads `parsed.name_granularity` directly
   (no signature change needed; it already receives `parsed`).
   `granularity != "surname"` runs the **exact original loop, byte-for-byte,
   in its own branch** (not refactored/merged) so "full" is provably a
   no-op. `granularity=="surname"` runs a new collision-safe variant.

## Backward-compat guarantee for `"full"`

- `_match_name`'s `"full"` arm is textually `_name_match(poly_value,
  _norm_name(fixture_name, style), style)` — identical to what every
  pre-existing call site did inline.
- The new `_fixture_surname_collision` guards in `TEAM_LABEL`/`SPREAD_TEAM`
  are gated behind `if granularity == "surname"` — never evaluated/branched
  into for `"full"`.
- `_match_poly_fixture` keeps the **original loop verbatim** under an
  `if granularity != "surname":` branch (not a refactor sharing code with the
  surname path) — zero risk of subtle short-circuit/ordering drift.
- Full-suite regression: 608 pre-existing tests all still pass, 13 skips
  unchanged (see Tests below) — every existing market defaults to `"full"`
  and its goldens are untouched.

## Collision guard (flip-safety)

Two independent ambiguity sources, both required to DROP (never guess):

1. **Within one candidate fixture**: `_fixture_surname_collision` — if a
   fixture's home/away competitors share the same last-token surname, ANY
   surname-based resolution against that fixture is inherently ambiguous.
   `build_rows` returns `[]` immediately; `_match_poly_fixture` skips that
   fixture entirely (`continue`) before running the name-match test.
2. **Across fixtures**: `_match_poly_fixture`'s surname branch collects
   **all** matching fixtures (exact-date tier first, then ±1-day fallback
   tier) instead of returning on first hit; if either tier has more than one
   match, returns `None` rather than the first one found.

## Deviation from the literal task text (flagged, not a BLOCKED mismatch)

The task named 3 consumers, listing only "SPREAD_TEAM `entity`→competitor
resolution." Reading the actual branch (`mappers/exchanges/polymarket.py`,
`build_rows`'s `SPREAD_TEAM` mode), the SAME branch also loops over
`outcomes` matching each `outcome_label` against `home_name`/`away_name` —
structurally identical to `TEAM_LABEL`'s per-outcome resolution, just
un-named in the task's bullet list. Per the probe (`set_handicap` — B.5),
poly's outcome labels for this exact form are ALSO surnames (`"Gojo"`,
`"Bu"`), so threading granularity into the entity check alone would leave
the per-outcome loop doing exact full-name comparison and the branch would
never resolve for the future `set_handicap` recognizer. I threaded
granularity into both resolution sites within `SPREAD_TEAM` (same value,
`parsed.name_granularity`, used consistently for both) so the mechanism is
actually usable for its stated purpose. This is additive within the named
consumer, gated by the same `"full"`-default no-op guarantee, and is
directly exercised by the required test ("A SPREAD_TEAM entity surname
resolves") — that test could not pass with entity-only threading, since the
outcome labels in the test are surnames per the probe's own convention.

## Files changed

- `mappers/exchanges/polymarket.py` — `ParsedMarket.name_granularity` field;
  `_match_name` + `_fixture_surname_collision` helpers; `TEAM_LABEL`/
  `SPREAD_TEAM` branches in `build_rows` threaded.
- `mappers/pipeline.py` — `_match_poly_fixture` threaded (granularity-gated
  branch, original loop preserved verbatim for `"full"`).
- `tests/mappers/test_name_granularity.py` — new, 22 tests.

## Tests

New file: **22/22 passed** (`-x -q`) — field default/override,
`_match_name` unit tests (surname match, wrong-player rejection, hyphenated
surname, full-mode byte-identical-call proof, full-mode-rejects-surname
proof), `_match_poly_fixture` (surname resolve, either orientation, full
default rejects surname pair, cross-fixture collision drop, within-fixture
collision drop, full-mode regression), `build_rows` `TEAM_LABEL`/
`SPREAD_TEAM` (surname resolve, full-mode rejects surname label, full-mode
regression, collision drop for both branches), `dataclasses.replace`
preserves the field (relevant since `_resolve_poly_markets`'s Phase B uses
`replace(parsed, date=...)`).

Full suite: `tests/mappers/ -q` → **630 passed, 13 skipped** (baseline before
this task: 608 passed, 13 skipped — exactly `608 + 22 new = 630`; skip count
unchanged). No existing test moved pass↔fail; all goldens byte-identical.

## Lint

`ruff check --fix` on `mappers/exchanges/polymarket.py`,
`mappers/pipeline.py`, `tests/mappers/test_name_granularity.py`: 2 findings
in `pipeline.py` (`SIM108` line ~153, `UP014` `MarmadMatch` NamedTuple syntax
~1276), confirmed via `git stash`/re-run against the pre-task commit to be
**pre-existing on `HEAD` already, at the same (line-shifted) locations** —
unrelated to this task's diff, not introduced by it, left untouched (not in
scope). `polymarket.py` and the new test file: **all checks passed**, 0
findings.

## Concerns

- The one deliberate deviation (SPREAD_TEAM's per-outcome loop, not just
  `entity`) is documented above — flagging in case the next task's author
  expected literal-scope-only threading; I believe extending it was
  necessary and correct, not scope creep, since it's the same named branch
  and the same single `name_granularity` value applied consistently.
- `_resolve_entity` (used by `OVER_UNDER`/`YESNO` TEAM-scope entity
  resolution) was deliberately NOT threaded — none of the 4 upcoming tennis
  forms use TEAM-scope `OVER_UNDER`/`YESNO` (match_total_games/set_games are
  `Scope.GAME`, whose `_resolve_entity` path returns `(True, None)` without
  any name matching at all), so threading it would be speculative,
  untestable scope creep. Flagging so the next task knows this path is
  intentionally still full-name-only/scope-GAME-only.
- ITF's 8 real surname collisions (probe section C.2) are not exercisable
  today since ITF isn't wired into any league config — the collision guard
  exists and is tested (2 synthetic collision tests) but has no live traffic
  to prove itself against yet.
