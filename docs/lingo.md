# American Sports Betting Markets — A Betfair Person's Guide

## The mental model shift

On Betfair you have an **exchange** with Back and Lay on discrete outcomes (a horse wins, or it doesn't). American sportsbooks structure things differently. There are roughly **four tiers** of market complexity in our data:

---

## 1. Moneyline — "Who wins?"

This is the closest to a Betfair **win market**. You pick which team wins the game. Two selections, that's it.

From the data (Brooklyn Nets at Cleveland Cavaliers):
```
Cleveland Cavaliers -840
Brooklyn Nets       +820
```

The numbers (`-840`, `+820`) are **American odds** — a different way to express the same thing as Betfair decimal odds:
- **Negative number** (favourite): `-840` means you must stake $840 to win $100. In decimal odds that's roughly 1.12.
- **Positive number** (underdog): `+820` means a $100 stake wins $820. In decimal odds that's 9.20.

Think of it this way: the sign tells you which side of $100 you're on. Negative = how much you risk to win $100. Positive = how much you win from a $100 risk.

In Betfair terms, **backing** the Cavaliers moneyline is like backing them on the win market. There's no separate Lay — the opposing moneyline selection is the equivalent.

---

## 2. Spread (Point Spread) — "Who wins after a handicap?"

This has no direct Betfair horse racing equivalent, but it's like an **Asian Handicap** in football betting. The favourite is handicapped to create a roughly 50/50 market.

From the data:
```
Cleveland Cavaliers  -17.5
Brooklyn Nets        +17.5
```

This means: take Cleveland's final score and subtract 17.5. If they still "win" after that adjustment, the Cleveland spread bet wins. The `.5` ensures no ties (no "push").

Why it exists: The Cavaliers are massive favourites (-840 moneyline). Nobody wants to bet at 1.12. The spread creates an interesting bet — "Can Cleveland win by 18 or more?"

The spread market typically has **multiple alternate lines** (e.g. -16.5, -17.5, -18.5) with different odds for each.

---

## 3. Totals (Over/Under) — "How many points in total?"

This is like betting on whether a value will go over or under a set line. No Betfair racing equivalent, but conceptually simple.

From the data:
```
Total Points:
  over 225.5     line: 225.5
  under 225.5    line: 225.5
```

You're betting on whether the combined score of both teams will be over or under 225.5. Again, the `.5` prevents ties.

**Team Totals** are the same concept but for one team only:
```
CLE: Team Total Points
  over 121.5
  under 121.5
```

Like totals, these offer multiple alternate lines (226, 226.5, etc.).

---

## 4. Player Props (Propositions) — "How will an individual player perform?"

This is the **bulk** of the market catalogue (look at how many there are for one game!). A "prop" is a bet on something other than the game outcome.

From the data:
```
James Harden Points:
  over 9.5
  under 9.5
```

Will James Harden score more or less than 9.5 points? Same over/under structure as totals, but focused on one player's individual statistics.

The data shows props for:
- **Points** — scoring
- **Rebounds** — grabbing the ball after a missed shot
- **Assists** — passing to a teammate who then scores
- **Made Threes** — successful 3-point shots
- **Steals** — taking the ball from an opponent
- **Blocks** — deflecting an opponent's shot
- **Turnovers** — losing possession (errors, essentially)

And **combinations**:
- **Points + Rebounds** — add the two stats together, over/under
- **Points + Rebounds + Assists** — add all three
- **Steals + Blocks** — defensive combo

And **milestone props** (yes/no, like moneyline):
- **Double Double** — reaching double figures (10+) in two stat categories
- **Triple Double** — double figures in three categories

---

## 5. Period Markets — Partial-game variants

All of the above (moneyline, spread, totals) can also be offered for portions of the game:
- **First Half** / **Second Half**
- **1st Quarter**, **2nd Quarter**, etc.

Same logic, just applied to a shorter window.

---

## 6. Futures — "Who wins the championship?"

This is what **Kalshi** offers. From our data:
```
"Will the Washington win the 2026 Pro Basketball Finals?"
```

These are Betfair-style **outright / ante-post** markets. Binary yes/no on a season-long outcome. Kalshi structures each as a separate binary contract (yes/no), not a multi-runner market — so "NBA Finals winner" isn't one market with 30 runners, it's 30 separate yes/no contracts.

---

## How the ProphetX data structure maps to this

In ProphetX's hierarchy:
- **Event** = a game (e.g. "Brooklyn Nets at Cleveland Cavaliers")
- **Market** = a betting market on that game (e.g. "Spread", "Donovan Mitchell Points")
- **Selections** = the outcomes within a market (e.g. "over" / "under", or team names)
- **Market Lines** = alternate lines for the same market (spread of -16.5, -17.5, -18.5 etc.)

In Betfair terms: an Event is a race meeting, a Market is "Win" or "Place", and Selections are the runners. Market Lines have no Betfair equivalent — they're like offering the same race with different handicap weights simultaneously.

---

## Summary cheat sheet

| American term | Closest Betfair concept | What it means |
|---|---|---|
| Moneyline | Win market | Pick the winner |
| Spread | Asian Handicap | Winner after applying a points handicap |
| Total (O/U) | — | Combined score over/under a line |
| Team Total | — | One team's score over/under |
| Player Prop | — | Individual player stat over/under |
| Futures | Ante-post / Outright | Season-long outcome |
| Selection | Runner | One side of a bet |
| Line | Handicap value | The number the spread or total is set at |
