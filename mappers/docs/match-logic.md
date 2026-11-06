# Match Logic

## Why flipping PX home / away is safe

In short: we match PX market selections to canonical betting sides
using the team abbreviation from the PX event, which we reach via
`competitor_id` on the selection — not via home/away position.  That
abbreviation is already alias-resolved to canonical form at the point
of creation (`build_comp_map`), so the flip is invisible downstream.

PX sometimes labels home and away opposite to Optic's schedule.
For example, on 2026-02-21 NCAAB:

| Source | Home | Away |
|--------|------|------|
| Optic  | DUKE | MICH |
| PX     | MICH | DUKE |
| Kalshi | DUKE | MICH |

When the pipeline detects a flip it reassigns the PX event to the
correct Optic fixture (`pipeline.py:438-441`).  This is safe because
PX's home/away labeling is only used once — during schedule matching —
and never reaches the canonical output rows.  Two independent data
paths ensure correctness:

**1. Row-level home/away comes from Optic, not PX.**

The row builder reads `home` and `away` from the Optic fixture
(`pipeline.py:583-584`), which is the schedule authority.  The PX
event's home/away fields are not consulted.

**2. Side (which team a bet is on) is resolved by competitor ID,
not by position.**

Each PX selection carries a numeric `competitor_id`.  Side resolution
looks this up in a map built from the event's competitor list:

```
PX event competitors:
  id=60000095  abbr=MICH  side=home
  id=60000026  abbr=DUKE  side=away

comp_map (built once, with alias resolution):
  {60000095: "MICH", 60000026: "DUKE"}

PX moneyline selection:
  competitor_id=60000026  →  comp_map[60000026]  →  side="DUKE"
```

The `side` field in the competitor list ("home"/"away") is consumed
only by `_sides()` (`px.py:123-141`) to build the initial match key.
`build_comp_map()` (`px.py:524-533`) ignores it — it maps `c.id` to
`c.abbreviation`, full stop.  `resolve_side_label()` (`px.py:536-557`)
then maps each selection's `competitor_id` through that table.

The resulting canonical row therefore gets:

- `home`, `away` — from Optic fixture (positional, authoritative)
- `side` — from PX competitor ID chain (identity-based, flip-invariant)

These are fully independent paths.  Swapping which competitor PX
considers "home" vs "away" changes the match key (fixed by the flip
recovery) but cannot change which team a bet resolves to.


## Kalshi ticker away / home ordering

Kalshi event tickers concatenate both team codes with no delimiter:

    KXNCAAMBGAME-26FEB21MICHDUKE

The ordering is **per-league config** (`KalshiConfig.ticker_home_first`):

- **US sports are away-first** — `MICHDUKE` splits as away=`MICH`,
  home=`DUKE`.
- **Soccer is home-first** — `KXEPLGAME-26MAY17AVLLFC` is Aston
  Villa home, and `KXWCGAME-26JUN11MEXRSA` is Mexico home.  The
  World Cup ordering was confirmed 68/68 games via the Optic
  source_ids join (2026-06-07 sweep,
  `scripts/sweep_world_cup_aliases.py`); before the flag existed,
  every matched soccer game mapped only via the flip recovery
  below, warning each time.

For NCAAB (variable-length codes) we can't split on position alone;
instead `_disambiguate_teams()` uses GAME-type market suffixes to
find the cut point and returns the codes in ticker order;
`resolve_game` applies the config flag.  For NBA the regex captures
fixed-width groups directly (`leagues/nba.py:62-64`).

**Verification:** the away-first convention was checked across 499
GAME events in 10 leagues (see `multi-sport-draft-refactor.md` step
0b) — but that check keyed on the suffix partitioning, and soccer's
home-first ordering was only caught later by the flip-recovery
warnings.  The pipeline warns and auto-recovers on any Kalshi flip
(`pipeline.py`, kalshi matching pass), so an ordering violation
surfaces as a per-game warning rather than silent wrong output.

**The ordering assumption is used at both levels** — event-level
schedule matching (`pipeline.py:510-512`) and market-level suffix
parsing (`_require_team`, `_parse_team_line`), which need to know
the two raw codes for the game.  However, **side resolution itself
is identity-based** and does not depend on which code is home vs
away:
each raw ticker code is resolved through the alias table
(`resolve_team` in `build_rows`), which maps `CHAR` → `CLT`
regardless of whether `CHAR` appeared in the home or away slot.
This is the same principle that makes PX flips safe (PX uses
`competitor_id` instead of an alias table, but the effect is
the same — identity-based, position-independent).

A Kalshi flip would therefore not cross-wire side resolution.
The pipeline warns and auto-recovers on a Kalshi flip (attaching
to the flipped `MatchKey` and swapping the raw codes), so the
failure mode is a per-game warning, not silent wrong output.


## Team matching

