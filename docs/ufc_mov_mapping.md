# UFC Method of Victory / Method of Finish mapping

Design note for mapping UFC method markets across Kalshi, Optic, and
(later) crypto.com / Polymarket. Written 2026-07-24 after the
market-mapping-test pipeline crash that morning; supersedes the
"no reconcilable target" rationale in the `ufc.py` comments (the
conclusion — unmapped for now — stands, but the reasoning and the
re-enable trigger below are different).

## Background: the 2026-07-24 crash

The 07:31:59 UTC pipeline run on market-mapping-test died in
`optic.build_rows`:

    ValueError: Optic odd 22133-17237-2026-07:method_of_victory:
    abdul_hussein_-_decision: game-scoped YES_NO with
    normalized_selection 'abdul_hussein' name='Abdul Hussein - Decision'

Root cause: Optic changed the odd shape. Nick's March 2026 samples
(`docs/nick-instructions.md`) show `method_of_victory` with a *blank*
`selection` and the outcome label only in `name` — which is what the
game-scoped YES_NO branch handles. Live data now ships
`selection="Abdul Hussein"`, `team_id` set, and the method only as a
`name` suffix (`"Abdul Hussein - Decision"`). That shape falls through
every branch to the raise. The same feed change hit `round_betting`
(patched in `7e11a2f`). Reproduced locally against
`data/2026-07-24/07_15` at `9c92197` (the commit the VM was running);
the failing run predates Joe's fixes, which the reflog shows deployed
at 08:20 (`9f3e38b`, unmaps MoV/MoF) and 08:54 (`7e11a2f`).

The deeper modelling error: `METHOD_OF_VICTORY` was declared
`(Scope.GAME, Shape.YES_NO)`. The market is fighter-scoped — every
non-Draw odd names a fighter and carries a `team_id`, structurally the
same as `team_to_win_by_knockout_submission_dq`, which maps fine as
`(Scope.TEAM, Shape.YES_NO)`.

## What the venues actually offer

Probed via Kalshi's public API (`/trade-api/v2/series`, `/events`,
`/markets`), 2026-07-24. Kalshi has 22 UFC series; the fight-level
tradeable ones:

| Series | Market | Structure |
|---|---|---|
| `KXUFCFIGHT` | Moneyline | per fighter (mapped today) |
| `KXUFCMOV` | Method of Victory | 7 legs/fight: fighter × {KO/TKO/DQ, Submission, Decision} + Draw/No Contest (`-DRAW`) |
| `KXUFCMOF` | Method of Finish | 4 legs/fight, fight-scoped: {KO/TKO/DQ, Submission, Decision, Draw/No Contest} |
| `KXUFCVICROUND` | Round of Victory | per fighter/round |
| `KXUFCROUNDS` | Total Rounds | "Fight ends before round N" (yes = under N−0.5) |
| `KXUFCDISTANCE` | To Go The Distance | yes/no |

`MOV` / `MOF` / `ROUNDS` / `DISTANCE` / `VICROUND` are enabled in
`mappers/vocab/combat_kalshi.py` (`ufc_kalshi_config`). Optic
counterparts: `round_betting`, `total_rounds`, `go_the_distance` /
`fight_to_go_the_distance`.

**Listing timing:** the July 18 card's MOV legs opened
2026-07-17T16:17Z — the day before the fight — and our snapshots have
only ever caught `KXUFCFIGHT`, so "Kalshi doesn't list MoV" was a
sampling artifact, not a fact. Expect each card's method markets to
appear roughly a day out.

Polymarket quotes only the fight-scoped "Will the fight be won by
KO or TKO?" / "won by submission?" forms (per-fighter forms
deliberately deferred in the polymarket parity work). crypto.com's
catalogue has per-fighter "Method of Victory" / "Method of Finish"
contract types but no live UFC rows in current snapshots — labels
unverified until a card is listed there.

## Kalshi settlement rules (verified)

From `https://assets.kalshi.com/contract_terms/FIGHTMETHODOFVICTORY.pdf`,
fetched and read 2026-07-24. The load-bearing facts:

- **KO/TKO/DQ**: TKO explicitly includes referee stoppage, corner
  stoppage (towel / verbal retirement), and doctor stoppage. DQ is
  bundled into the bucket.
- **Submission**: tap (mat, opponent, or self) or verbal submission.
  *Technical submissions* (ref stops the fight, no tap) count as
  submission. *Verbal submission to strikes* counts as TKO unless the
  official result records it as a submission.
