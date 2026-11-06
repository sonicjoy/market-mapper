> Historical. Tip/console references are retired; see CLAUDE.md.

# Gap-propose skip reduction (prod drain follow-up)

**Date:** 2026-09-28  
**GitLab work item:** [#31](https://gitlab.com/whiteswandata/marketmaking/mmmapper/-/work_items/31)  
**Parent context:** Drain waves shipped in [!361](https://gitlab.com/whiteswandata/marketmaking/mmmapper/-/merge_requests/361) / [#26](https://gitlab.com/whiteswandata/marketmaking/mmmapper/-/work_items/26). First prod worker `gap-propose-worker-1790624458` went idle after walking all books per league card.

**Goal:** Work only **actionable** skips: both the source book and Optic already have the rows, and harvest still did not pin. **Not actionable** means the source book or Optic does not have the data — leave those on the ledger until that data shows up. Do not loosen `names_fit` or bypass `pin_flow.draft_and_verify`.

**Status:** Phases 0–6 are implemented. [!396](https://gitlab.com/whiteswandata/marketmaking/mmmapper/-/merge_requests/396) is on `test` (`e3ac319e`): fight props read the sibling `KXUFCFIGHT` markets, and a wired Underdog total pins both Optic abbreviations. [#69](https://gitlab.com/whiteswandata/marketmaking/mmmapper/-/work_items/69) stays open until a worker on that image rewrites `disambig` and `name_mismatch` (phase 7.4). Prod ledger below is the latest row per key on 2026-09-29.

## Evidence (prod ledger, worker since `2026-09-28 19:42:00` UTC)

Terminal mix (all outcomes, not only `skipped`):

| Outcome | n | Notes |
|---------|---:|-------|
| `needs_probe` | 353 | Mostly Novig/Huddle-style “record demand, alias TBD” |
| `expected_residual` | 402 | `missing_optic`, `title_miss`, `completed_stale`, … |
| `horizon_wait` | 173 | `outside_horizon` — re-walk after 24h |
| `maker_lag` | 59 | `already_mapped` |
| **`skipped`** | **104** | **This project’s primary focus** |
| `needs_league` | 12 | Listed onboard path |
| `pinned` | 7 | Drafted (mostly `unknown` proposals) |

**`outcome = skipped` by reason**

| Reason | n | Where it hurts |
|--------|---:|----------------|
| `no_pin` | 54 | Walked, no pin, no finer skip row — NCAAF 1H (24), Novig `unknown` (7), crypto tennis (5), NFL periods (4) |
| `collision` | 18 | Kalshi ITF on `unknown` card (17) |
| `stamp_residual` | 16 | Polymarket league prefix already satisfied |
| `missing_tickers` | 5 | Poly prefix (`lv`, `min`, `nhl`, …) |
| `no_optic_book` | 4 | Poly prefix, no Optic book |
| `disambig` | 3 | Kalshi boxing |
| `verify_blocked` | 2 | Crypto CONL — Cart gate |
| `name_mismatch` | 2 | Crypto CONL / friendlies |

**Card-level:** Most league cards were `action=skip` (no *new* pins vs open Review). Four `unknown` Review cards did propose (`prop_f0ea9798…`, `prop_95c6a102…`, `prop_da41b529…`, `prop_be4bae2d…`).

## Actionable vs not actionable

A reason is **not actionable** when the source book (Kalshi, crypto.com, Polymarket, Novig, …) or the target (Optic fixture, Optic league, catalogue participant) does not have the row a pin would bind. Harvest cannot invent that row.

A reason is **actionable** when both sides already have the data and the skip is our matcher, a collision, Cart verify, an unbuilt probe, or an unclassified walk (`no_pin`).

`maker_lag` / `already_mapped` (59) and `pinned` (7) are neither: the alias is already on the tip, or a pin was drafted.

### Not actionable (data missing) — do not build a pin path

| Reason | n | Missing side | Why |
|--------|--:|--------------|-----|
| `outside_horizon` | 173 | target | Optic has not published this fixture yet. Ledger already re-walks after 24h. |
| `missing_optic` | 141 | target | No Optic fixture or league id to bind. |
| `completed_stale` | 114 | target | Fixture already finished; no live Optic row left. |
| `tournament_future` | 12 | target | Futures contract; no Optic match fixture. |
| `needs_league` | 12 | target | Venue token present, no single Optic league. |
| `missing_tickers` | 5 | source | Polymarket prefix has no US or official events (`lv`, `min`, `nhl`, …). |
| `no_optic_book` | 4 | target | League has no Optic book (SETKA / Modus inners). |

**452 keys.** They stay terminal on the ledger. The only code change allowed here is a clearer reason label, not a guessed pin.

`needs_probe` on Huddle is the same class when the selection id carries no league: source has no league token. Do not probe those.

### Actionable (both sides have data) — this project

| Reason | n | What to do |
|--------|--:|------------|
| `needs_probe` | 353 | First summary. A later read of the same window splits the rows by book: Novig 232 ([#34](https://gitlab.com/whiteswandata/marketmaking/mmmapper/-/work_items/34)), ProphetX 219 ([#41](https://gitlab.com/whiteswandata/marketmaking/mmmapper/-/work_items/41)), Underdog 182 ([#42](https://gitlab.com/whiteswandata/marketmaking/mmmapper/-/work_items/42)). Each book probes when Optic has the fixture. Huddle with no league stays not actionable. |
| `title_miss` | 135 | Kalshi ticker or title exists; we ignored the prefix or did not parse a fixture. Teach the market rule, or name it as a deliberate ignore after a sample. |
| `no_pin` | 54 | Walked with no finer reason. Split before any other fix (Phase 1). Largest piles: NCAAF 1H (24), Novig `unknown` (7), crypto tennis (5), NFL periods (4). |
| `collision` | 18 | Both names exist; code already owned (Kalshi ITF on `unknown`, 17). |
| `stamp_residual` | 16 | Polymarket prefix already on the tip; events existed and no new alias drafted. |
| `disambig` | 3 | Several Optic candidates (Kalshi boxing). |
| `verify_blocked` | 2 | Crypto CONL failed Cart verify. |
| `name_mismatch` | 2 | Crypto UNL / friendlies; names exist, `names_fit` refused. |

**583 keys** before the Huddle slice of `needs_probe` is moved to not actionable. `no_pin` is actionable only until Phase 1 shows a given key was actually missing source or Optic data.

**Baseline query** (re-run after each slice):

```sql
select outcome, reason, count(*) as n
from `rs-marketmaking.markets_us.mapping_gap_ledger`
where run_at > timestamp_sub(current_timestamp(), interval 7 day)
  and book not in ('_reopen', 'rfq')
group by 1, 2
order by outcome, n desc;
```

## Invariants

- All four surfaces: gap sweeper, mapper fail-safe, console/Chat, Cart Verify → `pin_flow.draft_and_verify` (see `teach-gap-sweeper` rule).
- Do not edit archive TOML as the live fix.
- Not-actionable reasons stay terminal. Do not draft a pin when Optic or the source book has no row.
- `stamp_residual` stays terminal; relabel to `expected_residual` only when the prefix is already satisfied, not when an alias should still bind.
- Feature flags for new behavior default **on** unless Joe asks otherwise.

## Phase 0 — Measure & prioritize (no product code)

- [x] **0.1** Grafana / BQ panel: top `skipped` + `no_pin` by `(book, league_token, reason)` with sample keys (reuse `docs/mapping-coverage-grafana.md` pattern).
- [x] **0.2** Join `skipped` keys to `reporting_us.rfq_latest` demand for last 7d; rank slices by RFQ demand, not raw count.
- [x] **0.3** Confirm which `no_pin` keys were walked but hit pin-slot / walk limits vs probe returned empty skip reason.

Prod `rs-marketmaking`, latest row per `(book, key)`, 2026-09-29. Ranked by ledger `demand` (the RFQ demand harvest copied). The live-leg join is the second panel in `docs/mapping-coverage-grafana.md`.

| Book | League | Reason | Keys | Demand | Actionable |
|------|--------|--------|-----:|-------:|------------|
| polymarket | unknown | `no_optic_book` | 4 | 77,789 | no |
| polymarket | nhl | `missing_us_events` | 1 | 17,118 | no |
| polymarket | unknown | `missing_tickers` | 3 | 15,469 | no |
| polymarket | russia_khl | `stamp_residual` | 1 | 3,344 | already residual on new walks |
| kalshi | itf_men | `collision` | 8 | 2,806 | seated; fail-closed |
| crypto | mlb | `unmapped` | 147 | 1,963 | not a phase in this plan |
| kalshi | unknown | `collision` | 38 | 1,861 | not ITF seating |
| crypto | ncaaf | `name_mismatch` | 124 | 1,039 | 7.4 comparison |
| kalshi | unknown | `disambig` | 17 | 601 | fight props, 7.4 |

`no_pin` is 167 latest keys, demand 443, all still `skipped`. New walks do not write it: a walk with neither pin nor skip is `walk_without_outcome` (3 keys) or the probe reason, and a key the walk never reached is `not_walked`. None of those `not_walked` rows are still the latest. The 167 cannot be split into slot-full versus empty-probe from the ledger; they are the pre-recorder terminals.

## Phase 1 — `no_pin` transparency (quick win)

- [x] **1.1** When harvest walks a key and drafts nothing, append an explicit skip reason (`walk_without_outcome`, the probe kind, or `aliases_complete`) instead of falling through to ledger `no_pin`. A key the walk never reached stays `not_walked`.
- [x] **1.2** Tests in `tests/control_plane/test_gap_ledger.py` (or nearest) lock reason → outcome mapping.
- [x] **1.3** Docs: `gap-propose.md` — `no_pin` should become rare / diagnostic only.

**Success:** `no_pin` count drops on next full drain; Slack/ledger summary lists actionable reasons. The recorder is on the tip. The 167 latest `no_pin` keys drop when their leagues are reopened after this image is on prod.

## Phase 2 — NCAAF / NFL period markets (largest `no_pin` demand)

- [x] **2.1** Classify Kalshi `KXNCAAF1H-*`, `KXNFL1H-*`, `KXNFL1Q-*`: market rules vs alias vs `expected_residual` (prop/stale).
- [x] **2.2** If fixable: `harvest_missing_market_rules` and/or alias path through `draft_and_verify`; mapper bootstrap for any new class.
- [x] **2.3** Gap sweeper + Chat skill fixture for one ticker per class.

Latest prod rows: `KXNCAAF1H` 172 `already_mapped` (demand 152,051), 14 `missing_optic`, 81 stale `no_pin` (demand 87). `KXNFL1H` 13 `already_mapped`. `KXNFL1Q` 2 stale `no_pin` (demand 22) and 2 `missing_optic`. The mapper parses these moneylines (`test_parse_event_ticker_ncaaf_1h` and the NFL 1H/1Q ticker tests). `missing_optic` stays not actionable. The stale `no_pin` rows leave when those leagues are reopened.

**Success:** NCAAF/NFL period keys pin or land in `expected_residual` with stable reason; demand on those tickers falls in `rfq_latest`.

## Phase 3 — Alias probe where Optic already has the fixture

Novig [#34](https://gitlab.com/whiteswandata/marketmaking/mmmapper/-/work_items/34), ProphetX [#41](https://gitlab.com/whiteswandata/marketmaking/mmmapper/-/work_items/41), and Underdog [#42](https://gitlab.com/whiteswandata/marketmaking/mmmapper/-/work_items/42) each replace a `needs_probe` close with the shared alias probe. A key with no Optic fixture stays not actionable.

- [x] **3.1** Novig: replace the record-only stub. Close from the Optic id the live mapper already joins.
- [x] **3.2** ProphetX: after tournament onboard, probe the fixture instead of writing `needs_probe`.
- [x] **3.3** Underdog: after the league is on the tip, probe the fixture instead of writing `needs_probe`.
- [x] **3.4** Lock each book with `test_pin_flow` and the nearest harvest test. ProphetX: `test_verify_pins_keeps_px_code` and `test_gap_fix_px.py`. Underdog: `test_verify_pins_keeps_underdog_code` and `test_gap_fix_listed_onboard.py`. Novig closes from the Optic id and does not draft an alias pin; `probe_wired_novig` is locked in that same harvest file.

**Success:** `needs_probe` remains only for keys that still have no source league or no Optic fixture.

## Phase 4 — Kalshi ITF `collision` on `unknown` card

- [x] **4.1** Trace `KXITFMATCH` / `KXITFWMATCH` on `unknown`: league resolver vs tip slug (`itf_men` / `itf_women`).
- [x] **4.2** If league mis-bucketed: fix planner resolver only (no fifth matcher). If true abbr collision: `pin_shared_optic_abbr` / harvest duplicate abbr path per teach-gap-sweeper.
- [x] **4.3** Regression: ITF keys seat on correct league card, not `unknown`.

`itf_match_slug` seats `KXITFMATCH` on `itf_men` and `KXITFWMATCH` on `itf_women` when that league is on the tip (`test_itf_match_seats_on_the_tip_league`, `test_itf_women_seats_when_the_league_is_on_the_tip`). Latest prod collisions for those series are on `itf_men` (8 keys, demand 2,806) and `itf_women` (11 keys), which is a fail-closed code collision, not an unknown-card misbucket. Do not remove a code a new claimant does not already own.

## Phase 5 — Polymarket `stamp_residual` (actionable only)

- [x] **5.1** For each of the 16 prefixes, check whether an alias should still bind. If the prefix is already satisfied, relabel `expected_residual` and stop.
- [x] **5.2** Leave `missing_tickers` and `no_optic_book` in the not-actionable table. No pin.
- [x] **5.3** Update `polymarket-mapping-gaps.md` + `rfq-unmapped-leg-coverage` skill.

`stamp_residual` is in `_residual`, so a new walk stores `expected_residual`. The high-demand prefixes from the 2026-09-29 14:30 drain (`itfme`, `itfwo`, `nfl`, `mlb`, `ufc`, `atp`, `cfb`, `unl`) took that outcome. Older latest rows still say `skipped` / `stamp_residual` (`russia_khl`, `euroleague`, `atp_doubles`) until those leagues are reopened. `missing_tickers` (demand 15,469) and `no_optic_book` (demand 77,789) stay not actionable.

## Phase 6 — Crypto verify / name fit (CONL, friendlies)

- [x] **6.1** Reproduce `verify_blocked` on `NX.F.OPT.CONL-*` through Cart Verify kernel. `test_conl_symbol_blocked_by_cart_keeps_the_gate_text` refuses `NX.F.OPT.CONL-1` in `draft_and_verify` and stores the gate sentence. Six latest prod rows on `concacaf_nations_league` still say the blanket `verify_blocked` (demand 25) because they were written before that recorder; a reopen rewrites them with the gate text.
- [x] **6.2** `name_mismatch` on UNL / FIFAF: `names_fit` accepts the conjunction `and` for Bosnia and Herzegovina (same 2026-10-02 18:45 kickoff as Optic `Bosnia-Herzegovina` / Sweden). Mozambique @ Botswana on 2026-09-30 has no Optic row, so it stays `name_mismatch`. `names_close` is unchanged.

## Phase 7 — Read venue fields before parsing tickers and titles ([#69](https://gitlab.com/whiteswandata/marketmaking/mmmapper/-/work_items/69))

Kalshi says not to parse tickers. The probe still derived identity from strings the venue sends as fields. Root cause on the test drain: `_fetch_paged` sent `status=open`, and a tennis or fight market settles within hours, so `KXATPCHALLENGERMATCH-*` events had no markets and stayed `disambig`.

- [x] **7.1** Kalshi: fetch one event's markets in any status (series stays open-only). Codes come off the markets for every league; team leagues fall back to the ticker grammar. Sides for surname titles already expand from `yes_sub_title`. The probe never used the ticker's date, so there is no kickoff-day change to make.
- [x] **7.2** Kalshi evidence: each market's `custom_strike` participant id rides on the pin as `kalshi:code:<code>:competitor:<uuid>`. Not an alias kind; that needs Joe's call.
- [x] **7.3** crypto.com: sides from `meta_home_participant` / `meta_away_participant` (`home_name` / `away_name` on the catalogue row); `meta_name` only as the fallback. One helper, `catalogue_sides`, feeds the Optic match and league discovery.
- [ ] **7.4** Re-run the test drain and compare `disambig` and `name_mismatch`.

Out of scope: loosening `names_fit`, Regalado initials, `walk_without_outcome`.

## Verification (each MR)

1. `bash scripts/run-quality.sh` + pyright on touched paths.
2. Test cluster drain: memory unchanged; ledger row mix shifts as intended.
3. Prod: comment on work item with before/after ledger query for affected `(outcome, reason)`.

## Suggested delivery order

`Phase 0` → `Phase 1` → `Phase 2` → `Phase 3` → `Phase 4` → `Phase 5` → `Phase 6`  
Ship **one phase per MR to `test`**, verify drain, then promote with `test` → `main` (merge `main` into `test` first per release rule).

`title_miss` (135) is actionable and folds into Phase 2 when the sample is a market-rule miss. Keys Phase 1 reclassifies as missing Optic or source data leave the actionable list.

## Out of scope

- Every row in **Not actionable** above (`missing_optic`, `outside_horizon`, `completed_stale`, `tournament_future`, `needs_league`, `missing_tickers`, `no_optic_book`, Huddle with no league token).
- `maker_lag` / `already_mapped`.
- Raising worker CPU above 1 core (infra follow-up from #26).
- Bulk AI suggest for skips (already default-on; not a substitute for unique-bind fixes).
