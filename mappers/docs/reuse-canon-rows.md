# Canonical table: one row per side, both exchanges

How we integrate Kalshi into the existing PX canonical table.


## Background

The existing PX canonical table has one row per **side** — each row
is one betting position you can take.  Every bet has exactly two
complementary sides (one wins, the other loses).

The required output format (see `data/greg benchmark 1.txt`) is
also per-side: each output object carries one PX `line_id` and one
Kalshi `market_ticker` + `side` ("yes" or "no").

So the canonical table stays as one-row-per-side.  We add two
columns: `kalshi_ticker` and `kalshi_side`.


## How each market type works

### Moneyline

PX: one market, two selections (one per team), each with a line_id.
Kalshi: two separate tickers (one per team), each a yes/no contract.

Each Kalshi ticker maps 1:1 to one canonical row.  `kalshi_side`
is always "yes" (KXNBAGAME-...-SAC yes = "SAC wins").

```
date        market_type  side  px_line_id  kalshi_ticker               kalshi_side
2026-02-26  moneyline    SAC   dce8b4e...  KXNBAGAME-26FEB26SACDAL-SAC  yes
2026-02-26  moneyline    DAL   a1b2c3d...  KXNBAGAME-26FEB26SACDAL-DAL  yes
```

### Game total

PX: one market, N market_lines.  Each market_line has two selections
(over + under), each with a line_id.
Kalshi: one ticker per line (e.g. KXNBATOTAL-...-228), where
yes = "over 228.5", no = "under 228.5".

One Kalshi ticker maps to TWO canonical rows (the over and the
under).  `kalshi_side` is "yes" for over, "no" for under.

```
date        market_type  line   side   px_line_id  kalshi_ticker              kalshi_side
2026-02-26  game_total   228.5  over   fa00d1e...  KXNBATOTAL-26FEB26CHAIND-228  yes
2026-02-26  game_total   228.5  under  de7a708...  KXNBATOTAL-26FEB26CHAIND-228  no
```

### Team total

Same structure as game total, but with `entity` identifying the team.

PX: two markets per game (one per team), N lines each, two
selections per line (over + under).
Kalshi: one ticker per team per line (e.g. KXNBATEAMTOTAL-...-HOU108),
yes = "HOU scores over 108.5", no = "HOU scores under 108.5".

```
date        market_type  entity  line   side   px_line_id  kalshi_ticker                     kalshi_side
2026-02-26  team_total   HOU     108.5  over   abc123...   KXNBATEAMTOTAL-26FEB26HOUORL-HOU108  yes
2026-02-26  team_total   HOU     108.5  under  def456...   KXNBATEAMTOTAL-26FEB26HOUORL-HOU108  no
```

### Spread

The hard one.  PX and Kalshi model spreads differently.

**PX:** one spread market per game, N market_lines.  Each market_line
has two selections with **signed** lines:
- CHA at line=-12.5 (favored, must win by 12.5+)
- IND at line=+12.5 (underdog, gets 12.5 point cushion)

The sign encodes direction: negative = favored, positive = underdog.
These two are complementary sides of one bet.

**Kalshi:** two tickers per line value — one per team:
- KXNBASPREAD-...-CHA12: yes = "CHA wins by 12.5+"
- KXNBASPREAD-...-IND12: yes = "IND wins by 12.5+"

These are NOT two sides of the same bet.  They are two independent
contracts.  CHA12 asks "does CHA win by 12.5+?" and IND12 asks
"does IND win by 12.5?" — both can be false (if the margin is
under 12.5 for either team).

**Matching CHA12 to PX:**
- CHA12 yes ("CHA wins by 12.5+") ↔ PX CHA at -12.5 (CHA covers)
- CHA12 no ("CHA does NOT win by 12.5+") ↔ PX IND at +12.5 (IND covers)

Both PX rows at a given line map to the SAME Kalshi ticker (CHA12),
just different sides (yes/no).

**Matching IND12 to PX:**
IND12 asks "does IND win by 12.5+?"  PX would need a market_line
where IND is favored by 12.5 (IND has the negative line).  If IND
is actually the underdog, no such PX line exists.  IND12 rows have
`kalshi_ticker` populated but `px_line_id` empty.

