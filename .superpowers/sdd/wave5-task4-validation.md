# Wave-5 Task 4: live-data validation of the WNBA Polymarket matcher

Read-only analysis (no pipeline/matcher/league source touched). Env:
`GCP_PROJECT=marketmaking-test`, `.venv/bin/python`, no poetry. Run 2026-07-23,
~06:30-07:00 UTC. Data dir: `data/2026-07-23/12_00/` (gitignored). Scratch scripts:
`/tmp/wnba_probe*.py`.

## 0. `fetch.optic --league wnba` wiring — CONFIRMED (Task 3 works)

```
GCP_PROJECT=marketmaking-test .venv/bin/python -m fetch.optic --league wnba --out-dir "$D"
```

`--league wnba` is **accepted** — no `argparse` "invalid choice" error, and the
`LEAGUE_SECRET.keys() >= SUPPORTED_LEAGUES.keys()` import-time assertion in
`fetch/optic.py` passes. Execution proceeded past both gates into
`init_headers("wnba")` → `subprocess.check_output(["gcloud", "secrets", ...])`,
which is where it failed (see §1). This is exactly the gap `task-8-validation.md`
hit for MLS/Liga MX/UCL (`--league mls` errored at argparse because
`SUPPORTED_LEAGUES` was hand-maintained and stale) — Task 3's derivation of
`SUPPORTED_LEAGUES` from `mappers.run.LEAGUES` plus the explicit
`LEAGUE.WNBA: "opticodds_access_key"` entry in `LEAGUE_SECRET` closes it. **No
Task-3 regression.**

## 1. Environment blocker: could not complete a live `fetch.optic` pull this session

`gcloud secrets versions access latest --secret=opticodds_access_key
--project=marketmaking-test` fails in this sandbox:

```
ERROR: (gcloud.secrets.versions.access) There was a problem refreshing your
current auth tokens: Reauthentication failed. cannot prompt during
non-interactive execution.
```

This is a session-level `gcloud` CLI reauth requirement (step-up auth), not a
code defect — `task-8-validation.md`'s session hit no such wall running the
identical `_init_headers`/secret-access path two days earlier. Things tried,
all legitimate (no credential bypass attempted):
- Retried the plain command — same reauth error.
- Checked `gcloud auth list`: two other credentialed accounts exist locally
  (`terraform-service-account@quant-db.iam.gserviceaccount.com`,
  `1085513696285-compute@developer.gserviceaccount.com`). Both are
  `PERMISSION_DENIED: secretmanager.versions.access` on `marketmaking-test` —
  neither is authorized for this secret.
- Did **not** attempt `gcloud auth login` (interactive OAuth requiring the
  human) or any ADC/library-based route around the CLI's reauth gate — those
  are credential-changing/circumvention actions outside a read-only validation
  task's scope, and the harness correctly declined them.

Net effect: **no fresh `optic_fixtures_odds.jsonl` for WNBA could be produced
this session.** `fetch.polymarket` (BigQuery-backed, no `gcloud secrets` call)
was unaffected — see §2. Recommend re-running `fetch.optic --league wnba` once
`gcloud auth login` has been refreshed interactively (or scheduling the
day-of-game re-probe, ~07-28+, from a session with valid auth).

## 2. `fetch.polymarket` — works, no flags needed, pulled live WNBA data

League-agnostic bridge fetch (2-day BigQuery window via ADC, no `gcloud`
secret call) ran clean:

```
Wrote data/2026-07-23/12_00/polymarket_markets.jsonl (18,992 markets)
```

130 rows carry a `wnba-` slug, across **11 distinct fixtures**:

| fixture (poly slug) | date | forms posted |
|---|---|---|
| chi-nyl, conn-ind, dal-por, las-wsh, min-sea, phx-la | 2026-07-22 | **full board**: moneyline + spread + total + points + rebounds + assists |
| ind-sea, tor-min, por-las | 2026-07-28 | moneyline only |
| gsv-phx, atl-dal | 2026-07-29 | moneyline only |
| nyl-dal (orphan, no accompanying game market) | 2026-07-16 | 1 stray assists prop |

This matches the task's caveat almost exactly, with one nuance: the 6
**already-played** 2026-07-22 games are the ones carrying full boards (they
were fully priced pre-game and the rows are still inside BigQuery's 2-day
`last_updated` window); the **upcoming**, post-break 2026-07-28/29 games
currently have **moneyline only** — spread/total/player-prop boards are not
posted yet even 5-6 days out. **Player-prop validation against genuinely
still-open markets is PENDING a closer-to-game re-probe** (spread/total may
post a few days out per the brief; props typically post closer to game day).

## 3. Parse-level validation (pipeline's own `parse_question`, unmodified)

Ran `mappers.exchanges.polymarket.parse_question` against all 130 live
questions with `wnba.LEAGUE.POLYMARKET`:

