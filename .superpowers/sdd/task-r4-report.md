# Task R4 report: poly "Exact Score" <-> optic `correct_score`

**Status:** complete, not blocked.

Scope per the brief: the one rescue-tier form that genuinely EXTENDS the
otherwise-frozen `build_rows` dispatch on BOTH exchange modules — poly
"Exact Score: <A> N1 - N2 <B>?" onto Optic's `correct_score` market_id.
2,284 rows, ~27% of poly soccer, the single biggest dropped soccer form
(`wave-rescue-probe-findings.md` sections A.1/B.1).

## Canonical score-key representation (the crux)

Both branches emit the SAME `(market_type, entity, line, side)` — the merge
key `pipeline.row_key` uses:

- `market_type` = `"correct_score"`
- `entity` = `None` (GAME scope)
- `side` = the **winner's** fixture abbrev (e.g. `"ATX"`), or `TIE_SIDE`
  (`"_TIE"`) for a draw — same convention THREE_WAY/moneyline already use.
- `line` = a numeric encoding of the winner-anchored scoreline:
  `winner_goals + loser_goals / 100.0` (a new shared helper,
  `mappers.shared.correct_score_line`). E.g. a 2-1 result (either team) ->
  `2.01`; a 1-1 draw -> `1.01`; a 10-2 result -> `10.02`.