Team matching is alias resolution followed by exact lookup.

Optic abbreviations are canonical.  Each exchange abbreviation is
looked up in `config/{league}/team_aliases.toml`; if found, it is
replaced with the canonical form.  If not found, the abbreviation
is assumed to already be canonical (identity pass-through).

The resolved abbreviations are used to build a `MatchKey(date, home,
away)`, which is then looked up in the Optic schedule.  If the lookup
fails:

- **PX: the pipeline raises.**  PX events carry structured
  competitor objects (`abbreviation`, `name`, `id`, `side`), so
  `parse_event` always produces a valid MatchKey — team resolution
  cannot partially fail.  If that key doesn't match the schedule on
  a date with fixtures, the only explanation is a missing alias in
  `team_aliases.toml`, and we want that to be loud.

- **Kalshi: the pipeline warns on stderr and skips the game.**
  Kalshi team resolution has a known partial-failure mode:
  variable-width leagues (NCAAB) require `_disambiguate_teams` to
  split a concatenated team string using GAME-type market suffixes,
  and this returns `None` when fewer than 2 GAME markets exist for
  the group (e.g. Kalshi publishes spread/total before moneyline).
  `resolve_game` passes that `None` through, so the pipeline
  already skips before reaching MatchKey lookup.  Even when
  `resolve_game` succeeds, the shorter Kalshi codes parsed from
  ticker strings lack the independent verification signals PX has,
  so a schedule miss is sometimes structural rather than erroneous.
  Raising here would crash the pipeline on data that is expected to
  be incomplete.

In both cases the fix for a genuine alias gap is to add an entry to
`team_aliases.toml`.

Unlike player orphans, there is no Levenshtein diagnostic for teams.
Team codes are short abbreviations with a small universe, so
mismatches surface immediately as raised errors or skipped-game
warnings on stderr.

### Away/home flip detection

Before raising or skipping, the pipeline checks whether the exchange
and Optic simply disagree on which team is home.  PX flips are
auto-recovered — this is safe because side resolution is
identity-based (see above).  Kalshi flips raise immediately as a
data-quality signal.


## Player matching

Player matching is exact string equality — no fuzzy matching.

**1. Name normalization.**  All three sources run each player name
through `normalize_player_name()` (`shared.py:256`): NFD decompose,
strip diacritics, strip periods, strip generational suffixes (Jr,
Sr, II, III, IV), lowercase, collapse whitespace, replace spaces
with underscores.  E.g. `"Nikola Jokić"` → `"nikola_jokic"`,
`"Wendell Carter Jr."` → `"wendell_carter"`.

**2. Player alias lookup (PX and Kalshi only).**  After
normalization, exchange names are looked up in
`config/{league}/player_aliases.toml`.  If found, the exchange
name is replaced with the canonical (Optic) name.  Optic names
are never aliased — Optic is the authority.

**3. Row key merge.**  Each source builds `CanonicalRow` objects
keyed by `(date, home, away, market_type, entity, line, side,
grouping_key)`, where `entity` is the normalized + aliased player
name.  Rows are merged in order PX → Kalshi → Optic
(`pipeline.py:587-638`): if
a row with the same key already exists, stamp the new source's
fields onto it; otherwise append.  A match requires all eight
fields to agree exactly.

**Failure mode.**  When an exchange player doesn't match any Optic
player, the exchange row stays exchange-only — no `optic_id` is
stamped.  The result is a missed betting opportunity, not a wrong
match.  There are two distinct causes:

**Coverage gap.**  PX or Kalshi offers markets on a player that
Optic doesn't cover for that game.  No alias can fix this — the
player simply isn't in Optic's universe.  In the diagnostic table
these orphans typically have a high Levenshtein distance (6+) and
no surname neighbour in the Optic column.  No action needed.

**Name mismatch.**  The same real player appears under different
names on the exchange and Optic (e.g. PX says `gg_jackson`, Optic
says `gregory_jackson`).  These typically show a lower Levenshtein distance
(say 1–4) and often cluster by surname in the diagnostic.  The fix is
to add an alias to `config/{league}/player_aliases.toml`:

```toml
[gregory_jackson]          # canonical (Optic) normalized name
px = ["gg_jackson"]        # exchange normalized name(s)
```

To find candidates, run the pipeline and inspect the orphan roster
table.  The `--orphan-dist N` flag controls which games appear:
only games where at least one orphan has Levenshtein distance <= N
are shown (default 5).  Raise the threshold to audit coverage gaps
too:

```
python -m mappers.run nba data/nba/2026-02-19 --orphan-dist 8
```

The dangerous scenario — matching the wrong real player — can only
happen if someone adds an incorrect alias.  The diagnostic exists
to inform that decision, not to automate it.  When in doubt, leave
the orphan unaliased; the cost is a missed opportunity, not a
wrong match.
