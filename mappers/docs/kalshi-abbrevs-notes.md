# Kalshi Variable-Length Team Codes: Investigation Notes

These notes document the data investigations that led to the chosen
approach in `multi-sport-draft-refactor.md`.  They are retained as
reference — the decision is recorded there, not here.

**Map/ignore (2026-09+):** Python `*_kalshi.py` factories ship empty
`ignored_ticker_types`.  Non-game types listed below are observed on
Kalshi; live map/ignore is `mapping_market_rules` on the BQ tip.


## The problem

NBA Kalshi event tickers encode both team abbreviations as
adjacent uppercase strings with no delimiter:

    KXNBAGAME-26FEB26DETOTT
                      ^^^^^^
                      DET + OTT (3 + 3, always)

The NBA regex `([A-Z]{3})([A-Z]{3})` works because all 30 NBA
abbreviations are exactly 3 characters.

NCAAB and NHL have variable-length team codes.  The same
concatenation becomes ambiguous:

    KXNCAAMBGAME-26FEB21ILSTCLEM
                         ^^^^^^^^
                         ILS + TCLEM?  ILST + CLEM?  IL + STCLEM?

    KXNHLGAME-26FEB26EDMLA
                      ^^^^^
                      EDM + LA?  ED + MLA?  EDML + A?

    KXNHLGAME-26FEB25VGKLA
                      ^^^^^
                      VGK + LA?  VG + KLA?

For NHL, a human can resolve these (EDM and VGK are well-known),
but a regex cannot without knowing the valid team codes.


## Why it matters for architecture

Today `try_parse_game_ticker` is a pure function — it takes an
event_ticker string and returns (date, away, home) or None.  It
needs no external context.  If variable-length codes require
disambiguation, the function needs access to either:

- A known team set for the league (which NCAAB deliberately
  dropped — ~350+ teams, ad-hoc abbreviations), or
- The Optic fixture schedule (try all split points, check which
  produces a valid MatchKey).

The second approach changes the dependency flow: Kalshi parsing
would need the schedule index, which today it doesn't receive
until the matching phase.


## Data investigation: what each exchange calls a team

All three exchanges identify teams differently.  The table below
shows what we found in real data (NBA and NCAAB samples).

### NBA example: San Antonio / Toronto

| Exchange | Abbreviation | Full name |
|----------|-------------|-----------|
| Optic    | `SAS`       | `San Antonio Spurs` |
| PX       | `SA`        | `San Antonio Spurs` |
| Kalshi   | `SAS` (ticker) | `San Antonio` (title) |

For NBA, PX and Optic agree on full names but differ on 5
abbreviations (GS/GSW, NY/NYK, NO/NOP, PHO/PHX, SA/SAS).
Kalshi tickers use the Optic abbreviation.  Kalshi titles use
city names only (no mascot).

### NCAAB example: several teams

| Optic abbr | Optic name | PX abbr | PX name | Kalshi title |
|-----------|------------|---------|---------|--------------|
| `ARMY`    | `Army`     | `ARMY`  | `Army Black Knights` | `Army` |
| `SCST`    | `South Carolina State` | `SCARST` | `South Carolina State Bulldogs` | ? |
| `IUPU`    | `IUPUI`    | `IUIND` | `IU Indy Jaguars` | ? |
| `WAKE`    | `Wake Forest` | `WAKE` | `Wake Forest Demon Deacons` | ? |
| `BC`      | `Boston College` | `BC` | `Boston College Eagles` | ? |
| `FUR`     | `Furman`   | `FURMAN` | `Furman Paladins` | ? |

