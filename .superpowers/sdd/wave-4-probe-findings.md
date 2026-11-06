# Wave 4 — Soccer optic+poly probe findings (2026-07-22)

Probe environment: `.venv/bin/python`, `GCP_PROJECT=marketmaking-test` for Optic fetches; `bq --project_id=rs-marketmaking` for the bridge queries. Read-only — no source file modified; two throwaway scripts ran from `/tmp` (`fetch/optic.py`'s `--league` CLI is choice-restricted to the 9 currently-wired leagues, so MLS/Liga MX/UCL needed either `--explore <raw-id>` — verified by reading the argparse code that `--explore` takes an unrestricted string, unlike `--league` — or a throwaway script; used the throwaway-script fallback to avoid writing fetch output into the repo tree).

## Three Optic league_ids (discovered via `leagues/active?sport=soccer`, 154 rows)

`fetch/optic.py` has no leagues-listing helper (`get_sports()` only hits `sports/active`, which lists *sports* like `soccer`/`basketball`, not leagues). The leagues list lives at `GET {BASE_URL}leagues/active?sport=soccer`. Grepping the 154-row soccer response for MLS/Liga MX/UCL:

| League | Optic `league_id` | numerical_id | region |
|---|---|---|---|
| **Major League Soccer** | `usa_-_major_league_soccer` | 527 | UNITED_STATES |
| **Liga MX** | `mexico_-_liga_mx` | 342 | MEXICO |
| **UEFA Champions League** | `uefa_-_champions_league` | 506 | INTERNATIONAL |

Note for Task 7: the poly bridge slug prefix for Liga MX is `mex` (confirmed in section C), NOT `mexico` or `liga_mx` — `PolymarketConfig.slug_prefix="mex"` but `OpticConfig.league_id="mexico_-_liga_mx"` are two different strings on the same league module; don't conflate them.

(Also noted in passing, not requested but adjacent: `usa_-_mls_next_pro` is MLS's reserve-league sibling — do not confuse with `usa_-_major_league_soccer`.)

## A. Optic soccer market ceiling

**No MLS or UCL fixture was live at probe time in a way that changed the answer for the better** — MLS: 31 fixtures in the next 10 days, 0 live (first kickoff was ~3.5h out: `2026-07-22T23:30:00Z`, `Philadelphia Union` vs `New York Red Bulls`, MLS's date_before horizon 10-day fetch). UCL (qualifying rounds are live in July) DID have one live fixture (`KS Egnatia Rrogozhinë vs NK Celje`, `202607228B140941`, kicked off `2026-07-22T19:00:00Z`). Both were pulled:

- **MLS pre-match** (`2026072210C6FAB9`, Philadelphia Union vs NY Red Bulls): **6,668 odds rows, 137 distinct `market_id`s.**
- **UCL live** (`202607228B140941`, in progress): **787 odds rows, 38 distinct `market_id`s** — a strict subset of the MLS list (no market_id in the UCL live set was absent from the MLS pre-match set). This is expected and important: **live/in-play odds boards are a suspended/collapsed subset of the pre-match board**, not a superset, so the MLS pre-match fixture is the more complete "ceiling" reference, not an understatement. (A qualifying-round UCL tie is also a thin book relative to a marquee UCL matchup — expect the live UCL market count to be a floor, not representative of UCL's own ceiling.)

**Full ranked `market_id` list, MLS pre-match fixture (137 distinct, 6668 odds rows):**

```
   531  player_goals                              75  1st_half_team_total
   448  player_shots                              75  player_fouls
   442  player_shots_on_target                    72  halftime_fulltime
   355  correct_score                             69  1st_half_player_goals
   253  asian_total_goals                         69  1st_half_anytime_goal_scorer
   241  player_assists                            62  1st_half_player_shots_on_target
   223  anytime_goal_scorer                        60  2nd_half_team_total
   213  total_goals                                58  anytime_goal_scorer_outside_box
   192  asian_handicap                             55  team_total_shots_on_target
   186  first_goal_scorer                          54  team_total_shots
   155  player_goals_+_assists                     50  1st_half_total_corners
   150  team_total                                 50  2nd_half_total_goals
   142  team_total_corners                         50  2nd_half_asian_total_goals
   132  total_corners                              49  player_offsides
   125  player_to_score_or_assist                  49  1st_half_asian_handicap
   111  player_tackles                             48  2nd_half_total_corners
   111  last_goal_scorer                           48  2nd_half_team_total_corners
    96  1st_half_player_shots                      44  1st_half_team_total_corners
    95  1st_half_asian_total_goals                 42  moneyline
    89  1st_half_total_goals                       41  team_first_goal_scorer
    82  1st_half_correct_score                     41  player_outside_box_shots_on_target
    82  player_fouls_drawn                         39  player_to_score_in_both_halves
                                                    39  2nd_half_anytime_goal_scorer
    39  2nd_half_player_goals                      15  2nd_half_double_chance
    34  anytime_card_receiver                      15  goal_spread_3-way
    34  anytime_red_card_receiver                  14  1st_half_team_total_exact
    34  player_cards                               14  total_goals_exact
    30  moneyline_3-way_+_total_goals               14  2nd_half_both_teams_to_score
    30  1st_half_moneyline                          14  both_teams_to_score_+_moneyline_3-way
    30  total_corners_3-way                         12  goal_both_halves
    29  total_shots_on_target                       12  1st_half_moneyline_3-way_+_1st_half_total_goals
    26  2nd_half_correct_score                      10  total_goals_odd_even
    26  team_total_tackles                          10  team_total_offsides
    25  both_teams_to_score                         10  team_to_score_both_halves
    24  player_header_shots_on_target               10  team_to_win_either_half
    23  double_chance                                9  highest_scoring_half / 1st_half_most_corners_3-way / 1st_half_goal_spread_3-way
    23  anytime_goal_scorer_by_header                8  1st_half_total_goals_exact / 1st_half_draw_no_bet / team_to_win_both_halves
    22  draw_no_bet                                  6  team_to_win_from_behind / 2nd_half_most_corners_3-way / 2nd_half_asian_handicap /
    22  total_shots                                     team_to_win_to_nil / most_shots_on_target_3-way / 2nd_half_draw_no_bet
    21  2nd_half_moneyline                           4  team_total_odd_even / 1st_half_team_total_odd_even / team_to_score /
    21  team_to_score_goal_1_3-way                      both_teams_to_score_both_halves / team_to_score_penalty /
    20  team_total_exact                                2nd_half_team_total_odd_even / 1st_half_total_goals_odd_even /
    18  most_corners_3-way / player_saves /             total_corners_odd_even / asian_handicap_corners / 1st_half_team_to_score /
        first_team_to_score / 1st_half_double_chance /  team_clean_sheet / 2nd_half_team_to_score / 1st_half/2nd_half_team_total_card_points /
        1st_half_both_teams_to_score                    total_red_cards / team_total_card_points
                                                      3  period_with_most_goals / race_to_{3,5,7,9}_corners / last_team_to_score /
                                                         1st/2nd_half_first_team_to_score / most_cards_3-way / will_there_be_an_own_goal /
                                                         1st_half_moneyline_3-way / first_team_to_score_3-way / 1st_half_total_shots(_on_target)
                                                      2  2nd_half_total_goals_odd_even / {1st,2nd}_half_total_corners_odd_even /
                                                         {1st,2nd}_half_asian_handicap_corners / team_to_kick_{first,last}_corner /
                                                         {1st_half_}will_there_be_a_{penalty,red_card} / total_card_points /
                                                         asian_handicap_card_points / 1st_half_total_card_points
```

(Raw ranked list saved at `/tmp/wave4probe_*` scratch files during the probe; reproduced verbatim above, just reflowed 2-up past rank ~20 for width.)

## B. Rescue check — does optic price the big poly forms mmmapper currently drops?

All four requested candidates are **PRESENT** on the live Optic feed:

| Form | Optic market_id(s) found | Count (MLS pre-match) | Verdict |
|---|---|---|---|
| Exact-score / correct_score | `correct_score` (355), `1st_half_correct_score` (82), `2nd_half_correct_score` (26) | 463 combined | **PRESENT** |
| 2nd-half totals/moneyline | `2nd_half_total_goals` (50), `2nd_half_asian_total_goals` (50), `2nd_half_moneyline` (21), `2nd_half_asian_handicap` (6), `2nd_half_both_teams_to_score` (14), `2nd_half_correct_score` (26), plus corners/cards/double-chance 2nd-half variants | 150+ combined | **PRESENT** |
| Team-×-half total | `1st_half_team_total` (75), `2nd_half_team_total` (60) | 135 combined | **PRESENT** |
| `player_assists` / `player_shots` | `player_assists` (241), `player_shots` (448), `player_shots_on_target` (442), `player_to_score_or_assist` (125), `player_goals_+_assists` (155) | 1,417 combined | **PRESENT** |

None of these five market families appear in ANY existing mmmapper `OpticConfig.table_types` (checked `mappers/leagues/world_cup.py`, the most-developed soccer config — its `table_types` covers moneyline/asian_handicap/total_goals/team_total/player_goals/1st_half_{moneyline,asian_handicap,total_goals}/both_teams_to_score/1st_half_both_teams_to_score/total_corners/team_total_corners/to_advance; no `correct_score`, no `2nd_half_*`, no team-half-total, no `player_assists`/`player_shots`).

**Verdict: all four are genuinely rescuable in a future wave.** This is out of Wave-4's declared scope (the plan already deliberately drops `exact_score`/`team_1h_total`/`team_2h_total`/`game_2h_total`/player-assists/shots pending this exact confirmation) — but the confirmation moves this from "maybe, unverified" to "yes, priced, worth a Wave 5." `correct_score` alone (463 odds rows on one fixture, ~2,210/8,330 = 27% of the poly soccer bridge rows across mls/mex/ucl in section C) is the single biggest addressable form.

## C. Real poly soccer question templates (bounded BQ, mls/mex/ucl)

Dry-run estimate: **10,842,511 bytes (~10.3 MiB)** for the unfiltered `SPLIT(slug,"-")[OFFSET(0)] IN ("mls","mex","ucl")` scan (single query, reused locally for all of section C — no repeat scans). A second, separately-bounded dry-run for the `fifwc` player-goals confirmation carried the same ~10.3 MiB estimate (same table, different slug filter). Both within the expected ~17 MB ceiling.

Row counts: 8,330 total (mls 2,948 / mex 1,526 / ucl 3,856). A template classifier covering the 10 requested forms + `exact_score` + a few adjacent forms (`first_to_score`, `2nd_half_result`, `total_corners`) classified 8,328/8,330 rows (99.98%) — the 2 unclassified rows are a single one-off UCL market, footnoted below.

| poly form | exact template | outcome_labels | count (mls+mex+ucl) | example |
|---|---|---|---|---|
| full game total | `<A> vs. <B>: O/U <N>` | Over / Under | 850 | `Austin FC vs. Seattle Sounders FC: O/U 2.5` → Over / Under |
| team total | `<A> vs. <B>: <Team> O/U <N>` | Over / Under | 760 | `Austin FC vs. Seattle Sounders FC: Austin FC O/U 1.5` → Over / Under |
| spread | `Spread: <Team> (-N)` / `(+N)` | **both team names** (not Over/Under) | 564 | `Spread: Austin FC (-1.5)` → `Austin FC` / `Seattle Sounders FC` |
| 3-way ML — team win | `Will <Team> win on <YYYY-MM-DD>?` | Yes / No | 364 | `Will Austin FC win on 2026-07-22?` → Yes / No |
| 3-way ML — draw | `Will <A> vs. <B> end in a draw?` | Yes / No | 156 | `Will Austin FC vs. Seattle Sounders FC end in a draw?` → Yes / No |
| 1st-half total | `<A> vs. <B>: 1st Half O/U <N>` | Over / Under | 382 | `Austin FC vs. Seattle Sounders FC: 1st Half O/U 1.5` → Over / Under |
| 1st-half leader | `<Team> leading at halftime?` | Yes / No | 262 | `Austin FC leading at halftime?` → Yes / No |
| 1st-half draw | `<A> vs. <B>: Draw at halftime?` | Yes / No | 128 | `Austin FC vs. Seattle Sounders FC: Draw at halftime?` → Yes / No |
| BTTS | `<A> vs. <B>: Both Teams to Score` | Yes / No | 152 | `Austin FC vs. Seattle Sounders FC: Both Teams to Score` → Yes / No |
| 1st-half BTTS | `<A> vs. <B>: Both Teams to Score in First Half` | Yes / No | 158 | `Austin FC vs. Seattle Sounders FC: Both Teams to Score in First Half` → Yes / No |
| *(adjacent, not in scope)* exact score | `Exact Score: <A> N - N <B>?` (+ `Exact Score: Any Other Score?`) | Yes / No | 2,210 | `Exact Score: Austin FC 0 - 0 Seattle Sounders FC?` → Yes / No |
| *(adjacent)* 1st-half team total | `<A> vs. <B>: <Team> 1st Half O/U <N>` | Over / Under | 496 | — |
| *(adjacent)* 2nd-half team/game total | `<A> vs. <B>: [<Team> ]2nd Half O/U <N>` | Over / Under | 366 + 478 | — |
| *(adjacent)* first-to-score / 2nd-half-winner | `<Team> to score first vs. <Team>?`, `<Team> to win the second half?` | Yes / No | 376 + 364 | — |

Date format confirmed: `Will <Team> win on 2026-07-22?` — strict ISO `YYYY-MM-DD`, matching the fixture date in the poly slug byte-for-byte.

**Player-goals questions (`<Player>: N+ goals`) do NOT appear for mls/mex/ucl** (0/8,330 rows matched that pattern) — confirmed **only for World Cup**: a separate bounded BQ probe (`slug` prefix `fifwc`, same ~10.3 MiB estimate) found the ladder present, e.g. `Alexander Sørloth: 1+ goals` / `2+ goals` / `3+ goals`, outcome_label Yes/No, slug suffix `-goals-<player>-gte<N>`.

**Footnote — the 2 unclassified rows**: one single UCL market, `Stefan Baiaram: Anytime Goalscorer` (Yes/No, slug `ucl-pls-ucr-2026-07-22-ags-stefan-baiaram`) — a *different* shape from the World Cup `N+ goals` ladder (no line, single Yes/No, "Anytime Goalscorer" wording). Appears exactly once in the entire 8,330-row sample — treat as noise, not a form to build a recognizer for; if it recurs at scale in a later pull, revisit.

**`mex` naming note**: the bridge's poly slug prefix for Liga MX is `mex` (e.g. `mex-que-ame-2026-07-18-...`), independent of the Optic `league_id` `mexico_-_liga_mx` recorded above.

## D. Team-name agreement (MLS)

Cross-referenced Optic's 30 distinct MLS competitor names (from `fixtures/active`, `usa_-_major_league_soccer`, 31 fixtures / 10-day horizon) against every poly team name parsed out of the 36 distinct MLS fixtures in the bridge sample (via the full-total form's `<A> vs. <B>: O/U N`), applying mmmapper's exact `mlb_suffix` logic — `_normalize()` (NFKD fold, lowercase, strip non-alnum to spaces) then `_name_match()` (equality or containment either direction), copied verbatim from `mappers/exchanges/polymarket.py`.

**Result: 13 of 72 poly team-name instances (18%) do NOT reconcile** under plain mlb_suffix containment — 5 distinct franchises:

| poly `question` name | optic `home_name`/`away_name` | mlb_suffix containment? | why it fails |
|---|---|---|---|
| `CF Montréal` | `Club de Foot Montréal` | **NO** | different abbreviation style entirely (initialism vs. spelled-out club name); neither string contains the other |
| `Los Angeles Galaxy` | `LA Galaxy` | **NO** | `los angeles` vs `la` — no shared substring relationship |
| `New York City FC` | `New York City Football Club` | **NO** | `fc` vs `football club` — abbreviation vs spelled-out suffix |
| `D.C. United SC` | `DC United` | **NO** | punctuation tokenization: `_normalize("D.C.")` → `"d c"` (space-separated), so `"dc"` (optic, no space) is never a contiguous substring of `"d c united sc"` |
| `Inter Miami CF` | `Club Internacional de Fútbol Miami` | **NO** | poly uses the common English nickname, optic uses the full formal (partly Spanish) legal name — no lexical overlap at all |

The other ~30 MLS franchises (Austin FC, Seattle Sounders FC, Toronto FC, St. Louis City SC, Sporting Kansas City, Nashville SC, Atlanta United FC, Chicago Fire FC, Vancouver Whitecaps FC, Columbus Crew, FC Cincinnati, Charlotte FC, Colorado Rapids (SC) ↔ Colorado Rapids, San Diego FC, Toronto FC, Houston Dynamo ↔ Houston Dynamo FC, Real Salt Lake, Minnesota United FC, New England Revolution, New York Red Bulls, Orlando City SC, Philadelphia Union, Portland Timbers, FC Dallas, San Jose Earthquakes) all reconcile cleanly via plain containment — the existing `mlb_suffix` style is sufficient for the majority, but **not sufficient on its own** for MLS.

**Recommendation for Task 6/7**: reuse the existing alias-table pattern already in the codebase (`OpticConfig.abbr_overrides` keyed by competitor id, or the `config/<league>/team_aliases.toml` mechanism from World Cup/tennis) rather than inventing a new `question_style`. A small MLS-specific name-alias overlay (5 entries: CF Montréal, LA Galaxy, NYCFC, DC United, Inter Miami) checked before/alongside the plain containment match would close the gap without touching `_normalize`/`_name_match` itself. Liga MX and UCL were not exhaustively checked here (out of the Task-1 D scope, which asked for MLS specifically) but the same failure modes (nickname-vs-legal-name, nationality-language club names) are likely to recur there too and should get the same probe before Task 7 locks in their configs.

## Impact on Tasks 2–7

Tasks 2–5's exact question templates, outcome-label pairs, and the `Will <Team> win on <YYYY-MM-DD>?` date format are now all confirmed byte-for-byte against live data (section C) — recognizers can be written directly against these strings with no placeholders. Task 6 (EPL/WORLD_CUP) is unaffected by section D since it doesn't touch MLS names. Task 7 (MLS/Liga MX/UCL) gets its three `OpticConfig.league_id` values from section A, its `table_types` seed list from the section-A market ceiling (moneyline/asian_handicap/total_goals/team_total/1st_half_moneyline/1st_half_asian_handicap/1st_half_total_goals/both_teams_to_score/1st_half_both_teams_to_score present and countable on all three leagues per section C), and must NOT assume plain `mlb_suffix` question_style is sufficient for MLS team names as-is — Task 7 needs a small alias overlay (section D) before wiring `MLS = PolymarketConfig(...)`, or 5 real MLS franchises will silently drop every market touching them (flip-safety means a name that resolves to neither fixture side just returns `[]`, so this fails silent, not loud). Section B's rescue verdict (correct_score / 2nd-half / team-half-total / player_assists+shots are ALL genuinely priced by Optic) is out of Wave-4 scope per the plan's own deferral but is now a confirmed, well-evidenced candidate for a Wave 5 — `correct_score` alone represents 27% of the poly soccer bridge row volume across mls/mex/ucl, the single largest addressable chunk left on the table. Player-goals stays WORLD_CUP/EPL-only (poly doesn't ask the `N+ goals` ladder for mls/mex/ucl at all — confirmed 0/8,330), so Task 5's `soccer_player_goals_rule` will simply never fire when wired into the three new expansion leagues, which is harmless (dead code path, not a bug) but means Task 7's expansion `PolymarketConfig.market_rules` doesn't need to special-case its absence.
