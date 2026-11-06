# Task 2 report — Soccer OVER_UNDER + SPREAD recognizers (reuse-mode forms)

## Files changed

- `mappers/exchanges/polymarket.py` — added 4 regex constants
  (`_Q_SOCCER_TOTAL`, `_Q_SOCCER_TEAM_TOTAL`, `_Q_SOCCER_SPREAD`,
  `_Q_SOCCER_FIRST_HALF_TOTAL`) and 4 recognizer functions
  (`soccer_total_rule`, `soccer_team_total_rule`, `soccer_spread_rule`,
  `soccer_first_half_total_rule`), inserted after `tennis_moneyline_rule` and
  before `parse_question`. `build_rows` and `parse_question` were NOT touched.
- `tests/mappers/test_polymarket_soccer.py` — new file, 16 unit tests.

## Design notes (for the record)

- Followed the codebase convention exactly: each rule looks up its canonical
  `MarketType` via `cfg.market_types.get(<kind>)` (kind keys `"total"`,
  `"team_total"`, `"spread"`, `"first_half_total"`), mirroring
  `mlb_total_rule`/`mlb_spread_rule` rather than hardcoding the `MarketType`.
- `team_a`/`team_b`/`entity` all go through `_norm_name(name, cfg.question_style)`
  same as MLB — test assertions use `pm._norm_name(...)` rather than asserting
  raw capitalized strings, per the ambiguity-resolution note.
- **Full-total guard** (`soccer_total_rule`): purely anchoring, no extra code —
  identical mechanism to `mlb_total_rule`. The regex requires the colon to be
  followed only by whitespace then literal `o/u`; the team-total form has an
  extra `<Team>` token there and the half forms have `1st/2nd Half` there, so
  backtracking `team_b` can never find a matching split (there's only one `:`
  in these questions). Verified this holds structurally before writing any
  code (traced the backtracking by hand).
- **Team-total guard**: anchoring alone is *not* sufficient here — the naive
  `(?P<team>.+?)\s+o/u` group would expand across `"<Team> 1st Half"` to reach
  the real `O/U` token, silently mis-parsing the team-half-total form. Added
  an explicit `re.search(r"(?i)\bhalf\b", team_raw)` rejection after the regex
  match, so it now correctly returns `None` for both `<Team> 1st Half O/U N`
  and `<Team> 2nd Half O/U N`. This is the one place this task deviates from
  "guard = pure anchoring" — flagged here since the brief describes the guard
  style via `mlb_total_rule`, which only needed anchoring; team-total needed a
  content check too.
- **First-half-total guard**: pure anchoring again — the pattern requires the
  literal `1st Half` directly after the colon with no team-name group at all,
  so `<Team> 1st Half O/U N` never matches (nothing in the pattern permits a
  team token before the literal `1st`).
- **Spread**: parsing logic is byte-identical to `mlb_spread_rule` (single
  named team + signed line in `entity`, `SPREAD_TEAM` side_mode) — no soccer-
  specific F5-style prefix to guard against, so no additional guard needed.

## Test config used

```python
SOCCER_CFG = pm.PolymarketConfig(
    slug_prefix="mls",
    optic_league_id="usa_-_major_league_soccer",
    market_types={
        "total": MarketType.GAME_TOTAL,
        "team_total": MarketType.TEAM_TOTAL,
        "spread": MarketType.POINT_SPREAD,
        "first_half_total": MarketType.FIRST_HALF_TOTAL,
    },
    question_style="mlb_suffix",
    market_rules=(pm.soccer_total_rule, pm.soccer_team_total_rule,
                  pm.soccer_spread_rule, pm.soccer_first_half_total_rule),
)
```

(The brief's literal ambiguity-resolution snippet used `market_types={}` and
`market_rules=()` as placeholders showing the required *fields*; populating
`market_types` with real kind→MarketType entries was necessary for the rules
to return anything non-None, matching the pattern already used by
`MLB_CFG`/`TENNIS_CFG` in `tests/mappers/test_polymarket.py`. Also added one
extra test, `test_soccer_total_rejects_missing_kind_config`, using the literal
`market_types={}` config from the brief to explicitly cover that
no-config-key → None path.)

## Commands run + output

### Step 2 — verify fail (before implementation)

```
$ .venv/bin/python -m pytest tests/mappers/test_polymarket_soccer.py -x -q
ERROR collecting tests/mappers/test_polymarket_soccer.py
AttributeError: module 'mappers.exchanges.polymarket' has no attribute 'soccer_total_rule'
1 error in 0.14s
```

### Step 4 — verify pass (after implementation)

```
$ .venv/bin/python -m pytest tests/mappers/test_polymarket_soccer.py -x -q
................                                                         [100%]
16 passed in 0.08s
```

### Step 5 — full suite + lint

```
$ .venv/bin/python -m pytest tests/mappers/ -q
........................................................................ [ 18%]
........................................................................ [ 36%]
........................................................................ [ 55%]
........................................................................ [ 73%]
...............................................s....ssss................ [ 92%]
..............................                                           [100%]
385 passed, 5 skipped in 2.19s
```

The diff is purely additive (16 new functions/constants appended to
polymarket.py, one new test file) — nothing pre-existing was edited, so
385 - 16 = 369 passed / 5 skipped is the implied unchanged baseline. No
existing test was modified, dropped, or changed in count — goldens unchanged.

```
$ .venv/bin/python -m ruff check --fix mappers/exchanges/polymarket.py tests/mappers/test_polymarket_soccer.py
All checks passed!
```

`ruff --fix` made no modifications (confirmed via `git status --short` before
and after — only the two intended files show as changed, diff unchanged by
the fix pass).

## Concerns

None blocking. One judgment call worth flagging (see design notes above): the
team-total rule needed an explicit `half` substring guard beyond pure
anchoring, unlike the other three rules and unlike `mlb_total_rule`'s guard
(which is anchoring-only). This was required by the exact question shapes in
the probe findings (the team name and the O/U marker are separated only by
whitespace in both the real and the half-suffixed forms, so the regex alone
can't distinguish them) — flagging it since the brief's phrasing ("mirror
`mlb_total_rule`'s guard") could be read as "anchoring only," and I want the
next reader to know why this one function has extra code.

Note: this report file (`task-2-report.md`) previously held a report from a
different, earlier "Task 2" (the core `(Scope,Shape)` refactor of the
Polymarket matcher, from the wave that built `mlb`/`atp`/`wta` wiring). That
content has been overwritten per this task's explicit instruction to write to
this exact path; the dir is gitignore'd scratch space so nothing tracked was
lost, but flagging the overwrite for the record in case that old content was
still wanted for reference.