NCAAB names disagree across all three dimensions:
- **Abbreviations** differ (SCST/SCARST, IUPU/IUIND, FUR/FURMAN)
- **Full names** differ: PX appends mascots (`Army Black Knights`
  vs Optic's `Army`); PX renamed IUPUI → `IU Indy Jaguars`
- **Kalshi titles** use informal short names (`Iowa St.`,
  `Wichita St.`, `Arkansas St.`, `BYU`)

**Conclusion:** Switching from abbreviations to full names as the
canonical key does NOT reduce the aliasing burden — you just shift
which strings disagree.  We keep Optic abbreviations as canonical.

### NHL

| Optic abbr | Kalshi title |
|-----------|-------------|
| `EDM`     | `Edmonton` |
| `ANA`     | `Anaheim` |
| `BOS`     | `Boston` |
| `PHI`     | `Philadelphia` |
| `VGK`     | `Vegas` |

NHL Kalshi titles use city names.  NHL has ~32 teams, manageable
for any alias table approach.

### Soccer (EPL / Bundesliga / La Liga / etc.)

| League | Kalshi prefix | Example ticker suffix | Example title |
|--------|-------------|---------------------|--------------|
| EPL    | `KXEPL`     | `TOTCRY` | `Tottenham vs Crystal Palace Winner?` |
| Bundesliga | `KXBUNDESLIGA` | `BVBBMU` | `Dortmund vs Bayern Munich Winner?` |
| La Liga | `KXLALIGA` | `OVIATM` | `Oviedo vs Atletico Winner?` |
| Ligue 1 | `KXLIGUE1` | `HACPSG` | `Le Havre vs PSG Winner?` |
| Serie A | `KXSERIEA` | `INTGEN` | `Inter vs Genoa Winner?` |
| MLS    | `KXMLS`     | `MINCIN` | `Minnesota vs Cincinnati Winner?` |

Soccer ticker suffixes are variable-length concatenated codes,
same ambiguity problem as NHL/NCAAB.  Soccer Kalshi titles use
club short names.


## Kalshi ticker types observed per league

From examining real data files.  These are the `{TYPE}` portion
extracted from `KX{LEAGUE}{TYPE}-...` event tickers.

**NBA** (prefix `KXNBA`): `GAME`, `SPREAD`, `TOTAL`, `TEAMTOTAL`,
`1HSPREAD`, `1HTOTAL`, `1HWINNER`, `2HWINNER`, `PTS`, `AST`,
`REB`, `3PT`, `BLK`, `STL`, `2D`, `3D`.

**NCAAB** (prefix `KXNCAAMB`): `GAME`, `SPREAD`, `TOTAL`,
`1HSPREAD`, `1HTOTAL`, `1HWINNER`.  No player props, no
TEAMTOTAL, no 2HWINNER.  Also posts non-game types (tip `ignore`):
`NAISMITH`, `UNDEFEATED`.

**NHL** (prefix `KXNHL`): `GAME`, `SPREAD`, `TOTAL`, `PTS`,
`AST`, `GOAL`, `FIRSTGOAL`.  No TEAMTOTAL, no half markets.
`GOAL` and `FIRSTGOAL` are NHL-specific (no NBA equivalent).
Also has many non-game types: `HART`, `NORRIS`, `CALDER`,
`VEZINA`, `ROSS`, `RICHARD`, `ADAMS`, `PRES`, `PLAYOFF`,
`ATLANTIC`, `METROPOLITAN`, `CENTRAL`, `PACIFIC`, `EAST`, `WEST`.

**Soccer** (prefixes `KXEPL`, `KXBUNDESLIGA`, `KXLALIGA`,
`KXLIGUE1`, `KXSERIEA`, `KXMLS`): `GAME`, `SPREAD`, `TOTAL`,
`BTTS`, `FIRSTGOAL`, `GOAL`.  Soccer `GAME` is 3-way (TIE
outcome exists).  `BTTS` (both teams to score) is soccer-specific.
Also has non-game types: `RELEGATION`, `TOP2`, `TOP4`, `TOP6`,
and league winner markets (bare prefix with no type).

Note: NHL `GAME` appears to be 2-way (no TIE suffix observed in
data), unlike soccer `GAME` which is 3-way.  NHL `yes_sub_title`
uses a different format from other leagues: `"PHI Flyers"` rather
than just `"Philadelphia"` or `"PHI"`.


## Kalshi fields available for game identification

The Kalshi Market object has 14 fields.  The current code uses
only 3 (`event_ticker`, `ticker`, `title`).  Key unused fields:

| Field | Content | Useful? |
|-------|---------|---------|
| `subtitle` | Always empty in all samples | No |
| `yes_sub_title` | Human-readable outcome (`"Milwaukee"`, `"Over 99.5 points scored"`) | Maybe |
| `rules_primary` | Full settlement rules with explicit game identification | Yes |
| `rules_secondary` | Extended rules (cancellation, overtime, etc.) | No |
| `expected_expiration_time` | Game end estimate — gives date | Backup |

### The `title` field is highly structured

Title patterns are **consistent across all leagues** (NBA, NCAAB,
NHL, EPL, Bundesliga, La Liga, Ligue 1, Serie A, MLS):

| Shape | Title pattern | Both teams? |
|-------|--------------|-------------|
| GAME (moneyline) | `{Away} at {Home} Winner?` | Yes |
| TOTAL | `{Away} at {Home}: Total Points` | Yes |
| BTTS | `{Away} at {Home}: Both Teams to Score` | Yes |
| 1HTOTAL | `{Away} vs {Home}: First Half Total?` | Yes |
| 1HWINNER/2HWINNER | `{Away} vs {Home}: {Half} Winner?` | Yes |
| SPREAD | `{Team} wins by over N.N ...?` | One team |
| TEAMTOTAL | `Will {Team} score over N.N points?` | One team |
| 1HSPREAD | `Will {Team} win the 1H by over N.N ...?` | One team |
| Player stats | `{Player}: {N}+ {stat}` | Neither |
| DD/TD | `{Player}: Double Double` | Neither |

The separator between teams is `"at"` (GAME, TOTAL, BTTS) or
`"vs"` (half markets, soccer GAME).  The team names used are
the exchange's informal display names (city for NBA/NHL,
school for NCAAB, club short name for soccer).