**How to determine which Kalshi ticker matches a PX line:**
The PX selection with the **negative** line identifies the favored
team.  The Kalshi suffix team is the team being asked about.  Match
when they agree: PX CHA at -12.5 matches Kalshi CHA12 (not IND12).

**Canonical representation:**
Keep PX's signed lines as-is.  They're the standard sportsbook
convention and self-describing.

```
date        market_type  line    side  px_line_id  kalshi_ticker                    kalshi_side
2026-02-26  point_spread  -12.5   CHA   935797b...  KXNBASPREAD-26FEB26CHAIND-CHA12  yes
2026-02-26  point_spread  +12.5   IND   7be04a8...  KXNBASPREAD-26FEB26CHAIND-CHA12  no
2026-02-26  point_spread  -12.5   IND               KXNBASPREAD-26FEB26CHAIND-IND12  yes
2026-02-26  point_spread  +12.5   CHA               KXNBASPREAD-26FEB26CHAIND-IND12  no
```

The first two rows are one bet (CHA favored by 12.5), matched to
CHA12 yes/no.  The last two are a different bet (IND favored by
12.5), Kalshi-only.


## CanonicalRow model

```python
class CanonicalRow(BaseModel):
    date: str                         # YYYY-MM-DD (Eastern)
    home: str                         # home team abbrev
    away: str                         # away team abbrev
    market_type: str                  # MarketType.value
    entity: str | None = None         # team abbrev (team_total only)
    line: float | None = None         # signed for point_spread; threshold for totals; None for moneyline
    side: str                         # team abbrev (moneyline/point_spread); "over"/"under" (totals)
    px_line_id: str | None = None     # PX selection's line_id
    kalshi_ticker: str | None = None  # Kalshi market ticker
    kalshi_side: str | None = None    # "yes" or "no" on the Kalshi contract
```

Row key (for merging): `(date, home, away, market_type, entity, line, side)`.

A row may have only PX fields, only Kalshi fields, or both — depending
on whether that specific side at that specific line exists on each exchange.


## Implementation approach

### What exists (in stash "Kalshi ticker parsing WIP")

Already written and tested:
- `KalshiParsedTicker` model (Pydantic)
- `parse_kalshi_ticker(market, home, away)` → parsed ticker or None
- Helper functions for suffix parsing
- Constants for ticker types and table types

These parse a Kalshi market ticker and extract: `market_type`,
`team_abbr`, `line` (half-point converted).

### What needs to change after popping the stash

1. **CanonicalRow** — add `kalshi_side: str | None = None` field
   (the stash already adds `kalshi_ticker`).

2. **Rewrite `build_kalshi_rows()`** — currently emits one row per
   ticker (the "yes" interpretation only).  Must emit TWO rows for
   spread and totals (yes + no), matching the existing PX per-side
   structure.

   For each parsed Kalshi ticker:
   - Moneyline: 1 row (side=team, kalshi_side="yes")
   - Spread: 2 rows (side=team at -line kalshi_side="yes",
     side=opponent at +line kalshi_side="no")
   - Game total: 2 rows (side="over" kalshi_side="yes",
     side="under" kalshi_side="no")
   - Team total: 2 rows (side="over" kalshi_side="yes",
     side="under" kalshi_side="no")

3. **Add merge logic in `main()`** — build PX rows first, index by
   key.  Then build Kalshi rows, look up each by key:
   - Found → stamp `kalshi_ticker` + `kalshi_side` onto existing row
   - Not found → append as Kalshi-only row

4. **Remove separate Kalshi table** — one combined table with all
   columns: date, home, away, market_type, entity, line, side,
   px_line_id, kalshi_ticker, kalshi_side.

### Spread: how `build_kalshi_rows()` produces signed lines

Kalshi SPREAD-...-CHA12 has: team_abbr="CHA", line=12.5 (positive).

To produce canonical signed lines matching PX convention:
- Row 1: side="CHA", line=-12.5, kalshi_side="yes"
  (CHA is the team being asked about → favored → negative)
- Row 2: side=opponent, line=+12.5, kalshi_side="no"
  (opponent is on the other side → underdog → positive)

The opponent is whichever of home/away is NOT team_abbr.