| market_type | count |
|---|---|
| MONEYLINE | 11 |
| POINT_SPREAD | 17 |
| GAME_TOTAL | 29 |
| PLAYER_POINTS | 24 |
| PLAYER_REBOUNDS | 24 |
| PLAYER_ASSISTS | 25 |
| **unparsed** | **0** |

**100% parse coverage, 0 drops at the recognizer level** — every live WNBA
poly question shape is recognized by the 6 wired rules (`mlb_total_rule` /
`mlb_spread_rule` / `mlb_moneyline_rule` reused verbatim + the 3 new
`basketball_player_*_rule`s).

## 4. Fixture-resolution dry run (synthetic `Fixture` stand-ins — NOT a real Optic cross-check)

Because §1 blocked a live Optic pull, full end-to-end stamping (poly leg +
Optic fixture + Optic odds → `CanonicalRow.polymarket`) could not run. As a
partial substitute, I exercised the pipeline's actual
`mappers.pipeline._resolve_poly_markets` (unmodified, imported directly)
against 11 minimal `Fixture` stand-ins carrying the **real** team names/dates
observed in the live poly data — the identical technique
`tests/mappers/test_wnba_wiring.py`'s `_FX` class already uses for the alias
unit tests. This validates the **resolution logic** (name-matching,
date-disambiguation, the two-phase player-prop join, the alias overlay) but
**not** genuine cross-exchange price/line agreement — that remains blocked.

```
total live wnba poly markets: 130
resolved: 129   stats: {unparsed: 0, no_fixture: 1}
  GAME_TOTAL: 29   MONEYLINE: 11   PLAYER_ASSISTS: 24
  PLAYER_POINTS: 24   PLAYER_REBOUNDS: 24   POINT_SPREAD: 17
```

The 1 `no_fixture` drop: `wnba-nyl-dal-2026-07-16-assists-jonquel-jones-2pt5` —
a stray assists prop for a 2026-07-16 game with **no accompanying game-level
market** in this pull (the moneyline/total/spread for that game had already
rolled out of the 2-day bridge window). Correctly dropped rather than
mis-stamped — expected behavior, not a matcher defect.

**Caveat on the 6 already-played 07-22 fixtures:** my stand-ins assume a
matching Optic fixture exists for them. A *real* live Optic pull run "now"
(the games already concluded) may not return them as `active` fixtures at
all, in which case a true end-to-end run would show more `no_fixture` drops
for the 07-22 side than this dry run suggests. The 5 upcoming (07-28/29)
fixtures are the ones a genuinely live run right now would actually validate
against — and those currently carry moneyline only (§2).

## 5. `portlandfire` alias — CONFIRMED, all forms, both games

Portland Fire has fixtures on both 2026-07-22 (`dal-por`, full board) and
2026-07-28 (`por-las`, moneyline only). All **15** live Portland-Fire-side
markets resolved correctly under `team_alias_scope({"portlandfire": "portland
fire"})`:

- `wnba-dal-por-2026-07-22` (moneyline) + 4× spread + 4× total + points(2) +
  assists(1) + rebounds(1) = 13 markets → `Dallas Wings vs Portland Fire`
- `wnba-por-las-2026-07-28` (moneyline) → `Portland Fire vs Las Vegas Aces`

0 drops for the aliased franchise. Toronto Tempo (the other 2026 expansion
team) needed no alias and resolved via plain containment, as designed.

## 6. YESNO_AS_OU player-prop check — labels confirmed, direction internally consistent, cross-check PENDING

Live example (`Breanna Stewart: Points O/U 21.5`, condition_id
`0x29bf64e1...dea17`):

```json
{"outcome_label": "Yes", "outcome_index": 0}
{"outcome_label": "No",  "outcome_index": 1}
```