### The `rules_primary` field always names both teams

Every game-scoped market's `rules_primary` contains a phrase
like:

    "in the Cleveland vs Milwaukee professional basketball game
     originally scheduled for Feb 25, 2026"

    "in the Cleveland at Milwaukee professional basketball game
     originally scheduled for Feb 25, 2026"

This is the richest field but also the most fragile to parse
(natural language, sport-specific phrasing).


## Approaches considered

All approaches still need an alias table to map exchange-specific
team identifiers to canonical (Optic) abbreviations.  The question
is *which* identifier they parse from Kalshi and *what context*
the parser needs.

1. **League-provided team set (split-point disambiguation).**
   The league config provides the set of valid Kalshi ticker
   abbreviations.  `try_parse_game_ticker` tries all split points
   on the concatenated team string and picks the split where both
   halves are in the set.  Works for NHL (~32 teams) and NBA
   (~30).  For NCAAB, 357 unique Kalshi ticker codes were found
   across two dates (see data investigation below).  The set is a
   flat `frozenset[str]`; a separate Kalshi-abbrev→Optic-abbrev
   alias table handles the ~72 codes that differ from Optic.

2. **Schedule-assisted disambiguation.** Pass the set of known
   (date, away, home) triples to the Kalshi parser.  For each
   ticker, extract the date, then try all split points on the
   team string, checking each against the schedule.  Downside:
   couples parsing to the schedule.

3. **Title-based game identification.** Don't parse teams from
   the ticker at all.  Extract the market type and date from the
   ticker (both unambiguous), then identify the game from the
   `title` field.  Group all markets sharing the same event_ticker
   suffix (opaque, not parsed).  For each group, find a market
   whose title names both teams (GAME or TOTAL — every game has
   at least one), parse the two team names using the `"at"` /
   `"vs"` separator, and map them to canonical abbreviations via
   the alias table.  Markets whose titles name only one team or
   neither inherit the game identity from their group.

4. **League-specific regex.** NCAAB might have a discoverable
   pattern (e.g. codes are always 2-4 chars, or the Kalshi ticker
   uses a different delimiter for NCAAB).  Needs more data
   examination.