- **Decision**: unanimous, split, majority, **and technical decision**
  all settle the Decision leg ("a win by points includes unanimous
  decision, technical decision, majority decision and split
  decision").
- **Draw leg pays on Draw OR No Contest.** On an NC all
  victory-method legs resolve No.
- **Overturned results** (appeals, failed drug tests) after expiration
  do not revise settlement; the official result at the conclusion of
  the bout, per the Source Agency hierarchy, governs.
- **No void path.** Cancellation, postponement beyond 7 days, fighter
  replacement, or missed-weight cancellation all *resolve to the last
  fair price at Kalshi's sole discretion*. Reschedule within 7 days
  tracks the bout.

`KXUFCMOF` has its **own** contract terms document
(`FIGHTMETHODOFFINISH.pdf` — different content hash, not yet read).
Read it before wiring MOF; do not assume it mirrors MOV.

Spot check against a settled card: `KXUFCMOV-26JUL18DUUSM` (Du Plessis
vs. Usman) settled DUDEC=Yes, all other legs No — consistent with a
Du Plessis decision win under the rules above.

## The like-for-like principle

We only take positions on venues (Kalshi, Polymarket, crypto.com) —
never on Optic, which is a pricing input. That splits "settlement
rules must match" into two different requirements:

**Venue ↔ venue.** A merge asserts the two contracts settle
identically in every reachable state: method buckets, draw/NC
handling, DQ inclusion, cancellation treatment. A mismatch is a
direct P&L event — we hedge leg A with leg B and one settles against
us. Merges here require a one-time human read of both venues'
settlement terms, recorded as a provenance comment at the config
(per repo convention).

**Optic → venue.** Optic has no settlement rules to match — it
aggregates books with heterogeneous house rules, and the bucket label
is the only semantics we get. The requirement is that the Optic
bucket we price from is the *same proposition* as the venue leg we
quote, to the resolution the labels can express. Mis-bucketing
(pricing Kalshi's KO/TKO/**DQ** off Optic's plain `KO/TKO`) is a
systematic, avoidable fair-value error. Label-invisible differences
(how some book classifies a technical decision) are unavoidable basis
noise in the fair price, not a settlement exposure.

### Where like-for-like holds

- Kalshi MOV fighter legs ↔ Optic `method_of_victory` odds with name
  suffixes `- KO/TKO/DQ`, `- Submission`, `- Decision`: exact label
  matches. These are the mappable pairs.
- Kalshi MOF legs ↔ Optic `method_of_ending`
  (`ko_tko_dq` / `submission` / `decision`): exact label matches
  (pending the MOF PDF read). Note `method_of_ending` is the Optic
  market the old `ufc.py` comment said didn't exist ("Optic has no
  method_of_finish market") — it does, under a different name.
- Polymarket "won by KO or TKO?" ↔ Optic `win_by_ko_tko`: already
  wired as `GAME_WIN_BY_KOTKO`.

### Where it breaks

- **Kalshi Draw/No Contest ↔ Optic `Draw`: not like-for-like.**
  Sportsbooks conventionally void MoV bets on an NC, so a book's Draw
  price estimates P(draw) only; Kalshi's leg pays P(draw) + P(NC),
  and NCs are more common than draws in the UFC. Leave the draw legs
  (MOV and MOF) unmapped. If trading wants to quote them, the NC
  uplift is a pricing-layer decision, not a mapping merge.
- **Kalshi MOF `KOTKODQ` ↔ Polymarket "won by KO or TKO?": not
  like-for-like** (DQ differs). The two venues' method markets must
  not merge with each other.
- Optic's overlapping extra buckets (`- KO/TKO`,
  `- KO/TKO, DQ or Submission`) have no Kalshi counterpart —
  `method_of_victory` is an aggregate of different books' bucketings,
  not one coherent N-way market. Drop the non-matching buckets;
  never fold them into a neighbour.

## Design

1. **`METHOD_OF_VICTORY` becomes `(Scope.TEAM, Shape.YES_NO)`** —
   entity = fighter from `team_id`, `side="yes"`, method in
   `grouping_key`. `METHOD_OF_FINISH` stays `(Scope.GAME,
   Shape.YES_NO)` with method in `grouping_key`, fed by Optic
   `method_of_ending` and Kalshi `KXUFCMOF`.

2. **Canonical method vocabulary encodes the full proposition as a
   set of primitive methods**, with draw-handling explicit:
   `ko_tko_dq`, `submission`, `decision`, `ko_tko`,
   `ko_tko_dq_submission`, `draw`, `draw_or_nc`. Rows merge only on
   identical keys, so like-for-like stops being a review-time
   discipline and becomes a property of the key: Kalshi `DRAWDRAW`
   (`draw_or_nc`) can never meet Optic `Draw` (`draw`), and Kalshi's
   `ko_tko_dq` can never meet Polymarket's `ko_tko`, even by
   accident.