Confirms the code comment's claim: WNBA player props genuinely use **Yes/No**
labels (not Over/Under, unlike MLB's props) — the `YESNO_AS_OU` side_mode
choice in `basketball_player_points_rule` (and rebounds/assists) is the
correct one, not `_player_prop_rule`'s `OVER_UNDER` default. All 73 player-prop
markets across the 6 full-board fixtures follow this same Yes/No pair (the
`SideMode.YESNO_AS_OU` branch in `resolve_side_rows` hard-drops any market
whose labels aren't exactly `{yes, no}`, and 0 of the 73 dropped at parse —
§3 — so this holds uniformly, not just for the one sampled market).

Code maps `Yes → "over"`, `No → "under"` (`mappers/exchanges/polymarket.py`
`resolve_side_rows`, `SideMode.YESNO_AS_OU` branch) — sports-book-conventional
and the only sane reading of "Yes, this player will exceed the line." This is
**internally consistent** (nothing observed contradicts it), but a genuine
**optic-cross-check** (does Optic's own `player_points`/etc. line direction
agree, 0 conflicts) requires the live Optic pull that's blocked — no player
boards were confirmed still-open for the upcoming (07-28/29) games either
(§2). **Verdict: PENDING** a day-of-game re-probe (~07-28+) with working
`gcloud` auth, not a failure.

## 7. Correctness checks

- **Market-type mismatches: 0/130** — every parsed form's shape matches its
  assigned `MarketType` (§3, 100% parse rate, no ambiguous/cross-matched
  forms).
- **Line mismatches vs. Optic:** not checkable — blocked (§1).
- **Over/under balance:** every `GAME_TOTAL` and player-prop market has
  exactly 2 outcomes forming a complementary pair (`resolve_side_rows` hard-
  drops otherwise, and 0 dropped at parse) — spot-checked directly:
  `Dallas Wings vs. PortlandFire: O/U 174.5` → `Over`(idx 0)/`Under`(idx 1).
- **3 hand spot-checks:**
  1. **Moneyline** — `Golden State Valkyries vs. Phoenix Mercury` →
     `team_a='golden state valkyries'`, `team_b='phoenix mercury'`,
     `side_mode=TEAM_LABEL` — correct, matches the `gsv-phx` 2026-07-29
     fixture.
  2. **Spread, date-disambiguation** — Las Vegas Aces play twice in this pull
     (`las-wsh` 07-22 home, `por-las` 07-28 away). `Spread: Las Vegas Aces
     (-5.5)` (slug `wnba-las-wsh-2026-07-22-spread-away-5pt5`) parses to
     `entity='las vegas aces', line=-5.5`; outcome labels are the literal team
     names (`"Las Vegas Aces"` / `"Washington Mystics"`), and
     `_match_poly_fixture`'s exact-date-wins rule correctly ties this to the
     07-22 fixture, not the 07-28 one — confirmed via the dry run (17/17
     spread markets resolved, 0 cross-date leakage).
  3. **Player prop** — `Breanna Stewart: Points O/U 21.5` → `Yes`/`No` labels,
     `YESNO_AS_OU`, line `21.5` (§6).

## 8. Drops

- **Parse-level: 0/130** (§3).
- **Fixture-resolution dry run: 1/130** — the orphaned `2026-07-16` assists
  prop (§4), an expected drop (stale market, no sibling game-level market to
  join against), not a mapper defect.
- Real production drop accounting (`stamped` / `dropped` / `no_fixture` /
  `non-game-line` / `agree` / `conflict-dropped`) requires the live Optic pull
  — blocked (§1). As a proxy, I ran the **actual** `mappers.run` CLI
  end-to-end against the live `polymarket_markets.jsonl` plus a real (but
  non-WNBA — MLS, already on disk from a prior session) `optic_fixtures_odds.jsonl`,
  to confirm the wired WNBA code path is crash-free:
  ```
  --- wnba ---
  optic: 0 fixtures loaded
  polymarket [wnba]: 0 stamped, 0 dropped (optic didn't price), 130 no fixture,
                      0 non-game-line, 0 agree, 0 conflict-dropped
  ```
  Exit 0, stderr otherwise clean — no exceptions. (Confirmed separately that
  running with the optic file simply *absent* raises `FileNotFoundError` at
  `optic.load_fixtures`, expected/self-induced, not a WNBA-specific bug.)

## 9. Test suite

`tests/mappers/test_wnba_wiring.py`: **19/19 passed** (League registration,
`KALSHI`/`PX is None`, `POLYMARKET` config identity, `OPTIC.table_types` 6-key
set, the 4 `portlandfire`-alias tests, plus the NBA/NCAAB parity tests).

## Overall verdict

- **Task 3 CLI wiring (`fetch.optic --league wnba`): CONFIRMED working.** Not a
  regression — reached the live secret-fetch call cleanly.
- **Live end-to-end Optic pull: BLOCKED this session** by an expired/
  non-interactive `gcloud` reauth requirement, unrelated to Task 2/3 code.
  `fetch.polymarket` (BigQuery/ADC-backed) was unaffected and pulled genuine
  live WNBA data (130 rows / 11 fixtures).
- **Parsing (100% of 6 forms, 0 drops) and fixture-resolution logic
  (129/130 in a synthetic-fixture dry run, 1 expected orphan drop) both check
  out** against live Polymarket data, using the pipeline's own unmodified
  code paths.
- **`portlandfire` alias: CONFIRMED**, all 15 live markets across both its
  fixtures.
- **YESNO_AS_OU labeling: label choice CONFIRMED live (Yes/No, not Over/
  Under); Yes→over/No→under direction internally consistent; a true
  optic-agreement cross-check is PENDING** — no live Optic pull this session,
  and no player-prop boards yet posted for the only currently-upcoming
  fixtures (07-28/29 are moneyline-only so far).
- **0 market-type mismatches, 0 line-mismatch checks possible (blocked), O/U
  balance holds, 3/3 hand spot-checks correct.**
- **Recommendation:** re-run `fetch.optic --league wnba
  --horizon-hours <168-240>` (default 48h horizon won't reach the 07-28/29
  resumption games) from a session with valid `gcloud` auth, ideally closer to
  07-28 once player-prop boards are posted, to close out the optic-cross-check
  and YESNO_AS_OU-vs-Optic verdicts left PENDING here.