5. **Optic-first matching with title-assisted Kalshi resolution.**
   Load Optic fixtures first (canonical), match PX to Optic (by
   abbreviation with PX alias table), then match Kalshi to the
   day's Optic fixture set using team names parsed from Kalshi
   GAME-type titles.  The ticker suffix is never split — the
   canonical (away, home) comes from the matched Optic fixture.
   A small Kalshi display-name→Optic-name alias table handles
   naming discrepancies.  See detailed investigation below.

6. **GAME-market suffix disambiguation (chosen).**  See
   `multi-sport-draft-refactor.md` for the full description
   and rationale.

7. **SPREAD-suffix fallback.**  When no GAME market exists,
   derive team codes from SPREAD market suffixes instead.  SPREAD
   suffixes end in a bare team abbreviation plus a numeric line
   (e.g. `-CARK6`, `-QUC3`).  Stripping trailing digits recovers
   the team code.  This is a minimal extension of approach 6 —
   same disambiguation algorithm, different suffix source.  Risk:
   team codes containing digits (e.g. M05 for Mainz 05) would
   need special handling, since naive digit-stripping turns `M052`
   into `M` rather than `M05`.

These approaches are not mutually exclusive.  The refactored
architecture could support per-league strategy selection.


## Data investigation: Kalshi ticker codes vs Optic abbreviations

**Data examined:** `data/ncaab/2026-02-{21,25}/kalshi_markets.jsonl`
and `data/ncaab/2026-02-{21,25}/optic_fixtures_odds.jsonl`.

Kalshi GAME-type market tickers (e.g.
`KXNCAAMBGAME-26FEB23HOUKU-KU`) have the individual team code
as the market ticker suffix.  Extracting these from two dates of
data gave **357 unique Kalshi NCAAB team codes**.  Extracting
competitor abbreviations from Optic fixtures on the same two
dates gave **343 unique Optic abbreviations**.

**285 codes appear in both sets** (string-identical).  However,
this only proves the strings match — not that they refer to the
same team in every case.  A team-by-team verification has NOT
been done.

**72 Kalshi codes have no match in the Optic set**, and **58
Optic abbreviations have no match in the Kalshi set**.  Some of
these are the same teams with different abbreviations:

| Team | Kalshi code | Optic abbr |
|------|-------------|------------|
| Abilene Christian | `AC` | `ACU` |
| Charlotte | `CHAR` | `CLT` |
| Detroit Mercy | `DET` | `DETM` |
| IU Indy | `IUIN` | `IUPU` |
| Grambling | `GRAM` | `GRAM` (but "Grambling St." in Kalshi titles vs "Grambling" in Optic) |
| Grand Canyon | `GC` | `GCU` |
| Loyola Chicago | `LCHI` | `LUC` |
| Penn | `PENN` | — (Optic uses `PENN` too, but for "Pennsylvania") |

Others may be teams that only appeared in one exchange's data on
those dates.  The two dates sampled don't cover every D1 team.


## Data investigation: approach 5 (Optic-first title matching)

**Data examined:** `data/ncaab/2026-02-21/` — all three exchange
files for the same date.

On 2026-02-21 there are 169 Optic fixtures, 148 PX events, and
178 unique Kalshi games (by event_ticker).

### Kalshi GAME-type title format

Every GAME-type market uses the title format:

    {Away} at {Home} Winner?

Parsing on `" at "` reliably extracts both team display names.
**Verified** on all 178 GAME tickers for 2026-02-21.

The names are Kalshi's informal display names — city names for
NBA/NHL, school names for NCAAB (often abbreviated: "Iowa St.",
"Wichita St.", "UConn").

### Automatic matching results

Matching Kalshi title names against Optic fixture team names
(case-insensitive, with normalization of "St." → "State" and
stripping of apostrophes/hyphens):

    GAME tickers:                    178
    Auto-matched (with normalize):   159  (89%)
    Still need alias:                 19