3. **Optic needs a per-market bucketer hook.** `OpticConfig.
   table_types` is a flat `market_id → MarketType` dict; MoV needs
   `market_id` + name-suffix → `(MarketType, grouping_key)`. The
   fighter comes from `selection`/`team_id` (no name parsing);
   strip the fighter prefix and canonicalize the ` - <Method>`
   suffix against a whitelist {KO/TKO/DQ, Submission, Decision}.
   Unrecognized suffixes are *skipped* (they're expected — see the
   extra buckets above), never raised. This is the same
   "fighter+method bucketer" Joe's and Victor's comments already
   point at.

4. **Kalshi side** (as built): the market type comes from Kalshi's
   typed scope in `mappers/vocab/kalshi_scopes.py` (`Sport.MMA`:
   "Method of Victory", "Method of Finish", "Round of Victory",
   "Round of Finish", "Go the Distance"). The method comes from
   `custom_strike` "Method" via `kalshi_method_label_key`
   (`mappers/fight_props.py`), the fighter from `custom_strike`'s
   competitor id (`strike_side`), the round from `custom_strike`
   "Round"; see `_parse_fight_prop` in `mappers/exchanges/kalshi.py`.
   Leg tickers are never read. Draw legs get `draw_or_nc` and have
   no Optic counterpart to merge with.

5. **Not in scope until verified**: crypto.com MoV/MoF (no live
   samples; Joe's observation that crypto splits KO/TKO from DQ
   means its buckets likely *don't* merge with Kalshi's — the keys
   will decide once real labels are seen); Polymarket per-fighter
   method questions (still deferred in the parity work); the
   `KXUFCVICROUND`/`KXUFCROUNDS`/`KXUFCDISTANCE` series (available,
   with already-mapped Optic counterparts `round_betting` /
   `total_rounds` / `go_the_distance` — enabled 2026-09-04).

## Verification plan before going live

1. Read `FIGHTMETHODOFFINISH.pdf`; confirm MOF buckets and draw/NC
   handling match the MOV reading above.
2. Capture the 26JUL25 card live: Kalshi MOV/MOF legs should list
   ~1 day out (from ~July 25 midday UTC). Diff the typed
   `custom_strike` Method/Round values and subtitles against this doc.
3. Fixture-based test: Optic `method_of_victory` odds in the new
   shape (fighter in `selection`) map to fighter-scoped rows with the
   right keys; the extra buckets and Draw are skipped without error
   (extends the `9f3e38b` regression test rather than replacing it).
4. After the card settles, spot-check settlement of every mapped leg
   against the official result, as done for DUUSM above.

## Live verification (2026-08-07)

Probed Kalshi open markets + contract PDFs before enabling MOV/MOF/ROUNDS:

| Series | Sample event | Leg suffixes (live) |
|---|---|---|
| `KXUFCMOV` | `KXUFCMOV-26AUG08JOHVAZ` | `{TEAM}KOTKODQ`, `{TEAM}SUB`, `{TEAM}DEC`, `DRAW` (not `DRAWDRAW`) |
| `KXUFCMOF` | `KXUFCMOF-26AUG08JOHVAZ` | `KOTKODQ`, `SUB`, `DEC`, `DRAW` |
| `KXUFCROUNDS` | `KXUFCROUNDS-26AUG08JOHVAZ` | integer `N`; yes = "Fight ends before round N" |

- MOF PDF (`FIGHTMETHODOFFINISH.pdf`) shares the same method-bucket template as MOV; live `yes_sub_title` confirms Draw/No Contest on both DRAW legs.
- ROUNDS polarity: yes = under `(N−0.5)`, no = over `(N−0.5)` (`FIGHTROUNDCOUNT.pdf`: "before Round N" = rounds 1..N−1). Kalshi `build_rows` inverts standard total yes=over for `TOTAL_ROUNDS` only.
- The suffixes above are evidence only; the mapper does not read them.
  Enabled via the `Sport.MMA` scopes in `mappers/vocab/kalshi_scopes.py`.
  `VICROUND` grouping_key comes from Kalshi `yes_sub_title` via
  `canonicalize_fight_prop_key`, checked against `custom_strike` "Round".

## Operational note (for the risk side)

Kalshi UFC method contracts have **no void path**: cancellations,
>7-day postponements, and fighter replacements resolve to the last
fair price at Kalshi's discretion. A position held into a cancelled
bout is marked wherever Kalshi says, not refunded. Worth knowing
before we quote these markets at size.