**Why not a literal `"W:L"` string in `line`:** `CanonicalRow.line` is typed
`float | None` (pydantic-validated — confirmed empirically: assigning the
string `"2:1"` raises `ValidationError: unable to parse string as a number`
before any of this code even runs). The brief's design intent — "side=team/
draw, scoreline differentiates rows sharing that side" — fits the existing
`(market_type, entity, line, side)` key perfectly; only the *field type* for
the scoreline needed resolving, not the join shape. `loser_goals` is always
a realistic single/double-digit soccer score (<100), so
`winner_goals + loser_goals/100` is a lossless, collision-free, order-
preserving encoding, computed by ONE shared function (`mappers/shared.py`)
that both `optic.build_rows` and `polymarket.build_rows` call, so the two
branches can never drift apart on the encoding. This was judged an
engineering-discretion call, not a join-semantics mismatch (the design
itself flags step 5 as "the crux; pick ONE representation... any consistent
[encoding] works since both sides just need to agree bit-for-bit") — so I
did not BLOCK, per the instructions' own carve-out.

## `build_rows` additions (existing branches untouched)

**`polymarket.py`** (`SideMode.EXACT_SCORE`, new branch inserted right after
the `THREE_WAY_FIXED` block, before the "all remaining modes are two-sided"
check): mirrors `THREE_WAY_FIXED`'s single-affirmative-row pattern (only
"Yes" emits; "No" drops). Resolves which of `team_a`/`team_b` is home/away
via `_name_match` against `home_name`/`away_name` (checks BOTH names, not
just one, unlike `THREE_WAY_FIXED`'s single `fixed_side_team` check — needed
here since both digits must be assigned correctly) — drops whole if either
resolves ambiguously or to neither/both sides (flip-safe, never trusts
question order even though real data always has `team_a==home`). Then:
`home_goals==away_goals` -> `side=_TIE`; `home_goals>away_goals` ->
`side=home`, scoreline=(home,away); `home_goals<away_goals` -> `side=away`,
scoreline=(away,home) (winner's goals first — the swap). Confirmed
`THREE_WAY_FIXED`/`TEAM_LABEL`/`SPREAD_TEAM`/`OVER_UNDER`/`YESNO_AS_OU`/
`YESNO` branches byte-unchanged (only a new `if mode == SideMode.EXACT_SCORE`
block was inserted; diffed the surrounding code to confirm no existing line
moved or changed).

**`optic.py`** (`Shape.CORRECT_SCORE`, new `elif` branch inserted right
after the existing `Shape.THREE_WAY` branch): parses `odd.selection_line`
(`"W:L"`), resolves `side` off `odd.team_id` via the SAME `team_map[...]` /
`TIE_SIDE` mechanism the neighboring `THREE_WAY` branch already uses (not
`_name_match` — Optic's `Odd` already carries `team_id`, so this is simpler
and more robust than re-deriving name matching that doesn't otherwise exist
in this module; a deliberate deviation from the brief's literal "via
`_name_match`" wording, judged equivalent/better since it reuses an existing,
already-proven pattern in the same file rather than importing a new
dependency). Confirmed every other branch (`MONEYLINE`/`SPREAD`/`TOTAL`/
`THREE_WAY`/`OVER_UNDER`/`YES_NO`/`H2H`) byte-unchanged; only the new `elif`
was inserted.

## Join-test result

`tests/mappers/test_polymarket_correct_score.py`'s `test_join_home_win`,
`test_join_away_win_winner_anchor_swap`, `test_join_draw` build BOTH rows
independently (poly via `polymarket.build_rows`, optic via
`optic.build_rows`) for the same real scoreline on the same synthetic
fixture, assert `(market_type, entity, normalize_line(line), side)` are
identical, AND drive the actual production join —
`pipeline.attach_polymarket_row(row_index, poly_row) == "stamped"` — proving
the poly leg really stamps onto the optic row, not just that the tuples look
alike. All 3 (home win, away win — the winner-anchor swap case: poly's
`"A 1 - 2 B"` joins optic's away-anchored `selection=B, selection_line=
"2:1"` — and draw) pass.

## Files changed

- `mappers/market_types.py` — `Shape.CORRECT_SCORE`; `MarketType.CORRECT_SCORE
  = ("correct_score", Scope.GAME, Shape.CORRECT_SCORE)`.
- `mappers/shared.py` — new `correct_score_line(winner_goals, loser_goals) ->
  float` helper, shared by both exchange modules so the encoding can't drift.
- `mappers/exchanges/polymarket.py` — `SideMode.EXACT_SCORE`;
  `ParsedMarket.team_a_goals`/`team_b_goals` (both `int | None = None`);
  `_Q_SOCCER_EXACT_SCORE` regex + `soccer_exact_score_rule`; `"exact_score"`
  key in `SOCCER_MARKET_TYPES`; rule appended to `soccer_market_rules`
  (21->22 entries, ordering comment updated); new `EXACT_SCORE` branch in
  `build_rows`.
- `mappers/exchanges/optic.py` — new `Shape.CORRECT_SCORE` branch in
  `build_rows`; import reordering (ruff `--fix`, pre-existing I001 debt,
  cosmetic only).
- `mappers/exchanges/px.py` — `Shape.CORRECT_SCORE: "moneyline"` added to
  `_PX_TYPE_FOR_SHAPE` (placeholder guess, same convention as the existing
  H2H entry) — REQUIRED companion edit: `test_px_type_for_shape_covers_
  all_shapes` is a global (not per-league) invariant asserting every `Shape`
  member has an entry; adding `Shape.CORRECT_SCORE` without this would have
  broken that pre-existing test even though CORRECT_SCORE is never wired
  into any PX config. Import reordering (ruff `--fix`, cosmetic).
- `mappers/leagues/{mls,liga_mx,ucl,epl,world_cup}.py` — `"correct_score":
  MarketType.CORRECT_SCORE` added to each `OPTIC.table_types`;
  `MarketType.CORRECT_SCORE` appended to each `OUTPUT_ORDER` (required
  companion edit — same `test_output_order_covers_all_used_types` invariant
  Task R2 hit); doc-comment updates.
- `tests/mappers/test_polymarket_soccer.py` — `ALL_SOCCER_CFG` gained
  `"exact_score"` key; `test_soccer_market_rules_is_ordered_tuple_of_21` ->
  `..._22` (renamed in place, same convention Task R1 used when it extended
  the tuple; membership set extended, no prior assertion removed);
  `test_parse_question_all_21_soccer_forms` -> `..._22` (renamed, one case
  added). No golden/snapshot test touched.
- `tests/mappers/test_polymarket_correct_score.py` — new, 18 tests: recognizer
  (bind + "Any Other Score" drop + missing-config + non-match), poly
  `build_rows` EXACT_SCORE (home win / away win winner-anchor / draw / drops
  when unnamed / drops when both teams resolve the same side), optic
  `build_rows` CORRECT_SCORE (home-anchored / away-anchored / draw), the 3
  join tests, and config wiring (all 5 leagues' `table_types`+`OUTPUT_ORDER`,
  the shared `SOCCER_MARKET_TYPES` key, tuple membership).

## Test counts

- `tests/mappers/test_polymarket_correct_score.py -x -q`: **18 passed** (new).
- `tests/mappers/` full suite: **597 passed, 13 skipped** (baseline via
  pre-task run: 579 passed, 13 skipped -> net +18 passed, 0 skip-count
  change, 0 pre-existing test removed). Confirmed byte-identical on every
  golden/snapshot test explicitly: `test_wc_crypto_integration.py::
  test_output_matches_snapshot`, `test_nba_integration.py::
  test_nba_mapper_output_matches_snapshot`, `test_ncaab_integration.py::
  test_ncaab_mapper_output_matches_snapshot`, plus the MLB/tennis
  integration suites — all pass unchanged (no soccer golden contains a
  `correct_score` odd per R2's own finding, so extending `table_types` has
  zero effect on any existing snapshot).
- `test_table_completeness.py` (global invariants): **27 passed, 13
  skipped** — `test_output_order_covers_all_used_types` green for all 5
  soccer leagues; `test_px_type_for_shape_covers_all_shapes` green (the
  required `_PX_TYPE_FOR_SHAPE` companion entry).

## Lint

`ruff check --fix mappers/market_types.py mappers/exchanges/polymarket.py
mappers/exchanges/optic.py mappers/exchanges/px.py mappers/shared.py
mappers/leagues/{mls,liga_mx,ucl,epl,world_cup}.py
tests/mappers/test_polymarket_correct_score.py
tests/mappers/test_polymarket_soccer.py` — fixed 2 pre-existing import-order
(I001) findings in `optic.py`/`px.py` (cosmetic, unrelated to this task's
logic, safe: full suite re-confirmed green after). My new code is clean on
all rule categories this project enables (`E,F,I,W,UP,C4,RET,PIE,SIM,B,N`) —
converted my new optic.py branch's `if/else` to a ternary to avoid a fresh
SIM108 finding (left the pre-existing, unfixed `THREE_WAY` branch's
identical `if/else` untouched, per the "existing branches untouched"
mandate). Remaining ruff findings repo-wide (3 in `optic.py`: 1 SIM108 on
the pre-existing `THREE_WAY` branch + 1 B905 + 1 SIM108 elsewhere; 3 N806 +
1 E501 in `px.py`/`shared.py`) are ALL pre-existing (confirmed via `git
stash` baseline diff before touching any file) and out of scope.

## Concerns

- `mypy` isn't installed in this repo's `.venv` (`No module named mypy`,
  same as every prior rescue-tier task) — could not run `make typecheck`.
- `Shape.CORRECT_SCORE: "moneyline"` in `_PX_TYPE_FOR_SHAPE` is a dead-code
  placeholder (no PX config uses `MarketType.CORRECT_SCORE`) — purely to
  satisfy the global shape-completeness test, same pattern as the existing
  `H2H` entry's comment.
- `exact_score_other` ("Exact Score: Any Other Score?", 138/2,422 rows,
  5.7% of the family) stays permanently unmapped by design — Optic's
  `correct_score` grid extends beyond poly's 0-3x0-3 cells, so the catch-all
  has no single matching Optic selection (probe section B.1). Verified the
  recognizer naturally returns `None` for it (no digit group to match), no
  special-case guard needed or added.
- EPL's `slug_prefix="epl"` remains "BEST-GUESS, UNVALIDATED" (pre-existing
  Task-6 caveat, inherited unchanged) — this task's EPL `correct_score`
  wiring is inert until that prefix is confirmed live.
- Near-miss during lint verification: a `git stash && ruff check ... && git
  stash pop` one-liner short-circuited on ruff's nonzero exit (lint findings
  present) and skipped the pop, briefly leaving all uncommitted work in the
  stash. Caught immediately via `git status`/`git stash list` and popped
  back before any further edits; verified file contents + full suite
  (597 passed) after recovery. No work was lost. Noting it here as a process
  hazard for future sessions: never chain a stash pop after a command that
  can legitimately exit non-zero.