The 19 unmatched Kalshi display names (from 2026-02-21):

    "American"               Optic: "American University"
    "Central Connecticut St."  Optic: "Central Connecticut" (no "State")
    "East Texas A&M"         Optic: (not in 2026-02-21 data)
    "FDU"                    Optic: (not found, maybe "Fairleigh Dickinson")
    "Grambling St."          Optic: "Grambling" (no "State")
    "LIU"                    Optic: "Long Island University"
    "Louisiana-Monroe"       Optic: "Louisiana Monroe" (hyphen vs space)
    "Miami (FL)"             Optic: "Miami Florida"
    "Nicholls St."           Optic: "Nicholls" (no "State")
    "Penn"                   Optic: "Pennsylvania"
    "Sam Houston"            Optic: "Sam Houston State"
    "Seattle"                Optic: "Seattle U"
    "Southern Miss"          Optic: "Southern Mississippi"
    "Southern University"    Optic: "Southern" or similar
    "St. Thomas"             Optic: "St. Thomas" (normalizes to "State Thomas")
    "UConn"                  Optic: "Connecticut"
    "UMass"                  Optic: "Massachusetts" or "UMass Lowell"
    "USC Upstate"            Optic: "USC Upstate" or different
    "University"             Parse artifact from "at Southern University"

