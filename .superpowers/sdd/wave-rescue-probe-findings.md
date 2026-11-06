# Soccer rescue-form probe — poly templates + optic structures + mapping matrix (2026-07-23)

Probe environment: `.venv/bin/python`, no poetry. BQ via the `google-cloud-bigquery`
Python client (`bigquery.Client(project="rs-marketmaking")`) — `gcloud`/`bq` CLI
reauth was **not** re-tried since the client worked first try; every query ran
against `location="us-east4"` (the bridge table's actual location — the naive
`location="US"` 404s, same gotcha the mm-bigquery skill documents). Optic API
access used the ADC workaround: `gcloud auth application-default
print-access-token` → bearer-authed `GET
secretmanager.googleapis.com/v1/projects/marketmaking-test/secrets/opticodds_access_key/versions/latest:access`
→ base64-decode the payload → use as `X-Api-Key` against `api.opticodds.com`
directly with `requests` (bypassing `fetch/optic.py`'s `gcloud secrets
versions access` subprocess call entirely). **Both workarounds succeeded on
the first attempt this session** — no reauth failure was hit, so this is a
full probe, not a partially-blocked one. Read-only throughout: no source file
was modified; all scratch scripts and JSON dumps live under `/tmp` (this
session's isolated scratchpad), never in the repo tree.

Context: Wave 4 shipped an 11-form soccer matcher (`soccer_market_rules` in
`mappers/exchanges/polymarket.py`) covering moneyline/spread/total/team-total/
1st-half-{total,BTTS,winner}/BTTS/player-goals. Its own probe
(`.superpowers/sdd/wave-4-probe-findings.md`, sections B/C) found ~52% of poly
soccer legs fall outside those 11 forms and confirmed Optic prices the biggest
dropped families (`correct_score`, `2nd_half_*`, half-team-totals,
`player_assists`/`player_shots`) — just not yet wired. This probe pins the
exact poly templates and exact Optic selection structures needed to wire a
rescue wave.

## A. Poly rescue-form templates + counts (BQ, bounded)

Query: `SELECT slug, question, outcome_label, outcome_index, n_outcomes FROM
marketmaking-test.raw_ingestion_us.polymarket_position_token_bridge WHERE
SPLIT(slug,"-")[OFFSET(0)] IN ("mls","mex","ucl")` — dry-run estimate
**13,433,097 bytes (~12.8 MiB)**, one query, reused for the whole mls/mex/ucl
section (up slightly from wave-4's ~10.3 MiB estimate — extra columns
requested, `outcome_index`/`n_outcomes` — and the row count itself grew
8,330→8,810 as one more day of MLS/UCL fixtures rolled into the bridge). A
separate, identically-bounded query for `fifwc` (dry-run also ~12.8 MiB, same
table) fetched **8,754 rows** for the player-prop confirmation. Both well
within the ~17 MB ceiling used in wave-4.

Classified all 8,810 mls/mex/ucl rows against BOTH the already-shipped
`soccer_market_rules` (3,940 rows / 44.7%) and the 9 rescue-form regexes below
(4,592 rows / 52.1% — matches the task's "~52%" framing almost exactly) — only
**278 rows (139 distinct questions, 3.2%)** fell through both, and every one
of those is an *additional* out-of-scope form not on this probe's target list
(see "Bonus finds" below), confirming the 9 forms below are the complete
rescue-relevant set for mls/mex/ucl.

### A.1 correct_score / exact_score

Template (verbatim, byte-exact): **`Exact Score: <A> N - N <B>?`** — note the
punctuation precisely: `" - "` (space-hyphen-space) between the two digits,
`": "` (colon-space) is NOT used here (unlike the O/U forms), and the
trailing `?` with no space before it. `<A>` is always the fixture's home team
(same team-order convention every other soccer form uses), digits are single
non-negative integers, `<B>` is away.

```
Exact Score: FC Flora 0 - 0 SK Iberia 1999?
Exact Score: FC Flora 0 - 1 SK Iberia 1999?
...
Exact Score: FC Flora 3 - 3 SK Iberia 1999?
```

Catch-all sibling, its own exact template: **`Exact Score: Any Other Score?`**
(no team names at all — one market per fixture).

- `outcome_label`: **Yes / No** (title case, same vocabulary as BTTS/1st-half-leader — not "Over/Under").
- Grid shape: **4×4 = 16 distinct scorelines per fixture**, home score 0–3 × away score 0–3 (67/81
  sampled fixtures had the full 16; the rest are partial due to market-creation lifecycle —
  fixtures further from kickoff have fewer lines posted yet, not a different grid shape).
- Counts (mls+mex+ucl): **`exact_score` 2,284 rows** (1,142 distinct questions × 2 outcomes) +
  **`exact_score_other` 138 rows** (69 distinct "Any Other Score?" questions × 2) = **2,422 total**,
  the single largest rescue form by volume (52.7% of all 4,592 rescue-tier rows).
- Per-league split: `exact_score` — mls 764, mex 514, ucl 1,006; `exact_score_other` — mls 44, mex 32, ucl 62.

### A.2 2nd-half game total

Template: **`<A> vs. <B>: 2nd Half O/U <N>`** (identical shape to the already-wired 1st-half form,
just `2nd` for `1st`). `outcome_label`: Over / Under.
Example: `FC Flora vs. SK Iberia 1999: 2nd Half O/U 0.5` → Over/Under.
**Count: 372** (mls 126 / mex 66 / ucl 180).

### A.3 team half totals (1st and 2nd)

- **1st half**: `<A> vs. <B>: <Team> 1st Half O/U <N>` — e.g. `FC Flora vs. SK Iberia 1999: FC Flora
  1st Half O/U 0.5` → Over/Under. **Count: 504** (mls 168 / mex 90 / ucl 246).
- **2nd half**: `<A> vs. <B>: <Team> 2nd Half O/U <N>` — same shape, `2nd` for `1st`. **Count: 488**
  (mls 168 / mex 88 / ucl 232).

Both are byte-identical in structure to `_Q_SOCCER_TEAM_TOTAL` (`soccer_team_total_rule`), just
with a `1st Half`/`2nd Half` literal inserted before `O/U` — the existing rule's own docstring
already anticipated this exact collision and guards `team_raw` against containing `"half"` for
that reason.

### A.4 2nd-half winner (+ draw)

- **Team-win**: `<Team> to win the second half?` — single team named, no fixture context in the
  string itself (mirrors `soccer_first_half_leader_rule`'s `<Team> leading at halftime?` shape
  exactly). `outcome_label`: Yes/No. **Count: 262** (mls 84 / mex 64 / ucl 114).
- **Draw**: `<A> vs. <B>: Second half draw?` — both teams named (mirrors
  `soccer_first_half_draw_rule`'s `<A> vs. <B>: Draw at halftime?` shape exactly). **Count: 134**
  (mls 42 / mex 32 / ucl 60).

### A.5 first-to-score (+ neither)

- **Team-first**: `<Team> to score first vs. <Team>?` — e.g. `FC Flora to score first vs. SK Iberia
  1999?`. **Count: 274** (mls 86 / mex 64 / ucl 124).
- **Neither**: `<A> vs. <B>: Neither team to score first?` — **both teams named with the standard
  `": "` colon-prefix**, NOT a bare `Neither team to score first?` (my first classification pass
  missed this — the bare form matches 0/8,810 rows; the correct anchor needs the `<A> vs. <B>: `
  prefix, same convention as `2nd_half_draw`/`1st_half_draw`). **Count: 136** (mls 44 / mex 32 /
  ucl 60).

### A.6 World Cup (`fifwc`) player props

All three ladders confirmed **present and Yes/No-labelled**, mirroring `soccer_player_goals_rule`'s
existing shape exactly (`"<Player>: N+ <stat>"`, N-0.5 line transform):

| poly template | count | N-ladder seen | example |
|---|---|---|---|
| `<Player>: N+ shots` | 928 | 1–5 | `Alexis Mac Allister: 1+ shots` → No |
| `<Player>: N+ goals` (already wired) | 834 | 1–3 | (existing rule) |
| `<Player>: N+ assists` | 568 | 1–2 | `Anthony Gordon: 1+ assists` → Yes |
| `<Player>: N+ goals + assists` | 380 | 1–4 | `Anthony Gordon: 1+ goals + assists` → Yes |
| `<Player>: N+ shots on target` (bonus find, not in the original ask) | 354 | 1–4 | `Alexis Mac Allister: 1+ shots on target` → No |

All outcome_labels are strictly Yes/No (verified: exactly half Yes / half No on every bucket, the
standard binary-market signature). Confirmed **0/8,810 mls/mex/ucl rows** match any of these
player-prop patterns — player props stay World-Cup-only, exactly as wave-4 found for `player_goals`.

### Bonus finds (out of the explicit ask, flagged for later)

The 278-row/139-question residual after both the shipped matcher and the 9 rescue forms above
resolves to exactly two more forms, both structurally simple (same OVER_UNDER/YESNO families
already in play) but not requested this round:

- `<A> vs. <B>: Both Teams to Score in Second Half` (2nd-half BTTS) — same shape as the existing
  1st-half BTTS rule, `2nd` for `1st`.
- `<A> vs. <B>: O/U <N> Total Corners` and `<A> vs. <B>: <Team> O/U <N> Corners` (total/team
  corners) — World Cup already has Kalshi-side corners MarketTypes (`TOTAL_CORNERS`/
  `TEAM_TOTAL_CORNERS`) so these would be cheap reuses too.
- The single `"Stefan Baiaram: Anytime Goalscorer"` one-off noted in wave-4 recurs (still exactly
  1 row) — confirmed still noise, not a form.

## B. Optic structures (live MLS fixture — ADC workaround succeeded)

Fetched via the ADC workaround (see environment note) against a live upcoming MLS fixture,
**New York Red Bulls (home) vs Charlotte FC (away)**, `2026072513A98ED0`, kickoff
2026-07-25T22:30:00Z — 3,364 odds rows across 3 sportsbook batches (kalshi/prophet_x/draftkings/
fanatics/betmgm + betano/fanduel/hard_rock/betfair_exchange/unibet + the prediction-market batch).
**No UCL fixture had any odds posted yet** — all 14 active UCL fixtures are qualifying-round ties
5–6 days out (2026-07-28/29) and every sportsbook batch returned 0 rows for the one UCL fixture
tried (`20260728C14D17A8`); MLS alone is the live reference for this section, sufficient since the
task accepted either.

### B.1 `correct_score` — THE critical unknown, now fully resolved

Structure: `selection` = the team name (or literal `"Draw"`), `selection_line` = **`"<own_goals>:<opponent_goals>"`**
(colon, **no spaces** — distinct from poly's `" - "` space-hyphen-space), `team_id` set for a team
selection / `null` for Draw, `points` always `null`, `normalized_selection` = snake_case team name.

```json
{"name": "Charlotte FC 5:1", "selection": "Charlotte FC", "selection_line": "5:1", "team_id": "8AC68A812511"}
{"name": "New York Red Bulls 4:1", "selection": "New York Red Bulls", "selection_line": "4:1", "team_id": "99E9262E8F71"}
{"name": "Draw 2:2", "selection": "Draw", "selection_line": "2:2", "team_id": null}
```

**Home/away encoding, verified by exhaustive cross-check** (deduped 60 distinct
(selection, selection_line) tuples on this fixture: 30 home-anchored + 24 away-anchored + 6 Draw):
each real final score is encoded **exactly once**, anchored to whichever team scored *more* goals
(`selection_line` = that team's own goals : opponent's goals); a draw is anchored to `"Draw N:N"`.
I explicitly checked for the redundant-reciprocal failure mode (e.g. both `(home,"4:1")` *and*
`(away,"1:4")` present for the same real match state) — **zero overlap found**, confirming there is
no double-encoding to guard against. So the conversion rule is:

- `selection == home_name` → `home_goals, away_goals = split(selection_line, ":")`
- `selection == away_name` → `away_goals, home_goals = split(selection_line, ":")` (reversed!)
- `selection == "Draw"` → `home_goals == away_goals == int(selection_line.split(":")[0])`

Poly's `<A> N1 - N2 <B>` (A=home, N1=home_goals, N2=away_goals per the standing team-order
convention) maps onto exactly one of the three cases above by comparing N1 vs N2 — **N1==N2 → Draw
row; N1>N2 → home-anchored row `"N1:N2"`; N1<N2 → away-anchored row `"N2:N1"`** (own-goals-first,
so the numbers swap order relative to poly's home-first phrasing).

**`1st_half_correct_score`** (66 entries) and **`2nd_half_correct_score`** (25 entries) confirmed
present with the **identical** selection/selection_line shape (verified: `Charlotte FC 3:1`,
`New York Red Bulls 2:0`, `Draw 1:1` on 1st-half; `Charlotte FC 3:2`, `Draw 2:2` on 2nd-half) —
but **poly does not ask a half-scoped exact-score question at all** (0/8,810 rows; only the
full-match `Exact Score:` template exists in the bridge), so these two optic market_ids currently
have no poly counterpart to rescue — noted for completeness, not actionable this wave.

**Optic's own grid extends well beyond poly's 0–3×0–3** (saw scores up to 9:2, 8:4, 7:4 on this
fixture) — poly's `"Any Other Score?"` catch-all is the complement of its 16-cell grid, which has
no single matching Optic selection (it would be the sum of every Optic scoreline *outside*
0–3×0–3). Per the codebase's "never invent, drop what doesn't match" convention, **`exact_score_other`
stays permanently unmapped even after a correct_score rescue** — ~5.7% of the exact-score family
(138/2,422 rows) has no path to a real Optic price.

### B.2 `2nd_half_moneyline` — 3-way, not 2-way

```json
{"selection": "Draw", "selection_line": null, "team_id": null}
{"selection": "Charlotte FC", "selection_line": null, "team_id": "8AC68A812511"}
{"selection": "New York Red Bulls", "selection_line": null, "team_id": "99E9262E8F71"}
```

**3-way** (Team/Team/Draw), identical shape to the already-wired `moneyline`/`1st_half_moneyline`.
No separate `"2nd_half_moneyline_3-way"` market_id exists (0 rows) — same convention as the
full-game/1st-half series, where the plain id is already 3-way and no `-3-way` suffix variant
coexists. Maps directly to `MarketType.SECOND_HALF_WINNER_3WAY` — **already defined** in
`market_types.py` (line 77) but never wired to any Optic or poly config yet.

### B.3 `first_team_to_score` — 3-way, `team_first_goal_scorer` doesn't exist

```json
{"selection": "Charlotte FC", "team_id": "8AC68A812511"}
{"selection": "Draw", "team_id": null}
{"selection": "New York Red Bulls", "team_id": "99E9262E8F71"}
```

Same 3-way Team/Team/Draw shape as `2nd_half_moneyline` above. The task's alternate candidate
`team_first_goal_scorer` **does not exist** as a market_id on this fixture (confirmed 0 rows) — the
real id is `first_team_to_score`. Half-scoped variants exist too but are thin
(`1st_half_first_team_to_score` / `2nd_half_first_team_to_score`, 3 rows each) and poly doesn't ask
half-scoped first-to-score, so only the full-game id matters.

### B.4 `2nd_half_total_goals` / team half-totals / player props — all confirmed, standard OVER_UNDER shape

```json
// 2nd_half_total_goals (GAME scope, no entity):
{"name": "Under 0.5", "selection": "", "selection_line": "under", "points": 0.5, "team_id": null}
{"name": "Over 2.5",  "selection": "", "selection_line": "over",  "points": 2.5, "team_id": null}

// 1st_half_team_total / 2nd_half_team_total (TEAM scope, entity=team):
{"name": "Charlotte FC Over 2.5", "selection": "Charlotte FC", "selection_line": "over", "points": 2.5, "team_id": "8AC68A812511"}
{"name": "New York Red Bulls Under 0.5", "selection": "New York Red Bulls", "selection_line": "under", "points": 0.5, "team_id": "99E9262E8F71"}

// player_assists / player_shots_on_target (PLAYER scope, entity=player):
{"name": "Tim Parker Over 0.5", "selection": "Tim Parker", "selection_line": "over", "points": 0.5, "player_id": "83FD7A048776"}
{"name": "Eric Choupo-Moting Over 3.5", "selection": "Eric Choupo-Moting", "selection_line": "over", "points": 3.5, "player_id": "A2BE63FE98DC53C1"}

// player_goals_+_assists (PLAYER scope, same shape):
{"name": "Jahkeele Marshall-Rutty Over 0.5", "selection": "Jahkeele Marshall-Rutty", "selection_line": "over", "points": 0.5}
```

All four are the exact same `over`/`under` + `points` shape `optic.build_rows`'s `Shape.TOTAL`
(game/team scope) and `Shape.OVER_UNDER` (player scope) branches already handle generically — no
Optic-side code changes needed for any of these, only new `table_types` entries + (for the poly
side) new `market_rules` recognizers.

Note: `player_shots` (not `_on_target`) was **not posted on this particular fixture** (0 rows) —
wave-4's probe fixture (Philadelphia Union vs NY Red Bulls, a different MLS game) had 448
`player_shots` rows, confirming it's a real, if intermittently-posted, market_id; poly's plain
`"N+ shots"` question maps to this id (not `player_shots_on_target`, which is poly's separate `"N+
shots on target"` question — see A.6's bonus row).

## C. Mapping matrix + build_rows assessment

Read `mappers/exchanges/polymarket.py` (`SideMode` enum, `build_rows` dispatch) and
`mappers/exchanges/optic.py` (`Shape`-keyed dispatch, lines 306–387) to judge fit. Every existing
`Shape`/`SideMode` pair is generic (dispatches on `(scope, shape)`/`side_mode` alone, no
per-market-id logic), so "cheap" below means *zero* changes to either `build_rows` function — only
new `MarketType` enum members (when one doesn't already exist) plus new `market_rules` recognizers
plus `OpticConfig.table_types`/`SOCCER_MARKET_TYPES` entries.

| Rescue form | Optic market_id | Optic selection shape | SideMode fit | MarketType needed |
|---|---|---|---|---|
| 2nd-half winner (+draw) | `2nd_half_moneyline` | 3-way: team/team/Draw | `THREE_WAY_FIXED` (existing) | `SECOND_HALF_WINNER_3WAY` — **already exists**, unused |
| first-to-score (+neither) | `first_team_to_score` | 3-way: team/team/Draw | `THREE_WAY_FIXED` (existing) | **new**: `FIRST_TO_SCORE_3WAY` (Scope.GAME, Shape.THREE_WAY) |
| 2nd-half game total | `2nd_half_total_goals` | over/under + points | `OVER_UNDER` (existing) | **new**: `SECOND_HALF_TOTAL` (Scope.GAME, Shape.TOTAL) |
| 1st-half team total | `1st_half_team_total` | team + over/under + points | `OVER_UNDER` (existing) | **new**: `FIRST_HALF_TEAM_TOTAL` (Scope.TEAM, Shape.TOTAL) |
| 2nd-half team total | `2nd_half_team_total` | team + over/under + points | `OVER_UNDER` (existing) | **new**: `SECOND_HALF_TEAM_TOTAL` (Scope.TEAM, Shape.TOTAL) |
| player assists | `player_assists` | player + over/under + points | `YESNO_AS_OU` (existing) | `PLAYER_ASSISTS` — **already exists** (only wired via World Cup's CRYPTO config today, never via OPTIC) |
| player shots | `player_shots` | player + over/under + points | `YESNO_AS_OU` (existing) | `PLAYER_SHOTS` — **already exists**, same gap |
| player shots on target (bonus) | `player_shots_on_target` | player + over/under + points | `YESNO_AS_OU` (existing) | `PLAYER_SHOTS_ON_TARGET` — **already exists**, same gap |
| player goals+assists (bonus, in original ask) | `player_goals_+_assists` | player + over/under + points | `YESNO_AS_OU` (existing) | reuse `PLAYER_GOALS_OR_ASSIST` — **already exists** (same Shape/Scope; crypto's binary "To Score Or Give Assist" already merges onto this type's N=1 rung the same way `anytime_goal_scorer` merges onto `PLAYER_GOALS`'s 0.5 line — precedent set in world_cup.py) |
| **correct_score** | `correct_score` | discrete scoreline (team-anchored `"own:opp"` string, or Draw) | **NONE of the 6 fit** | **NEEDS a new MarketType + a new Shape** (see below) |

**Every row except `correct_score` is "cheap"**: for the THREE_WAY/TOTAL/OVER_UNDER rows, the
Optic-side `build_rows` dispatch (`mappers/exchanges/optic.py` lines 306–387) already handles the
shape generically — literally just add a `table_types` key. On the poly side, the new
`market_rules` recognizers are copy-paste-rename jobs against the already-shipped templates:
`soccer_second_half_leader_rule`/`soccer_second_half_draw_rule` mirror
`soccer_first_half_leader_rule`/`soccer_first_half_draw_rule` byte-for-byte (`1st`→`2nd`,
`leading at halftime`→`to win the second half`); `soccer_first_to_score_rule`/
`soccer_neither_first_rule` mirror the same team-win/draw pair pattern; `soccer_second_half_total_rule`
mirrors `soccer_first_half_total_rule`; `soccer_first_half_team_total_rule`/
`soccer_second_half_team_total_rule` mirror `soccer_team_total_rule` with a `1st Half`/`2nd Half`
literal inserted (same anchoring technique the existing rule already uses to reject the plain
team-total form); `soccer_player_assists_rule`/`soccer_player_shots_rule`/
`soccer_player_shots_on_target_rule`/`soccer_player_goals_assists_rule` are direct clones of
`soccer_player_goals_rule` (`_player_prop_rule` + `YESNO_AS_OU` + the `n - 0.5` line transform,
just a different stat word in the regex and a different `kind` key).

### `correct_score` — what a new SideMode would need to emit

None of the 6 `SideMode`s (nor, symmetrically, any of the 8 `Shape`s Optic's own `build_rows`
dispatches on) fit a discrete multi-outcome scoreline market: `TEAM_LABEL`/`SPREAD_TEAM` assume
exactly 2 complementary team-named outcomes; `OVER_UNDER`/`YESNO_AS_OU` assume an over/under or
yes/no pair; `THREE_WAY_FIXED` assumes at most 3 sides (home/away/tie) with a *known* fixed
membership — `correct_score` instead has dozens of mutually exclusive discrete outcomes (a
scoreline grid), and unlike `THREE_WAY_FIXED`'s draw-collapsing behavior, every distinct scoreline
(including every draw scoreline `0:0`, `1:1`, `2:2`...) is its own separate row, not one shared
`_TIE` bucket.

Since B.1 established both sides can independently compute a canonical `(home_goals, away_goals)`
pair for any real scoreline and the existing `CanonicalRow` merge key is already the 4-tuple
`(market_type, entity, line, side)` — segregated per `market_type` so there is zero collision risk
with any other market's side vocabulary — the cheapest correct design is:

1. **New `Shape.CORRECT_SCORE`** in `market_types.py`, and a new `MarketType.CORRECT_SCORE`
   (`Scope.GAME`, `Shape.CORRECT_SCORE`). No new `CanonicalRow` fields needed — reuse `side: str`
   as a discrete key: `side = f"{home_goals}-{away_goals}"` (hyphen, to stay visually distinct from
   Optic's own `":"` convention and poly's own `" - "` phrasing — any consistent separator works
   since both sides just need to agree bit-for-bit), `entity = None`, `line = None`.
2. **`mappers/exchanges/optic.py`**: a new `elif mt.shape == Shape.CORRECT_SCORE:` branch (~alongside
   line 330's `THREE_WAY` branch) that parses `odd.selection_line` (`"X:Y"`), resolves `odd.team_id`
   against `team_map` to learn whether the named team is home or away (`None` → Draw, `X==Y`
   already), and emits `side = f"{home_goals}-{away_goals}"` per the B.1 conversion rule (swap the
   two numbers when the anchor team is away).
3. **`mappers/exchanges/polymarket.py`**: a new `SideMode.EXACT_SCORE` (or similar); a new
   `ParsedMarket` needs two new int-or-None fields (`score_a`/`score_b`, parsed straight from the
   regex's two digit groups) since the existing single `line: float | None` can't carry a pair; a
   new recognizer `soccer_exact_score_rule` matching `_Q_SOCCER_EXACT_SCORE = re.compile(r"^Exact
   Score:\s*(?P<a>.+?)\s+(?P<sa>\d+)\s*-\s*(?P<sb>\d+)\s+(?P<b>.+?)\?\s*$")` (a **second**, disjoint
   rule for the literal `"Exact Score: Any Other Score?"` string that always returns `None` —
   explicitly documented as permanently unmapped per B.1's grid-boundary finding, not a bug); and a
   new `build_rows` branch (mirroring `THREE_WAY_FIXED`'s single-affirmative-row pattern: these are
   Yes/No markets, only the "Yes" outcome emits a row) that resolves `team_a` against
   `home_name`/`away_name` via the existing `_name_match` helper (flip-safety — never trust
   positional order blindly, even though byte-exact data shows `team_a` is always home) to learn
   which parsed digit is `home_goals` vs `away_goals`, then emits `side =
   f"{home_goals}-{away_goals}"` identically to step 2's convention.

This is a real, if mechanical, cross-cutting change (touches `market_types.py` +
both exchange `build_rows` functions + `polymarket.py`'s dataclass/enum), not a
config-only wire-up — it is its own tier, separate from the 9 "cheap" forms above.

## Rescue wave scope recommendation

**Cheap tier (config + recognizer-clone only, zero `build_rows` changes on either exchange
module)** — 9 forms, 2,170 rescue-tier rows on mls+mex+ucl (4,592 total rescue rows − 2,422
correct_score) + 1,882 fifwc player-prop rows (assists+shots+goals_assists+shots_on_target, the
last two being bonus finds beyond the original ask):

| form | mls+mex+ucl count |
|---|---|
| 1st-half team total | 504 |
| 2nd-half team total | 488 |
| first-to-score (+neither) | 274 + 136 = 410 |
| 2nd-half game total | 372 |
| 2nd-half winner (+draw) | 262 + 134 = 396 |

plus fifwc player props (World-Cup-only, confirmed 0/8,810 on mls/mex/ucl): player_shots 928,
player_goals 834 (already wired), player_assists 568, player_goals_+_assists 380,
player_shots_on_target 354.

**correct_score tier (needs new `Shape`/`MarketType`/`SideMode` + a `build_rows` branch on *both*
`mappers/exchanges/optic.py` and `mappers/exchanges/polymarket.py`, plus 2 new `ParsedMarket`
fields)** — 1 form, but the single largest one: 2,284 rescuable rows (+ 138 permanently-unmappable
`exact_score_other` rows that stay dropped even after the rescue, per B.1's grid-boundary finding).

Recommendation: ship the cheap tier first (9 straightforward recognizer clones, no risk to
existing dispatch code, immediately doubles rescued volume from ~45% to ~97% of currently-dropped
mls/mex/ucl legs when combined with the already-shipped 11 forms) as one wave; treat
`correct_score` as its own follow-up wave given the cross-cutting `Shape`/`SideMode` design work,
even though it is the single biggest volume item (52.7% of the total rescue-tier row count) and
therefore the highest-value target once the machinery exists.
