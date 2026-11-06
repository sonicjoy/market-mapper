# Kalshi missing GAME ticker problems

Our NCAAB pipeline requires the GAME (moneyline) market to
disambiguate variable-width team abbreviations in the concatenated
game suffix (e.g. splitting "QUCCARK" into QUC + CARK).  When the
GAME ticker is absent or unmatchable, `_disambiguate_teams` fails
and the entire game group is skipped — losing SPREAD, TOTAL, and
all other market types too.

Relying on GAME-level markets is the current implementation (approach
6 in `kalshi-abbrevs-notes.md`; described fully in
`multi-sport-draft-refactor.md` §"Kalshi variable-length team
codes").  If too many betting opportunities are missed due to absent
GAME markets, we should revisit the alternative approaches documented
in `kalshi-abbrevs-notes.md` — particularly title-based game
identification (approach 5), which does not depend on GAME markets
existing.

Two distinct causes produce this same failure.

---

## 1. Rescheduled games (GAME ticker has wrong date)

Discovered 2026-03-04 while investigating "stale Kalshi source_id"
warnings on NCAAB 2026-02-25.

### The symptom

The Optic verification step reports two kinds of warnings for the
same game:

    optic: 2026-02-25 MORG@SCST — Kalshi date mismatch (FEB14 ≠ FEB25) ...
    Optic 18107-33911-2026-02-25: Kalshi source_id '...SPREAD-26FEB25MORGSCST-SCST1'
      but no match — no moneyline market — game group skipped

We initially assumed these were Optic data errors — stale
source_ids carried over from previous matchups.  They are not.

### The root cause: Kalshi ticker dates and rescheduled games

Kalshi embeds the **originally scheduled** game date in the ticker:

    KXNCAAMBGAME-26FEB14MORGSCST      ← original date (Feb 14)

When a game is rescheduled, Kalshi does **not** update the GAME
(moneyline) ticker.  Instead, it creates fresh tickers for other
market types with the new date:

    KXNCAAMBSPREAD-26FEB25MORGSCST    ← new date (Feb 25)
    KXNCAAMBTOTAL-26FEB25MORGSCST     ← new date (Feb 25)
    KXNCAAMB1HSPREAD-26FEB25MORGSCST  ← new date (Feb 25)
    KXNCAAMB1HTOTAL-26FEB25MORGSCST   ← new date (Feb 25)
    KXNCAAMB1HWINNER-26FEB25MORGSCST  ← new date (Feb 25)

The GAME ticker still says FEB14.  The `rules_primary` field
confirms this: "...originally scheduled for Feb 14, 2026".

### The failure cascade

1. **GAME ticker skipped**: Our Kalshi parser extracts `2026-02-14`
   from `KXNCAAMBGAME-26FEB14MORGSCST`.  The `MatchKey` lookup
   against the fixture index (which has the game under `2026-02-25`)
   returns None.  The ticker is skipped as "other-date".

2. **No moneyline → entire game group skipped**: We need the GAME
   (moneyline) market to disambiguate team abbreviations in the
   game suffix.  Without it, `resolve_game` can't split the
   concatenated team string, so the SPREAD/TOTAL tickers — which
   *do* have the correct FEB25 date — are also skipped.

3. **Zero Kalshi rows**: No canonical rows for this game get a
   `kalshi_ticker`.

4. **Optic verification reports two warnings**: Optic's odds carry
   source_ids pointing to both the old GAME ticker (date mismatch)
   and the new SPREAD tickers (no moneyline market).  Both warnings
   trace back to the same root cause.

### No structured signal in Kalshi data

We checked all date fields on Kalshi market objects:

- `expected_expiration_time`: Not updated for rescheduled games.
  It still reflects the original date.  (The 91 cases where it
  disagrees with the ticker date are all late-night West Coast
  games crossing midnight ET — unrelated.)
- `close_time`: Always `expected_expiration_time + 13d21h`
  (a safety backstop).  Not useful.
- `created_time`, `open_time`: When the market was listed.
  Not useful.
- `rules_primary`: Free text mentioning "originally scheduled
  for ..." — not structured, not parseable.

There is nothing in the Kalshi data that tells us the actual
rescheduled date.  Only Optic's fixture has the correct date.

### Cases observed

NCAAB 2026-02-25:

| Game        | GAME ticker date | Fixture date | Gap     |
|-------------|------------------|--------------|---------|
| MORG@SCST   | FEB14            | FEB25        | 11 days |
| WAKE@BC     | FEB24            | FEB25        | 1 day   |
| XAV@PROV    | FEB24            | FEB25        | 1 day   |

For WAKE@BC all market types (GAME, SPREAD, TOTAL, etc.) retained
the original FEB24 date — Kalshi never created fresh tickers at all.
For MORG@SCST only the GAME ticker kept the old date.

---

## 2. Missing GAME market (never listed by Kalshi)

Discovered 2026-03-09 while investigating the reconcile warning
on NCAAB 2026-03-08:

    reconcile: 55120-10632-2026-03-08: Kalshi source_id
      'KXNCAAMBSPREAD-26MAR08QUCCARK-CARK6' but no match
      — no moneyline market — game group skipped

### The root cause: staggered market listing

Kalshi does not list all market types for a game at the same time.
Per Nick: moneyline (GAME) is typically listed first, a few days
before game time, followed by SPREAD, TOTAL, and exotic markets
closer to tip-off.

However, for lower-profile games Kalshi sometimes lists SPREAD and
TOTAL markets **without ever creating a GAME market**.  The GAME
ticker simply does not exist — not under a different date, not
under a different abbreviation.  It was never listed.

### How we verified

Searched all three snapshots of `kalshi_markets.jsonl` for
2026-03-08 (01_13, 07_59, 19_11).  We searched for each team
abbreviation independently — QUC, CARK, UND, NDSU — across all
NCAAB GAME tickers (not just the concatenated pair).

The broader search found GAME tickers for these teams in the
01_13 snapshot, but for **different games on Mar 7**:

    KXNCAAMBGAME-26MAR07QUCPEAY   ← QUC vs Austin Peay (Mar 7)
    KXNCAAMBGAME-26MAR07UNDUST    ← UND vs St. Thomas (Mar 7)
    KXNCAAMBGAME-26MAR07NEOMNDSU  ← Omaha vs NDSU (Mar 7)

These are gone by the 07_59 snapshot (settled).  No GAME ticker
for the Mar 8 QUC@CARK or UND@NDSU matchups exists in any
snapshot.  Also enumerated every NCAAB GAME event ticker in the
19_11 snapshot — neither game appears.

The pattern is clear from the full ticker inventory for that date:

- **Mar 8 games with full market coverage** (28 of 30 matched):
  GAME + SPREAD + TOTAL + first-half markets
- **Mar 8 games missing GAME** (2 games):
  SPREAD + TOTAL only — no GAME ticker in any snapshot
- **Mar 9–10 games** (early listings, 15 games):
  GAME only — SPREAD/TOTAL not yet created

This confirms the staggered listing pattern.  The two missing-GAME
games are the odd ones out: they got exotic markets but Kalshi
never created the moneyline.

### Cases observed

NCAAB 2026-03-08 (data from 19_11 snapshot):

| Game        | Market types present       | GAME ticker |
|-------------|----------------------------|-------------|
| QUC@CARK    | SPREAD, TOTAL              | absent      |
| UND@NDSU    | SPREAD, TOTAL              | absent      |

For contrast, upcoming games listed the same day had GAME only:

| Game          | Market types present | Days until game |
|---------------|----------------------|-----------------|
| ALCN@ALST     | GAME                 | 1               |
| PITT@STAN     | GAME                 | 2               |
| (13 others)   | GAME                 | 1–2             |

---

## Fix for rescheduled games: suffix remap + auto-remap

Verified 2026-03-09 at Nick's request; auto-remap added 2026-07-29.

`kalshi_rescheduled.toml` maps old game suffixes to correct dates
(e.g. `"26FEB14MORGSCST" = "2026-02-25"`).  The pipeline uses
this in three steps:

1. **Rewrite the suffix before grouping.**  `suffix_remap` rewrites
   `26FEB14MORGSCST` → `26FEB25MORGSCST`, so the old-date GAME
   ticker and the new-date SPREAD/TOTAL tickers all land in the
   same `kalshi_groups` entry.

2. **Disambiguate teams as normal.**  `_disambiguate_teams` is
   date-agnostic — it finds GAME-type markets regardless of their
   ticker date.  Markets from different dates may coexist in the
   group; the function only cares about market suffixes.

3. **Override the extracted date.**  `resolve_game` returns the
   ticker date (FEB14); the pipeline replaces it with the fixture
   date (FEB25) from `date_override`.  The MatchKey lookup and
   all canonical rows use the corrected date.

**Auto-remap (no TOML):** when the ticker date is missing from the
Optic index but the same `(home, away)` has exactly one **unclaimed**
forward fixture within 7 days (not already matched by another Kalshi
ticker, not a same-day doubleheader), the pipeline remaps
automatically and logs `auto-reschedule`.  TOML always wins when
present.  Ambiguous cases still print the TOML suggestion for manual
verification.

The target date must also be one this run's Kalshi data covers.  Kalshi
lists a slate only a few days out (see problem 2), so a fixture on a date
with no Kalshi tickers at all is simply not listed yet, not a makeup game.
Without that guard, a real makeup date sitting beyond the Optic fixture
horizon would let an earlier legitimate meeting between the same teams
absorb the postponed ticker — and a later tick would then merge that
game's own ticker onto the same entry.

**Limitation:** resumed game + regular game on the same new date is a
same-day doubleheader — Kalshi tickers have no tip-off time, so both
auto-remap and TOML hit the existing doubleheader skip.

See also `docs/mmkalshi-greg-first-reschedule.md` for the RFQ-side
follow-up (Greg-first start-time guard).

---

## Remaining gap: missing GAME market (problem 2)

The suffix remap does not help when Kalshi never creates a GAME
ticker at all.  The remap brings old-date and new-date tickers
into the same group, but `_disambiguate_teams` still needs at
least two GAME-type markets to split the concatenated team string.
When no GAME market exists, there are zero GAME-type suffixes and
the function returns None — the entire game group is skipped.

The alternative approaches in `kalshi-abbrevs-notes.md` apply
here — particularly approach 5 (title-based game identification),
which parses team names from the `title` field and needs no GAME
market at all.  A lighter-weight option specific to this problem:
derive the team split from SPREAD suffixes, which end in a bare
team abbreviation plus a numeric line (e.g. `-CARK6`, `-QUC3`).
Stripping trailing digits would recover the team codes without
needing GAME markets (see approach 7 in `kalshi-abbrevs-notes.md`).