These fall into clear categories:
- **"St." normalization over-applied:** "St. Thomas" should NOT
  become "State Thomas" (St. Thomas is the school's actual name).
  Smarter normalization: only expand "St." when followed by a
  space and another word (i.e. "Iowa St." → "Iowa State" but
  "St. Thomas" stays).  Similarly "Grambling St." → "Grambling
  State" but Optic just has "Grambling" — reverse problem.
- **Nicknames/initialisms:** UConn, UMass, FDU, LIU, Penn — a
  small fixed set of well-known college abbreviations.
- **Suffix variations:** "American" vs "American University",
  "Seattle" vs "Seattle U", "Sam Houston" vs "Sam Houston State".
- **Formatting:** "Miami (FL)" vs "Miami Florida",
  "Louisiana-Monroe" vs "Louisiana Monroe".

A Kalshi display-name→Optic-name alias table of ~30-40 entries
would cover all NCAAB exceptions.  This is much smaller than the
357-entry team code set needed for approach 1.

### How approach 5's matching algorithm would work

```
for each date's data:
  1. Load Optic fixtures → game_index keyed by (date, home, away)
     Also build name_index: normalized_optic_name → abbr

  2. Load PX events → match to Optic by abbreviation
     (with PX abbr alias table, already planned)

  3. Load Kalshi markets, grouped by event_ticker:
     a. Extract market type from ticker prefix (unambiguous)
     b. Extract date from ticker suffix (YYMMMDD, unambiguous)
     c. Find any GAME-type market in the group
     d. Parse title: "{Away} at {Home} Winner?"
     e. Normalize both names, apply display-name aliases
     f. Look up both names in name_index → canonical abbrs
     g. Look up (date, home_abbr, away_abbr) in game_index
     h. All markets in the group inherit this game identity
```

### Advantages of approach 5 over approach 1

- No 357-entry team code frozenset to maintain.
- No Kalshi-code→Optic-abbrev mapping needed (the 72-entry
  alias table from approach 1 is replaced by the ~30-40-entry
  display-name alias table).
- Display names are human-readable and self-documenting
  (`"UConn" → "Connecticut"` is obvious; `"DET" → "DETM"` is
  not).

### Open questions and risks (approach 5)

These have NOT been verified — they are work to be done.

1. **Does every Kalshi game have a GAME-type market?**  **No.**
   Originally verified as "yes, for all same-day games" across
   early data (NBA 4 dates, 76 games; NCAAB 2 dates, 310 games;
   NHL 1 date, 18 same-day games; soccer 1 date, 111 games).
   However, on NCAAB 2026-03-08 two games (QUC@CARK, UND@NDSU)
   had SPREAD and TOTAL markets but no GAME market in any snapshot.
   See `kalshi-missing-game-tickers.md` §2 for details.

   Two apparent exceptions on investigation are not real problems:

   - **NHL stale player props.**  The NHL 2026-02-26 file contains
     5 previous-day (FEB25) games with only player prop markets
     (AST, GOAL, FIRSTGOAL, PTS) — game-level markets (GAME,
     SPREAD, TOTAL) had already closed.  These are games that
     already finished; the pipeline wouldn't merge them anyway.
     Their `rules_primary` still names both teams
     (`"in the EDM Oilers at ANA Ducks professional hockey game
     ..."`), providing a fallback if ever needed.

   - **La Liga Segunda División.**  10 La Liga 2 games use ticker
     type `2GAME` instead of `GAME`.  Their titles use the same
     `"{Away} vs {Home} Winner?"` format — title parsing works
     identically.  The code just needs to recognize `2GAME` as
     a GAME-equivalent type when searching for game identity.

2. **Title format stability.**  Titles are human-facing strings.
   Kalshi could change `"at"` to `"vs"` or rephrase `"Winner?"`
   without notice.  Ticker format is arguably more stable (API
   identifier).  But the title patterns have been observed to be
   consistent across NBA, NCAAB, NHL, and 6 soccer leagues, so
   they appear to be generated from a template.

3. **Same-day name collisions.**  Could "Miami" appear twice on
   one day (Miami FL and Miami OH)?  Kalshi disambiguates with
   `"Miami (FL)"` and `"Miami (OH)"` in titles.  But the
   normalizer needs to handle this correctly.  **Not yet tested**
   on a day where both Miami teams play.

4. **Cross-exchange coverage mismatch.**  Some Kalshi games may
   not have Optic fixtures (different coverage).  These can't be
   merged and should be skipped with a warning, but the matching
   code must handle the "no Optic match" case gracefully.

5. **The PX-to-Optic match is a prerequisite.**  Approach 5
   assumes PX→Optic matching works.  **Measured:** the PX→Optic
   abbreviation alias table is ~200+ entries for NCAAB (compared
   to 5 for NBA).

   Across two dates of NCAAB data (2026-02-21 and 2026-02-25),
   323 unique PX abbreviations were observed.  Only 111 (34%)
   match an Optic abbreviation exactly.  The remaining 212 need
   explicit alias mappings.  PX tends toward longer abbreviations
   (`BUTLER`, `OREGON`, `CREIGH`); Optic toward shorter ones
   (`BUT`, `ORE`, `CREI`).

   This doesn't change the architecture — the TOML alias table
   design handles any size — but it means bootstrapping the NCAAB
   alias table is a significant upfront task.  An offline
   discovery tool that matches PX events to Optic fixtures by
   date and game pairing, auto-suggests aliases where names
   overlap, and flags the rest for manual resolution would help.
   The table will also grow as new dates surface teams not yet
   seen (D1 has ~360 teams; only ~320 appeared across these two
   sample dates).

6. **"St." normalization is tricky.**  "Iowa St." should become
   "Iowa State", but "St. Thomas" should stay "St. Thomas" (or
   become "Saint Thomas").  "St. John's" is another case.  The
   normalizer needs context-aware rules or the alias table handles
   these as exceptions.

7. **The display-name alias table needs bootstrapping.**  The
   ~30-40 entries were estimated from one date of data.  Other
   dates may surface additional exceptions.  An offline discovery
   tool that attempts matching and reports failures would help
   build the table incrementally.

8. **Two-pass grouping.**  Markets must be grouped by event_ticker
   before processing (to find a GAME-type title for each game).
   The current NBA code processes markets in a single pass.  This
   is a minor architectural change, not a fundamental problem.

### Separate topic: Kalshi/Optic title overlap

Kalshi GAME-type titles use team display names (`"Charlotte"`,
`"East Carolina"`) that often match Optic team names exactly.
This is an interesting property that could simplify matching if
we ever revisited a title-based approach, but it is not part of
the chosen ticker-suffix method.  To be investigated separately.
