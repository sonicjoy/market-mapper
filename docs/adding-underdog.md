# Adding Underdog UDX

Underdog UDX is Underdog's CFTC-regulated event-contract exchange. Every market is a binary YES contract on
one outcome, and takers RFQ **parlays of 2–9 of those single markets**. We respond to those RFQs, so every
leg has to be mapped to our canonical contract identity before it can be priced. This guide is the
starting point for an Underdog source in mmmapper, in the same shape as `adding-dkex.md`.

Like DKEX, UDX handed us **no Optic ids** when this guide was first measured, so everything is recovered from
the market. Since then the rows gained `external_ids.optic_odds`, which the pass does not trust to pick a fixture
(item 13). Unlike DKEX,
every UDX market also carries an **English contract sentence** that states exactly what YES means
("Resolves Yes if the New York Giants beat the Arizona Cardinals by at least 2.5 points in the National
Football League game between …"). That sentence is a second, independent witness the adapter should use —
with one large exception (section *The things that are easy to get wrong*, item 1).

Everything below was measured on 2026-09-23 against the **prod** venue unless it says otherwise. The raw data
is committed next to this file in `docs/underdog/` (see *Data files*).

## How the mapper reads a contract (typed fields, no ticker parsing)

The mapper never parses a ticker; it is carried as the opaque RFQ key. Each catalogue row is read from:

| Need | Source |
|---|---|
| Canonical market and period | `external_ids.optic_odds.market_id`, per sport, in `mappers/vocab/underdog_markets.py` |
| Which league a row belongs to | `external_ids.optic_odds.fixture_id` is one of the league's Optic fixtures |
| Teams, kickoff, YES side, line, player | the contract sentence (`mappers/exchanges/underdog.py`) |
| Fixture | name + kickoff within the window; the Optic fixture id only when the sentence states no kickoff (NBA props), and as a witness otherwise |

Leagues and market tables are code (`UNDERDOG_LEAGUE_SLUGS`, `with_code_underdog`); the tip is not read or written for them.
The sections below describe the venue as first measured on 2026-09-23 and the ticker grammar it used; that grammar now lives
only in `mappers/control_plane/underdog_legacy_*.py` for the tip-era gap tools and should be deleted with them.
MLB inning markets (`1st_3_innings_*`, `1st_7_innings_*`, `1st_half_*` on baseball) stay unmapped until Underdog confirms what an inning count means.

## Where the catalogue comes from

| Source | Host | Auth | Freshness | Use |
|---|---|---|---|---|
| Prod REST `GET /markets` | `https://api.underdogexchange.com` | venue API key (signed) | live | **production** |
| UAT REST `GET /markets` | `https://api.uat.udx.underdogsports.com` | UAT key | live, but UAT has listed only expired MLB since 2026-09-07 | development only |

The venue's published AsyncAPI (`servers` block) still names `api.udx.underdogsports.com` for prod. **That host
has no DNS record**; the live prod host is `api.underdogexchange.com` (confirmed with Underdog, probed
2026-09-23). Do not read the host out of their spec.

**Endpoint.** `GET /markets?type=single_leg&limit=100`, then follow `next_page_url` (it carries a `page` token)
until it is null. `type=multi_leg` returns the combo markets that RFQs mint (`UDXCOMBO-<id>` with a `legs[]`
list) — the mapper does not need them; every combo leg is an ordinary single-leg ticker. Useful row fields:
`ticker`, `description`, `status` (`open`, `unopened`, `paused`, `closed`, `expired`), `expires_at`,
`tick_size`, `minimum_price`, `maximum_price`.

**Rate limits.** Unauthenticated `/markets` is allowed but throttled — 8 requests per 2 s on UAT
(`RateLimit-Policy: "read";q=8;w=2`; not measured on prod). Authenticated calls use the member bucket; on prod our member reads
**12,000/min, burst 400** (`GET /rate_limit_profile`, profile `tier_0` v2). A full single-leg pull is about 424
pages today, so sign the requests.

**Auth.** Three headers on every signed request plus a version pin:

| Header | Value |
|---|---|
| `UDX-Access-Key` | the API key id |
| `UDX-Access-Timestamp` | Unix epoch **milliseconds** as a string, within 30 s of server time |
| `UDX-Access-Signature` | base64 of RSA-PSS (SHA-256, MGF1-SHA-256, 32-byte salt) over the message below |
| `UDX-Version` | `2026-07-15` (omitting it selects the oldest version ever shipped) |

Message for a GET = `timestamp_ms + "GET" + path`, with the path **without** its query string
(`1790000000000GET/markets`). Bodies and idempotency keys only enter the message on mutations, which the
mapper never makes.

**Credential — the long-lead item.** Do not reuse the RFQ trading key: it carries trade scope. UDX
distinguishes unrestricted trade-scoped keys from account-restricted ones (`createAccount` in their OpenAPI),
so ask Underdog for a **read-only key for the catalogue** and store it in GSM (`rs-marketmaking`).

## Size and shape of the book

On 2026-09-23 prod listed **42,317 single-leg markets, 29,234 open, in 142 families** (a family is the ticker
prefix before the first `_`, e.g. `UDXNFLSPREAD1H`).

Open markets by venue sport code: `NCAAMFB` 12,764 · `NFL` 8,505 · `MLB` 5,789 · `WNBA` 514 · `MLS` 451 ·
`ATP` 385 · `WTA` 286 · `LIGAMX` 206 · `UFC` 200 · `ITFMEN`/`ITFWOMEN` 68 · `ATPCHL` 64 · `NBA` 2 (futures only).

What takers actually parlay is much narrower. Across a sample of **18,676 prod parlays (91,886 legs, 2–9 legs
each)**:

| Family | Open markets | Legs in real parlays |
|---|---:|---:|
| `UDXMLBGAMEWIN` | 146 | 32,070 |
| `UDXNFLGAMEWIN` | 64 | 14,126 |
| `UDXMLBTOTAL` | 174 | 7,703 |
| `UDXMLBSPREAD` | 118 | 6,320 |
| `UDXNFLSPREAD` | 439 | 4,352 |
| `UDXNCAAMFBGAMEWIN` | 240 | 3,968 |
| `UDXWNBAGAMEWIN` | 14 | 3,837 |
| `UDXATPCHLMATCHWIN` | 64 | 3,105 |
| `UDXWTAMATCHWIN` | 52 | 2,860 |
| `UDXMLBRFI` | 43 | 2,142 |
| `UDXNCAAMFBSPREAD` | 2,487 | 2,029 |
| `UDXWNBASPREAD` | 47 | 1,305 |
| `UDXATPMATCHWIN` | 44 | 1,298 |
| `UDXNFLTOTAL` | 325 | 1,279 |
| `UDXWNBATOTAL` | 51 | 1,042 |
| `UDXMLBTEAMTOTAL` | 230 | 789 |
| `UDXMLBHRR` | 1,108 | 577 |
| `UDXNCAAMFBTOTAL` | 2,133 | 483 |
| `UDXMLBHR` | 559 | 440 |
| `UDXUFCFIGHTWIN` | 24 | 405 |

Sport mix per parlay: MLB only 49% · NFL only 17% · MLB + WNBA 9% · NCAAF 6% · WNBA 3% · tennis about 5%.
Only 59 of the 142 families appear in any parlay in the sample. Every family, with counts and a verbatim
sentence, is in Appendix A.

**Suggested order**, by demand: MLB + NFL + WNBA game lines → NCAAF game lines → tennis match winner → MLB
RFI / team total / first-5 total → player props → UFC.

## The symbol grammar

```
UDX{SPORT}{PRODUCT}{PERIOD?}_{AWAY}{HOME}{YYMMMDD}{HHMM}{PLAYER?}_{SELECTION}

UDXNFLGAMEWIN_ARINYG26OCT041300_ARI              ARI @ NYG, Oct 4 2026 1:00pm ET, YES = Arizona wins
UDXNFLSPREAD_ARINYG26OCT041300_NYG2.5            YES = Giants win by >= 2.5
UDXNFLTOTAL_ARINYG26OCT041300_43.5               YES = over 43.5 points
UDXNFLSPREAD1H_ARISF26SEP271605_ARI0.5           first-half spread (period suffix 1H)
UDXMLBTOTAL5_ARICOL26SEP232040_1.5               first-5-innings total (period suffix 5)
UDXMLBHR_ARICOL26SEP232040ADAELAMADOR_0.5        player prop: Adael Amador over 0.5 HR
UDXATPMATCHWIN_ATMFAR26SEP230000_JFARIA          tennis: YES = Jaime Faria wins
UDXUFCFIGHTWIN_ALACAS26SEP261720_ALATENG         UFC: YES = Alatengheili wins
UDXMLSGAMEWIN_CHICLT26SEP261930_CHI              soccer: YES = Chicago Fire win in regulation
```

- **Sport codes seen:** `MLB NFL NBA WNBA NCAAMFB ATP ATPCHL WTA ITFMEN ITFWOMEN UFC MLS LIGAMX` (plus one
  expired `LALIGA` row). Note `NCAAMFB`, not `NCAAF`.
- **Listed since 2026-09-28:** `FIFA` (international friendlies, national teams — league `international_friendlies`,
  not `international_club_friendlies`), `BRASILA`, `SAUDIPRO`, `ARGNAC`, `NHL`. ARGNAC / BRASILA sentences name the
  HOME side first, like UNL. NHL asks a question instead of "Resolves Yes if": "Will NHL Minnesota Wild score above
  1.5 more goals … of Boston Bruins (away) at Minnesota Wild (home) …"; totals put the pair right after "Will NHL".
  `UDXNHLTEAMGOALS` has no Optic hockey market and stays unmapped. Live rows: `docs/underdog/udx_new_leagues_2026-09-29.json`.
- **Products** are the letters after the sport up to the period suffix or `_`: `GAMEWIN`, `SPREAD`, `TOTAL`,
  `TEAMTOTAL`, `MATCHWIN`, `FIGHTWIN`, `RFI`, `BTTS`, and the prop codes (`HR`, `KS`, `HITS`, `TB`, `HRR`, `RBI`,
  `REC`, `RECYDS`, `RUSHYDS`, `PASSYDS`, `PASSTD`, `PASSATT`, `TD`, `FIRSTTD`, `PTS`, `REB`, `AST`, `3PT`, …).
  Appendix A lists every one.
- **Period suffix:** `1H`, `2H`, `1Q`–`4Q` (football, basketball, soccer), and a bare inning count `3`, `5`, `7`
  (MLB: `TOTAL5`, `SPREAD5`, `GAMEWIN3`, …). **The period is part of the key** — see item 1 below.
- **Teams:** `{AWAY}{HOME}` concatenated with no separator (`ARINYG`, `CONNWSH`, `AAMUFAMU`). Codes are
  usually 2–4 letters, but NCAAF also has `SDKST`, `LINDEN` and the mixed-case `Mercyh`. Split the way Kalshi
  does: the event's own two win-market selections (`GAMEWIN` / `MATCHWIN` / `FIGHTWIN`, `DRAW` ignored) must
  rebuild the blob, in away+home order. On 2026-09-25 that split all 227 team events and never disagreed
  with a code-list split. Events with no open win market fall back to the codes other events proved, then to
  the selection itself; two valid splits are refused, not guessed.
- **Tennis and UFC blobs are surname stems**, not codes: `ANDBAS` = ANDrade + BASavareddy, in sentence order
  (853 of 853 rows on 2026-09-25). Their win selections never rebuild the blob, so no team split is attempted.
- **Date/time:** `YYMMMDD` + `HHMM` in **US Eastern** (`26OCT041300` = 2026-10-04 13:00 ET = 17:00Z). The
  sentence repeats it ("originally scheduled for 1:00pm ET on October 4, 2026").
- **Player segment:** props append a truncated player token to the event segment
  (`…26SEP232040ADAELAMADOR`, `…26SEP271605MARVINHARRIS`). It is truncated (Marvin Harrison Jr. →
  `MARVINHARRIS`), so take the name from the sentence, not the token.
- **Selection:** a team code (`ARI`), team code + line (`NYG2.5`), a bare line (`43.5`), a player code
  (`JFARIA`), or a product-specific token (`RFI`, `DIST`, `DEC`, `R1`, `RBARCELR1`, `RBARCELDEC`).
- **Player code:** first initial + family name, **cut to 7 characters** (`AANDRAD` = Andres Andrade,
  `CCANIAT` = Carlo Alberto Caniato); a single-word name is its first 7 letters (`ALATENG`). Checked against all
  169 `MATCHWIN` / `FIGHTWIN` selections on 2026-09-25.

## The sentence grammar

Every sentence ends with the same tail:

```
… the {LEAGUE} game between the {AWAY} and the {HOME} originally scheduled for {H:MM}{am|pm} ET on {Month D, YYYY}.
```

(`match between` for tennis, `fight between` for UFC.) Tennis and UFC also drop both articles: "between Andres
Andrade and Nishesh Basavareddy". The part before it states the contract. The shapes seen
for game lines, verbatim:

| Product | Sentence (verbatim prod example) |
|---|---|
| GAMEWIN (MLB, WNBA, NCAAF) | Resolves Yes if the Arizona Diamondbacks win the Major League Baseball game between … |
| GAMEWIN (NFL) | Resolves Yes if the Arizona Cardinals score more points than their opponent during the full duration of the National Football League game between … |
| SPREAD | Resolves Yes if the New York Giants beat the Arizona Cardinals by at least 2.5 points in the National Football League game between … |
| TOTAL (NFL, WNBA, NCAAF) | Resolves Yes if there are above 43.5 points in the National Football League game between … |
| TOTAL (MLB) | Resolves Yes if there are above 10.5 runs during the full duration in the Major League Baseball game between … |
| TEAMTOTAL (MLB) | Resolves Yes if Arizona Diamondbacks records above 1.5 runs during the full duration of the Major League Baseball game between … |
| TEAMTOTAL (NFL) | Resolves Yes if the Arizona Cardinals records above 10.5 points during the entire game, including regulation time and any officially designated overtime periods of the National Football League game between … |
| RFI (MLB) | Resolves Yes if there are above 0.5 runs during the 1st inning in the Major League Baseball game between … |
| TOTAL5 (MLB) | Resolves Yes if there are above 1.5 runs during the first 5 innings in the Major League Baseball game between … |
| MATCHWIN (tennis) | Resolves Yes if Jaime Faria wins the ATP Tour match between Terence Atmane and Jaime Faria originally scheduled for 12:00am ET on September 23, 2026. |
| SPREAD (tennis) | Resolves Yes if Jaime Faria wins at least 1.5 more games than their opponent in the ATP Tour match between … |
| FIGHTWIN (UFC) | Resolves Yes if Alatengheili wins the Ultimate Fighting Championship fight between Alatengheili and John Castaneda originally scheduled for 5:20pm ET on September 26, 2026 during the entire fight. |
| GAMEWIN (MLS) | Resolves Yes if Chicago Fire FC score more goals than their opponent during regulation time of the Major League Soccer game between … |
| Player prop | Resolves Yes if Adael Amador records above 0.5 home runs during the full duration of the Major League Baseball game between … |

Comparators, which decide the YES side:

- **"by at least N"** — YES on exactly N (a UDX spread is a one-sided `>=` threshold on the named team).
- **"above N"** — YES only strictly over N.
- **"win" / "score more … than their opponent"** — a tie resolves NO.
- Units: `runs` (MLB), `points` (NFL, NBA, WNBA, NCAAF), `goals` (soccer), `games` (tennis).

## The things that are easy to get wrong

1. **8,784 period markets are worded as the full game.** On every row of these families the sentence
   describes the *full game*; only the ticker suffix says it is a half, quarter or inning count:

   | Families | Rows |
   |---|---:|
   | NFL `SPREAD` and `TOTAL` × `1H` `2H` `1Q`–`4Q` | 2,523 |
   | NCAAF `GAMEWIN`, `SPREAD`, `TOTAL` × `1H` `2H` `1Q`–`4Q` | 4,829 |
   | WNBA `SPREAD` and `TOTAL` × `1H` `2H` `1Q`–`4Q` | 720 |
   | MLB `GAMEWIN3/5/7`, `SPREAD3/5/7` | 632 |
   | Liga MX `GAMEWIN1H`, `SPREAD1H`, `TOTAL1H` | 80 |

   Worded correctly: NFL `GAMEWIN1H`–`4Q` ("during the first half …"), MLB `TOTAL3/5/7` ("during the first 5
   innings"), MLS `…1H`. So: **key the period on the typed `external_ids.optic_odds.market_id`
   (`mappers/vocab/underdog_markets.py`), never on the sentence and never on the ticker suffix**, and treat
   the sentence as confirming everything *except* the period. MLB `GAMEWIN3` could mean the first three innings or
   the third inning alone — do not infer it (Polymarket US mapped a similar `i3` token to "first 3 innings" by
   inference and lost $274,380 on 2026-09-21). Hold the MLB inning families until Underdog confirms the
   definition in writing.

2. **Integer lines are a different contract.** "beat the Dallas Cowboys by at least 3 points"
   (`UDXNFLSPREAD_BALDAL26SEP271625_BAL3`) wins on exactly 3; an Optic −3 pushes on exactly 3. "above 7 runs"
   (`UDXMLBTOTAL_MIACHC26SEP221940_7`) loses on exactly 7; an Optic 7 total pushes. Prod had 9 NFL integer
   spreads, 1 NCAAF (`…_UGA14`) and 1 MLB total. **Do not emit integer lines.**

3. **A tie is NO on every "win" market.** Period win markets therefore correspond to the **3-way** types, not
   the 2-way moneylines: NFL `GAMEWIN1H` ("score more points than their opponent during the first half") →
   `FIRST_HALF_WINNER_3WAY`, not `FIRST_HALF_MONEYLINE`. The same holds for MLB inning winners (`GAMEWIN5` →
   `FIRST_FIVE_MONEYLINE_3WAY`), where a tie after five innings is common.

4. **Soccer is regulation time, 3-way.** MLS `GAMEWIN` says "during regulation time"; a draw is NO. Map only to
   `MONEYLINE_3WAY` with YES = the named team — never `MONEYLINE`.

5. **Every game has two `GAMEWIN` tickers — the satellite case.** One per team (`…_ARI`, `…_NYG`; exactly 2
   per event on all 32 open NFL games). The NO side of `_ARI` is the YES side of `_NYG` (NFL tie aside). Emitting
   both canonical sides per symbol collides exactly as DKEX `WIN` did, so use the satellite path
   (`attach_dkex_row` pattern) and extend the MERGE key.

6. **Deep ladders.** NFL games list a median of 25 spread tickers (both teams, e.g. `ARI1.5` … `COL3.5`), NFL
   totals a median of 19, WNBA totals up to 47, NCAAF spreads up to 46. A spread ticker `X1.5` is X −1.5 (YES)
   and the opponent +1.5 (NO); the venue lists only "beat by at least" lines, so no two tickers share a side.
   The mapper reads team and line from the sentence, not from the ticker.
   Expect the DKEX result: most unstamped rungs will be "Optic ladder lacks this line" — drop them, never
   interpolate.

7. **Player codes collide.** `DBLANCH` (ATP Challenger) is both **Dali Blanch** and **Darwin Blanch**
   (`UDXATPCHLMATCHWIN_BLAMOE26SEP250600_DBLANCH`). Key tennis and prop aliases on the full name from the
   sentence, never on the code alone.

8. **Team-defence entities sit in "player" families.** `UDXNFLTD_…ARIZONACARDI_0.5` is "Arizona Cardinals D/ST
   records above 0.5 touchdowns", and `NEWENGLANDPA` / `SEATTLESEAHA` are written both "… D/ST" and
   "… Defense". Split D/ST from players before choosing a prop type.

9. **Choose the side by team name, never by position.** The venue lists AWAY then HOME; Optic has its own
   home/away. They agreed on every matched team-sport event (below), but one ATP Challenger match was listed the
   other way round — and a positional copy would have priced the other player.

10. **MLB needs a narrow window, not the exact minute.** Teams play three-game series on consecutive days
    (starts 18–24 h apart) and doubleheaders (TB @ NYY at 17:05Z and 23:05Z on 2026-09-22), so a same-day
    fallback would pick the wrong game. But game 2 of a doubleheader drifts: on 2026-09-25 CHC @ BOS game 2 was
    19:10 ET in UDX and 18:05 in Optic, BAL @ NYY game 2 19:05 against 19:25, and the exact-minute rule dropped
    every game-2 row. Team sports take the nearest same-name fixture within ±2 h, Polymarket's window.

11. **Tennis times are placeholders.** 60 of 259 tennis events had matching player names but a start time more
    than a day before Optic's (e.g. `UDXATPMATCHWIN_ATMFAR26SEP230000` listed 2026-09-23 04:00Z, Optic
    2026-09-24 05:30Z). Tennis and UFC take the nearest same-name fixture within ±6 h, else the only one
    within ±3 days.

12. **Venue grammar quirks — alias, don't "fix".** NCAAF drops "the" before the YES team but keeps it before the
    opponent ("if Alabama A&M beat the Florida A&M"); team totals read "if Arizona Diamondbacks records above";
    names can be long ("Pumas de la Universidad Nacional Autonoma de Mexico").

13. **UDX's own Optic id is a witness, not a join key.** By 2026-09-25, 37,073 of 37,084 open rows carried
    `external_ids.optic_odds` (`fixture_id`, `market_id`, `player_id` / `team_id`). Its `fixture_id` agreed with the
    name + kickoff join on 288 of 291 joined events, but it was **swapped** on the BAL @ NYY doubleheader (the
    16:05 tickers named game 2, the 19:05 tickers game 1), and an id-first join moved 22 correct game-1 markets
    onto game 2 (!298). Since 2026-10-10 the pass joins on that id when both sentence names fit the fixture it
    names: the sentence's "originally scheduled" kickoff went stale (12:00am ET placeholders on NCAAF, every
    open MLB row hours off), leaving 2,707 of 34,275 open rows unmapped with the right fixture named. Kickoff
    only decides when a same-pair fixture sits within 36 h (doubleheader, series): the sentence kickoff, else
    `expires_at` less 3 days (exact on 99% of NCAAF, MLB and soccer rows, not NHL), picks the game. Replayed
    on the 2026-10-10 catalogue: no row moved to a different fixture. After a stamp,
    `underdog_udx_optic_witness` rejects on fixture / team / player disagreement and alerts (without rejecting) when
    `market_id` is outside the product catalogue in
    ``docs/underdog/udx_optic_market_ids_2026-09-28.csv``.

## Fixture resolution, measured

Method: every UDX event that has a `GAMEWIN` / `MATCHWIN` / `FIGHTWIN` market (the sentence gives both names and
the ET start), matched against `rs-marketmaking.opticodds_us.opticodds_fixtures` for 2026-09-15 → 2026-10-12
(1,681 fixtures in the eleven leagues below; 25 MB scanned). A match requires both normalised names equal to the
fixture's `home_team_display` / `away_team_display`; then exact minute, else within 45 min, else the only
fixture that UTC day.

| UDX sport | Optic `league.id` | Events | Matched | Exact minute | ≤ 45 min | Same day, unique | Names match, time > 1 day off |
|---|---|---:|---:|---:|---:|---:|---:|
| `NFL` | `nfl` | 32 | **100%** | 32 | 0 | 0 | 0 |
| `NCAAMFB` | `ncaaf` | 119 | **100%** | 117 | 0 | 2 | 0 |
| `MLB` | `mlb` | 89 | **98.9%** | 88 | 0 | 0 | 0 (1 ambiguous) |
| `WNBA` | `wnba` | 13 | **100%** | 13 | 0 | 0 | 0 |
| `MLS` | `usa_-_major_league_soccer` | 16 | **100%** | 16 | 0 | 0 | 0 |
| `LIGAMX` | `mexico_-_liga_mx` | 9 | **100%** | 5 | 2 | 2 | 0 |
| `UFC` | `ufc` | 17 | **100%** | 11 | 5 | 1 | 0 |
| `WTA` | `wta` | 95 | 82.1% | 21 | 6 | 51 | 17 |
| `ATP` | `atp` | 50 | 74.0% | 21 | 4 | 12 | 13 |
| `ATPCHL` | `atp_challenger` | 114 | 73.7% | 21 | 14 | 49 | 30 |

- **No name residue at all.** Every event's two names matched an Optic fixture after normalising (lowercase,
  non-alphanumerics to spaces, `&` → `and`). Unlike DKEX's CFB list, there is no alias gap for team sports today.
- **Orientation.** Venue AWAY = Optic away on 492 of 493 matched events; the one exception is an ATP Challenger
  match. None of the matched fixtures were flagged `venue_neutral`.
- **Tennis misses are time, not names** (item 11). `ITFMEN` / `ITFWOMEN` were not measured; mmmapper seeds
  already carry `itf_men` / `itf_women` keys.
- Raw output: `docs/underdog/fixture_resolution_2026-09-23.txt`.

What `underdog_pass._match_fixture` does: both names must fit an Optic fixture in either order (`names_fit`,
person rules for tennis and UFC), then the nearest start within ±2 h for team sports or ±6 h for people, a tie
refused. People with nothing that close take the only same-name fixture within ±3 days. On the 2026-09-25 live
catalogue that joined 291 of 312 events, every tennis and UFC event included; 16 of the 21 misses were NFL games
with no Optic fixture under those names.

## Leagues

| UDX code | Venue writes | Optic `league.id` (measured) |
|---|---|---|
| `MLB` | Major League Baseball | `mlb` |
| `NFL` | National Football League | `nfl` |
| `NBA` | National Basketball Association | `nba` |
| `WNBA` | Women's National Basketball Association | `wnba` |
| `NCAAMFB` | NCAA Football | `ncaaf` |
| `ATP` | ATP Tour | `atp` |
| `ATPCHL` | ATP Challenger | `atp_challenger` |
| `WTA` | WTA Tour | `wta` (not `wta_doubles`) |
| `ITFMEN` / `ITFWOMEN` | International Tennis Federation | not measured (seed keys `itf_men`, `itf_women`) |
| `UFC` | Ultimate Fighting Championship | `ufc` |
| `MLS` | Major League Soccer | `usa_-_major_league_soccer` |
| `LIGAMX` | Mexican Liga MX | `mexico_-_liga_mx` (not `_women` / `_u21`) |

## Aliases

- **Teams — 362 codes, all unique within their sport** (`docs/underdog/team_aliases_2026-09-23.csv`): MLB 30 ·
  NFL 32 · WNBA 15 · NCAAF 237 · MLS 30 · Liga MX 18. Derived from `GAMEWIN` tickers (code order away, home)
  against "between the A and the B", keeping a row only when the YES team in the sentence is the selection code.
  Codes are mostly 2–4 letters (WNBA `CONN` = Connecticut Sun; NCAAF `AAMU` = Alabama A&M), with longer and
  mixed-case NCAAF exceptions (*The symbol grammar*, Teams). Inline tables in Appendix B.
- **Players — 1,167 codes** (`docs/underdog/player_aliases_2026-09-23.csv`): MLB 403 · NFL 309 · WNBA 69 · ATP 74
  · ATP Challenger 148 · WTA 130 · UFC 34. Three conflicts: `DBLANCH` (two players) and the two NFL D/ST vs
  Defense spellings (items 7–8).
- Because UDX names equal Optic display names on every matched event and the mapper reads names from the
  sentence, no code aliases are needed. The codes above are evidence only. If a name ever needs a pin, it is a
  code table in `mappers/vocab/` or `mappers/exchanges/underdog*.py` with a test, never a tip alias.

## Market-type crosswalk

Against `mappers/market_types.py` on `origin/main` (2026-09-23), line numbers in brackets. Every UDX market is a
YES contract; the YES column is what the canonical row's selection must be.

| UDX family | `MarketType` | YES side | Note |
|---|---|---|---|
| `GAMEWIN` (MLB, NFL, NBA, WNBA, NCAAF) | `MONEYLINE` (68) | named team | NFL "full duration": tie is NO |
| `SPREAD` | `POINT_SPREAD` (69) | named team, line negated | MLB run line uses the same type; half lines only |
| `TOTAL` | `GAME_TOTAL` (74) | over | MLB "during the full duration" |
| `TEAMTOTAL` | `TEAM_TOTAL` (189) | named team over | NFL wording includes overtime |
| NFL `GAMEWIN1H` | `FIRST_HALF_WINNER_3WAY` (102) | named team | tie is NO |
| NFL `GAMEWIN1Q` | `FIRST_QUARTER_WINNER_3WAY` (105) | named team | tie is NO |
| NFL `GAMEWIN2H` | `SECOND_HALF_WINNER_3WAY` (103) | named team | tie is NO |
| `GAMEWIN2Q`–`4Q` | none | — | no type |
| `SPREAD1H` / `TOTAL1H` | `FIRST_HALF_POINT_SPREAD` (76) / `FIRST_HALF_TOTAL` (77) | — | full-game wording (item 1) |
| `SPREAD1Q` / `TOTAL1Q` | `FIRST_QUARTER_POINT_SPREAD` (106) / `FIRST_QUARTER_TOTAL` (107) | — | full-game wording |
| `TOTAL2H` | `SECOND_HALF_TOTAL` (80) | over | full-game wording |
| NBA `TEAMTOTAL1H` | `FIRST_HALF_TEAM_TOTAL` | named team over | "points scored during the first half"; 154 open, 2026-10-29 |
| `SPREAD2H`, `SPREAD2Q`–`4Q`, `TOTAL2Q`–`4Q` | none | — | no type |
| MLB `TOTAL5` | `FIRST_FIVE_TOTAL` (87) | over | worded correctly |
| MLB `SPREAD5` | `FIRST_FIVE_POINT_SPREAD` (86) | — | full-game wording |
| MLB `GAMEWIN5` | `FIRST_FIVE_MONEYLINE_3WAY` (94) | named team | tie is NO; full-game wording |
| MLB `GAMEWIN3` | `FIRST_THREE_MONEYLINE_3WAY` (98) | — | only after Underdog confirms "first 3 innings" |
| MLB `TOTAL3/7`, `SPREAD3/7`, `GAMEWIN7` | none | — | no type |
| MLB `RFI` | `FIRST_INNING_TOTAL` (82) | over 0.5 | "above 0.5 runs during the 1st inning" |
| MLB `HR` `KS` `HITS` `TB` `HRR` `RBI` | `PLAYER_HOME_RUNS` (230) `PLAYER_STRIKEOUTS` (231) `PLAYER_HITS` (232) `PLAYER_BASES` (233) `PLAYER_HITS_RUNS_RBIS` (234) `PLAYER_RBIS` (235) | player over | name from the sentence |
| NFL `PASSYDS` `PASSTD` `RECYDS` `REC` `RUSHYDS` `PASSATT` | `PLAYER_PASSING_YARDS` (240) `PLAYER_PASSING_TOUCHDOWNS` (242) `PLAYER_RECEIVING_YARDS` (243) `PLAYER_RECEPTIONS` (244) `PLAYER_RUSHING_YARDS` (245) `PLAYER_PASSING_ATTEMPTS` (247) | player over | — |
| NFL `TD` | `PLAYER_TOUCHDOWNS` (260) for players | player over | D/ST rows are team entities (item 8) |
| NFL `FIRSTTD` | `FIRST_TOUCHDOWN_SCORER` (261) | named player | — |
| WNBA `PTS` `AST` `REB` `3PT` | `PLAYER_POINTS` (215) `PLAYER_ASSISTS` (216) `PLAYER_REBOUNDS` (217) `PLAYER_THREES` (218) | player over | — |
| Tennis `MATCHWIN` (ATP, ATPCHL, WTA, ITF) | `MONEYLINE` (68) | named player | selection = player code |
| Tennis `TOTAL` | `MATCH_TOTAL_GAMES` (149) | over, games | — |
| Tennis `SPREAD` | none (`SET_HANDICAP` (152) is sets) | named player by ≥ N games | games handicap has no type |
| UFC `FIGHTWIN` | `MONEYLINE` (68) | named fighter | "during the entire fight" |
| UFC `DISTANCE` / `TOTAL` / `MOV` / `MOVFINISH` / `FIGHTWINROUND` | `GO_THE_DISTANCE` (291) / `TOTAL_ROUNDS` (162) / `METHOD_OF_VICTORY` (288) / `METHOD_OF_FINISH` (289) / `ROUND_BETTING` (290) | per sentence | read each sentence first |
| Soccer `GAMEWIN` (MLS, LIGAMX) | `MONEYLINE_3WAY` (101) | named team | regulation time; never `MONEYLINE` |
| Soccer `BTTS` | `BTTS` (131) | yes | Liga MX only on 2026-09-23 |
| Soccer `SCORE` (BRASILA, SERIEA, LIGAMX, MLS, LIGUE1) | `CORRECT_SCORE` | winner (or draw) + winner-first score, YES only | 90 minutes: sentence, or Brazil's rules, must say "excluding extra time" |
| NHL `GOALS` `ASSISTS` `POINTS` `SHOTSONGOAL` | `PLAYER_GOALS` `PLAYER_ASSISTS` `PLAYER_POINTS` `PLAYER_SHOTS_ON_GOAL` | player over | whole sentence + venue player id (below) |
| NHL `FGS` | `FIRST_GOAL_SCORER` | player YES only | whole sentence + venue player id; Optic lists no NO side (2026-10-29) |
| NHL `GOALIESAVES` | none (held) | — | no RFQ demand, 2026-10-15 |

### NHL skater props (2026-10-15): two witnesses, both required

The NHL prop ticker carries no team codes (`UDXNHLGOALS_2610151900<hex player id>_0.5`) and the sentence is a
question: "Will NHL Anton Johansson record above 0.5 goals during the entire game including overtime but excluding
the shootout of Philadelphia Flyers (away) at Detroit Red Wings (home), originally scheduled for October 15, 2026 at
7:00pm ET?". `mappers/exchanges/underdog_nhl_props.py` maps one only when:

1. the **whole sentence** is that contract — half-point line, the stat the venue's Optic `market_id` names, and
   Optic's hockey-prop settlement (overtime counts, the shootout never does; NHL *team* markets include the shootout
   and are a different contract);
2. the venue's `external_ids.optic_odds.player_id` names **exactly one** player on the matched Optic fixture, and
   that player is the sentence's player after `normalize_player_name`.

Anything else maps nothing (`unconfirmed`); an id naming a different player than the sentence is alerted
(`optic_player`). Measured on the prod catalogue + Optic NHL odds, 2026-10-15: 2,857 / 2,857 open skater-prop rows
fit the sentence and every player id named the sentence's player. Replay of `mappers.run --league nhl` on those
inputs: the 870 existing Underdog NHL stamps unchanged, 3,629 new stamps, each checked independently against the raw
Optic odd (fixture, market, Optic `player_id` = venue `player_id`, line, YES→over / NO→under). Every row with
its verdict: `docs/underdog/udx_nhl_props_replay_2026-10-15.csv.gz`.

UDX settles a player who does not take part at the "last fair market price" (CFTC filing NFLENTITYOUTCOME; no NHL filing found) — a
pricing difference from books that void, shared with every Underdog player prop, not a mapping one.

### NFL TD ladder, combined yards, kicking points (2026-10-19): same two witnesses, QB hold

`UDXNFLTD` lines 1.5 / 2.5 carry Optic `player_touchdowns` ("records above 1.5 touchdowns during the full game
(including overtime)"); the 0.5 line still carries `anytime_touchdown_scorer` and maps as before. `UDXNFLPASSRUSHYDS`,
`UDXNFLRUSHRECYDS` and `UDXNFLKICKPTS` carry `player_passing_+_rushing_yards`, `player_rushing_+_receiving_yards` and
`player_kicking_points` ("… during the full duration of the National Football League game …"). All four map only
through `mappers/exchanges/underdog_player_props.py`: the whole sentence for that market id, and the venue's player id
naming that player in the SAME Optic market on the fixture (Optic also labels the id "<team> :: <player>" in
`team_first_touchdown_scorer`, so other markets are never read).

**Passing touchdowns.** Underdog's NFL filing (NFLENTITYOUTCOME) only says "touchdowns" is the count of that
statistic. Underdog confirmed in writing (Jim Bumbulsky, 2026-10-19) that a quarterback's passing touchdowns do NOT
count, which matches its own `player_touchdowns` id and its prices (Purdy 2+ at 3-4c, McCaffrey 2+ at 28-33c): the
ladder is Optic's scorer-touchdown market for every player, quarterbacks included.

Live check, prod catalogue + Optic NFL/NCAAF/NHL odds, 2026-10-19 09:45Z, `mappers.run --json` on main and on the
branch: NFL `unmapped` 270 -> 9 (the 9 are `player_extra_points_made`, not in prod sport_subs), `held` 5 (Purdy,
Caleb Williams, Maye at 1.5; Daniels at 1.5 and 2.5), `unconfirmed` 0, `optic_player` 0; 295 new stamps, every one
checked independently against the raw Optic odd (fixture, market, Optic `player_id` = venue `player_id`, line and stat
from the sentence, YES->over / NO->under, no passer on the TD ladder): 295 PASS. Existing stamps byte-identical: NFL
3,856, NCAAF 13,603, NHL 1,862. Every row: `docs/underdog/udx_nfl_props_replay_2026-10-19.csv.gz`.

### NFL period draws read like a game tie but settle on the period (2026-10-19)

`UDXNFLGAMEWIN2Q/3Q/4Q/2H_*_DRAW` say "the National Football League game … is level at the end of the third quarter",
which reads like a game tie. Underdog's NFLGAMEWIN filing (CFTC 40.2(a), the contract spec the rulebook defers to) settles
every `<time period>` on that period's points: "only the points scored in <time period> are considered", and a Tie strike
resolves Yes when "<time period> ends with both teams having an equal number of points". That is Optic's
`*_moneyline_3-way` draw, so they map. Read the filing, not the sentence, for settlement (traders Henry and Matt checked
the period-market rules before mmmapper!442).

## What the rows must carry

`markets_us.market_mapping` rows with `sportsbook = 'Underdog'`, one per canonical row the pipeline stamps:

- the **UDX market ticker** in `source_ids` — the RFQ side resolves a leg *by ticker*, so each of an event's
  tickers (including both `GAMEWIN` twins) must land;
- the Optic `fixture_id`, `market_id`, `selection` and `line` of the ticker's **YES** side as the sentence states
  it (spread YES = named team with the line negated; total YES = over);
- nothing for the "do not emit" cases: integer lines, the unconfirmed MLB inning families, families with no
  `MarketType`, rungs Optic does not price.

The RFQ maker quotes a leg only when the row's identity agrees with its own mapping, so a wrong row costs a
missed quote, not a mispriced one — but it will be visible as a disagreement.

## Suggested build, following DKEX

1. `fetch/underdog.py` — **built**: `GET /markets?type=single_leg&status=open` pager to `underdog_markets.jsonl`,
   registered as an optional fetcher in `fetch/__main__.py` for leagues whose config resolves `UNDERDOG`
   (`underdog_requested`, set by `UNDERDOG_LEAGUE_SLUGS` via `with_code_underdog`). The read is
   public (prod `listMarkets` security includes `{}`; public bucket `RateLimit-Policy: "read";q=8;w=2`, so a full
   pull is ~350 pages / ~80 s); `UDX_AUTH=signed` signs with GSM `udx-api-key-id` / `udx-private-key` if that
   ever changes. Host from `UDX_API_BASE` (default `https://api.underdogexchange.com`).
2. `BigQuery/load_underdog_raw.py` + `raw_ingestion_us.underdog_raw` (schema + Terraform in the infra repo, like
   `dkex_raw`).
3. `mappers/exchanges/underdog.py` — typed fields only: `external_ids.optic_odds` for market and league, the
   sentence parser (the templates above) for teams, YES side, line and player, and `build_rows` emitting both
   canonical sides per ticker. The ticker is the opaque RFQ key, never parsed.
4. `mappers/vocab/underdog_markets.py` — the crosswalk above, keyed on the typed Optic `market_id` per sport;
   `UNDERDOG_LEAGUE_SLUGS` lists the leagues.
5. `UnderdogGenericProfile` + `LeagueConfig.UNDERDOG` threaded through `mappers/seed/` for football, baseball,
   basketball, tennis, MMA, soccer.
6. `_run_underdog_pass` + `attach_underdog_row` + the satellite path in `mappers/pipeline.py`; keep only
   `status == "open"`.
7. The `UNDERDOG` emit and MERGE-key extension in `BigQuery/load_mappings.py` (`market_id|selection_id`, as
   for Kalshi and DKEX).
8. `tests/mappers/test_underdog.py` driven by `docs/underdog/udx_markets_golden_2026-09-23.json`.
9. League set in code: `with_code_underdog` (`mappers/seed/tip_factories.py`) wires every slug in
   `UNDERDOG_LEAGUE_SLUGS`; no `mapping_leagues` row, no tip aliases. A change ships by MR with a test and the
   `regression:mapping-gate` delta (removed rows need a waiver in `regression/waivers.toml`).
10. AI validation: an Underdog block in `BigQuery/ai_validation.py` that feeds the judge the venue sentence —
    the most direct evidence any adapter has.

## Data files

All in `docs/underdog/`, pulled 2026-09-23:

| File | Holds |
|---|---|
| `prod_market_families_2026-09-23.csv` | 142 families: total and open rows, parlay-leg demand, one verbatim ticker + sentence each |
| `team_aliases_2026-09-23.csv` | 362 team codes → venue name, with the ticker each was learned from |
| `player_aliases_2026-09-23.csv` | 1,167 player codes → venue name, conflicts flagged |
| `udx_markets_golden_2026-09-23.json` | 3,417 verbatim rows: every prod MLB/NFL/WNBA `GAMEWIN`/`SPREAD`/`TOTAL` market (2,305), 720 UAT MLB rows, and 3 samples from each of the 133 other prod families — a ready test set |
| `fixture_resolution_2026-09-23.txt` | raw output of the fixture-resolution measurement |

Regenerate the catalogue with a signed pager over `GET /markets?type=single_leg` and keep `ticker`,
`description`, `status`, `expires_at`.

## Open questions

**For Underdog** (the owner sends these):

1. A read-only, account-restricted API key for the catalogue.
2. The definition of MLB `GAMEWIN3/5/7` and `SPREAD3/5/7` (first N innings, or inning N alone?).
3. Fixing the full-game sentences on the 8,784 period markets (item 1).
4. Updating the prod host in their published AsyncAPI.

**For the owner:**

1. Drop integer lines (recommended) or model the exact-number difference later.
2. Soccer: map `GAMEWIN` to `MONEYLINE_3WAY`, or leave soccer out.
(The `mapping_leagues` rows, code aliases and rule activation questions are closed: Underdog is code-owned,
see `CLAUDE.md`.)

## Appendix A — every prod market family, with a verbatim venue sentence

Pulled 2026-09-23 from `GET /markets?type=single_leg` on prod (42,317 rows, 142 families). Columns: total rows, open rows, and legs in a sample of 18,676 real prod parlays. Sentences are verbatim, venue grammar included. Source: `docs/underdog/prod_market_families_2026-09-23.csv`.

### MLB

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXMLBGAMEWIN` | 178 | 146 | 32070 | `UDXMLBGAMEWIN_ARICOL26SEP232040_ARI` | Resolves Yes if the Arizona Diamondbacks win the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBTOTAL` | 368 | 174 | 7703 | `UDXMLBTOTAL_ARICOL26SEP232040_10.5` | Resolves Yes if there are above 10.5 runs during the full duration in the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBSPREAD` | 255 | 118 | 6320 | `UDXMLBSPREAD_ARICOL26SEP232040_ARI1.5` | Resolves Yes if the Arizona Diamondbacks beat the Colorado Rockies by at least 1.5 runs in the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBRFI` | 60 | 43 | 2142 | `UDXMLBRFI_ARICOL26SEP232040_RFI` | Resolves Yes if there are above 0.5 runs during the 1st inning in the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBTEAMTOTAL` | 454 | 230 | 789 | `UDXMLBTEAMTOTAL_ARICOL26SEP232040_ARI1.5` | Resolves Yes if Arizona Diamondbacks records above 1.5 runs during the full duration of the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBHRR` | 2685 | 1108 | 577 | `UDXMLBHRR_ARICOL26SEP232040ADAELAMADOR_0.5` | Resolves Yes if Adael Amador records above 0.5 hits and runs and runs batted in during the full duration of the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBHR` | 1215 | 559 | 440 | `UDXMLBHR_ARICOL26SEP232040ADAELAMADOR_0.5` | Resolves Yes if Adael Amador records above 0.5 home runs during the full duration of the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBTOTAL5` | 226 | 106 | 280 | `UDXMLBTOTAL5_ARICOL26SEP232040_1.5` | Resolves Yes if there are above 1.5 runs during the first 5 innings in the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBHITS` | 1893 | 832 | 180 | `UDXMLBHITS_ARICOL26SEP232040COLECARRIGG_0.5` | Resolves Yes if Cole Carrigg records above 0.5 hits during the full duration of the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBKS` | 436 | 216 | 178 | `UDXMLBKS_ARICOL26SEP232040MASONADAMS_1.5` | Resolves Yes if Mason Adams records above 1.5 strikeouts during the full duration of the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBTB` | 2514 | 1194 | 103 | `UDXMLBTB_ARICOL26SEP232040ADAELAMADOR_1.5` | Resolves Yes if Adael Amador records above 1.5 total bases during the full duration of the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBSPREAD5` | 151 | 70 | 59 | `UDXMLBSPREAD5_ARICOL26SEP232040_ARI1.5` | Resolves Yes if the Arizona Diamondbacks beat the Colorado Rockies by at least 1.5 runs in the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBRBI` | 1374 | 673 | 44 | `UDXMLBRBI_ARICOL26SEP232040ADAELAMADOR_0.5` | Resolves Yes if Adael Amador records above 0.5 runs batted in during the full duration of the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBGAMEWIN3` | 93 | 42 | 40 | `UDXMLBGAMEWIN3_ARICOL26SEP232040_ARI` | Resolves Yes if the Arizona Diamondbacks win the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBGAMEWIN5` | 93 | 42 | 10 | `UDXMLBGAMEWIN5_ARICOL26SEP232040_ARI` | Resolves Yes if the Arizona Diamondbacks win the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBGAMEWIN7` | 93 | 42 | 3 | `UDXMLBGAMEWIN7_ARICOL26SEP232040_ARI` | Resolves Yes if the Arizona Diamondbacks win the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBEARNEDRUNS` | 221 | 98 | 0 | `UDXMLBEARNEDRUNS_ARICOL26SEP232040_MADAMS1.5` | Resolves Yes if Mason Adams records above 1.5 earned runs during the full duration of the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBTOTAL7` | 120 | 19 | 0 | `UDXMLBTOTAL7_ARICOL26SEP232040_8.5` | Resolves Yes if there are above 8.5 runs during the first 7 innings in the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBSPREAD7` | 118 | 20 | 0 | `UDXMLBSPREAD7_ARICOL26SEP232040_ARI0.5` | Resolves Yes if the Arizona Diamondbacks beat the Colorado Rockies by at least 0.5 runs in the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBTOTAL3` | 85 | 15 | 0 | `UDXMLBTOTAL3_ARICOL26SEP232040_3.5` | Resolves Yes if there are above 3.5 runs during the first 3 innings in the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBSPREAD3` | 84 | 15 | 0 | `UDXMLBSPREAD3_ARICOL26SEP232040_ARI0.5` | Resolves Yes if the Arizona Diamondbacks beat the Colorado Rockies by at least 0.5 runs in the Major League Baseball game between the Arizona Diamondbacks and the Colorado Rockies originally scheduled for 8:40pm ET on September 23, 2026. |
| `UDXMLBWALKSALLOWED` | 49 | 22 | 0 | `UDXMLBWALKSALLOWED_CINATL26SEP231915CHRISSALE_0.5` | Resolves Yes if Chris Sale records above 0.5 walks during the full duration of the Major League Baseball game between the Cincinnati Reds and the Atlanta Braves originally scheduled for 7:15pm ET on September 23, 2026. |
| `UDXMLBSTART` | 4 | 4 | 0 | `UDXMLBSTART_27_APR01` | Will the first game of the 2027 MLB regular season commence before April 1, 2027? |
| `UDXMLBCBA` | 1 | 1 | 0 | `UDXMLBCBA_26_DEC02` | Will MLB have a new CBA before December 2, 2026? |

### NFL

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXNFLGAMEWIN` | 64 | 64 | 14126 | `UDXNFLGAMEWIN_ARINYG26OCT041300_ARI` | Resolves Yes if the Arizona Cardinals score more points than their opponent during the full duration of the National Football League game between the Arizona Cardinals and the New York Giants originally scheduled for 1:00pm ET on October 4, 2026. |
| `UDXNFLSPREAD` | 439 | 439 | 4352 | `UDXNFLSPREAD_ARINYG26OCT041300_NYG2.5` | Resolves Yes if the New York Giants beat the Arizona Cardinals by at least 2.5 points in the National Football League game between the Arizona Cardinals and the New York Giants originally scheduled for 1:00pm ET on October 4, 2026. |
| `UDXNFLTOTAL` | 325 | 325 | 1279 | `UDXNFLTOTAL_ARINYG26OCT041300_43.5` | Resolves Yes if there are above 43.5 points in the National Football League game between the Arizona Cardinals and the New York Giants originally scheduled for 1:00pm ET on October 4, 2026. |
| `UDXNFLTEAMTOTAL` | 955 | 955 | 201 | `UDXNFLTEAMTOTAL_ARISF26SEP271605_ARI10.5` | Resolves Yes if the Arizona Cardinals records above 10.5 points during the entire game, including regulation time and any officially designated overtime periods of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLRECYDS` | 792 | 779 | 185 | `UDXNFLRECYDS_ARISF26SEP271605MARVINHARRIS_14.5` | Resolves Yes if Marvin Harrison Jr. records above 14.5 receiving yards during the full duration of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLRUSHYDS` | 442 | 442 | 87 | `UDXNFLRUSHYDS_ARISF26SEP271605CHRISTIANMCC_109.5` | Resolves Yes if Christian McCaffrey records above 109.5 rushing yards during the full duration of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLREC` | 459 | 449 | 68 | `UDXNFLREC_ARISF26SEP271605MARVINHARRIS_0.5` | Resolves Yes if Marvin Harrison Jr. records above 0.5 receptions during the full duration of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLPASSYDS` | 220 | 220 | 55 | `UDXNFLPASSYDS_ARISF26SEP271605BROCKPURDY_149.5` | Resolves Yes if Brock Purdy records above 149.5 passing yards during the full duration of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLTD` | 329 | 292 | 43 | `UDXNFLTD_ARISF26SEP271605ARIZONACARDI_0.5` | Resolves Yes if Arizona Cardinals D/ST records above 0.5 touchdowns during the full duration of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLPASSTD` | 97 | 97 | 43 | `UDXNFLPASSTD_ARISF26SEP271605BROCKPURDY_0.5` | Resolves Yes if Brock Purdy records above 0.5 passing touchdowns during the full duration of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLTOTAL1Q` | 163 | 163 | 30 | `UDXNFLTOTAL1Q_ARISF26SEP271605_10.5` | Resolves Yes if there are above 10.5 points in the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLTOTAL1H` | 420 | 420 | 23 | `UDXNFLTOTAL1H_ARISF26SEP271605_10.5` | Resolves Yes if there are above 10.5 points in the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLGAMEWIN1Q` | 48 | 48 | 17 | `UDXNFLGAMEWIN1Q_ARISF26SEP271605_ARI` | Resolves Yes if the Arizona Cardinals score more points than their opponent during the first quarter of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLGAMEWIN1H` | 48 | 48 | 15 | `UDXNFLGAMEWIN1H_ARISF26SEP271605_ARI` | Resolves Yes if the Arizona Cardinals score more points than their opponent during the first half of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLSPREAD1H` | 336 | 336 | 12 | `UDXNFLSPREAD1H_ARISF26SEP271605_ARI0.5` | Resolves Yes if the Arizona Cardinals beat the San Francisco 49ers by at least 0.5 points in the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLSPREAD1Q` | 176 | 176 | 5 | `UDXNFLSPREAD1Q_ARISF26SEP271605_ARI10.5` | Resolves Yes if the Arizona Cardinals beat the San Francisco 49ers by at least 10.5 points in the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLRUSHATT` | 172 | 172 | 5 | `UDXNFLRUSHATT_ATLGB26SEP242015BIJANROBINSO_11.5` | Resolves Yes if Bijan Robinson records above 11.5 rushing attempts during the full duration of the National Football League game between the Atlanta Falcons and the Green Bay Packers originally scheduled for 8:15pm ET on September 24, 2026. |
| `UDXNFLRUSHRECYDS` | 72 | 72 | 3 | `UDXNFLRUSHRECYDS_ATLGB26SEP24BIJROBINS_123.5` | Resolves Yes if Bijan Robinson records above 123.5 rushing + receiving yards during the full duration of the National Football League game between the Atlanta Falcons and the Green Bay Packers originally scheduled for 8:15pm ET on September 24, 2026. |
| `UDXNFLPASSCOM` | 171 | 171 | 2 | `UDXNFLPASSCOM_ATLGB26SEP242015JORDANLOVE_13.5` | Resolves Yes if Jordan Love records above 13.5 passing completions during the full duration of the National Football League game between the Atlanta Falcons and the Green Bay Packers originally scheduled for 8:15pm ET on September 24, 2026. |
| `UDXNFLPASSATT` | 239 | 239 | 1 | `UDXNFLPASSATT_ATLGB26SEP242015JORDANLOVE_23.5` | Resolves Yes if Jordan Love records above 23.5 passing attempts during the full duration of the National Football League game between the Atlanta Falcons and the Green Bay Packers originally scheduled for 8:15pm ET on September 24, 2026. |
| `UDXNFLPASSRUSHYDS` | 378 | 378 | 0 | `UDXNFLPASSRUSHYDS_ATLGB26SEP24JORLOVE_149.5` | Resolves Yes if Jordan Love records above 149.5 passing + rushing yards during the full duration of the National Football League game between the Atlanta Falcons and the Green Bay Packers originally scheduled for 8:15pm ET on September 24, 2026. |
| `UDXNFLFIRSTTD` | 311 | 274 | 0 | `UDXNFLFIRSTTD_ARISF26SEP271605ARIZONACARDI_0.5` | Resolves Yes if Arizona Cardinals D/ST records above 0.5 first touchdown during the full duration of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLSPREAD2H` | 244 | 244 | 0 | `UDXNFLSPREAD2H_ARISF26SEP271605_ARI10.5` | Resolves Yes if the Arizona Cardinals beat the San Francisco 49ers by at least 10.5 points in the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLTOTAL2H` | 213 | 213 | 0 | `UDXNFLTOTAL2H_ARISF26SEP271605_10.5` | Resolves Yes if there are above 10.5 points in the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLSPREAD3Q` | 165 | 165 | 0 | `UDXNFLSPREAD3Q_ARISF26SEP271605_ARI10.5` | Resolves Yes if the Arizona Cardinals beat the San Francisco 49ers by at least 10.5 points in the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLSPREAD4Q` | 164 | 164 | 0 | `UDXNFLSPREAD4Q_ARISF26SEP271605_ARI10.5` | Resolves Yes if the Arizona Cardinals beat the San Francisco 49ers by at least 10.5 points in the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLTOTAL3Q` | 163 | 163 | 0 | `UDXNFLTOTAL3Q_ARISF26SEP271605_10.5` | Resolves Yes if there are above 10.5 points in the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLTOTAL4Q` | 162 | 162 | 0 | `UDXNFLTOTAL4Q_ARISF26SEP271605_10.5` | Resolves Yes if there are above 10.5 points in the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLSPREAD2Q` | 160 | 160 | 0 | `UDXNFLSPREAD2Q_ARISF26SEP271605_ARI10.5` | Resolves Yes if the Arizona Cardinals beat the San Francisco 49ers by at least 10.5 points in the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLTOTAL2Q` | 157 | 157 | 0 | `UDXNFLTOTAL2Q_ARISF26SEP271605_10.5` | Resolves Yes if there are above 10.5 points in the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLRECLNG` | 149 | 134 | 0 | `UDXNFLRECLNG_ATLGB26SEP242015BIJANROBINSO_14.5` | Resolves Yes if Bijan Robinson records above 14.5 longest reception yards during the full duration of the National Football League game between the Atlanta Falcons and the Green Bay Packers originally scheduled for 8:15pm ET on September 24, 2026. |
| `UDXNFLGAMEWIN2Q` | 48 | 48 | 0 | `UDXNFLGAMEWIN2Q_ARISF26SEP271605_ARI` | Resolves Yes if the Arizona Cardinals score more points than their opponent during the second quarter of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLGAMEWIN3Q` | 48 | 48 | 0 | `UDXNFLGAMEWIN3Q_ARISF26SEP271605_ARI` | Resolves Yes if the Arizona Cardinals score more points than their opponent during the third quarter of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLGAMEWIN4Q` | 48 | 48 | 0 | `UDXNFLGAMEWIN4Q_ARISF26SEP271605_ARI` | Resolves Yes if the Arizona Cardinals score more points than their opponent during the fourth quarter of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLGAMEWIN2H` | 45 | 45 | 0 | `UDXNFLGAMEWIN2H_ARISF26SEP271605_ARI` | Resolves Yes if the Arizona Cardinals score more points than their opponent during the second half and overtime of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLPASSINT` | 44 | 44 | 0 | `UDXNFLPASSINT_ATLGB26SEP242015JORDANLOVE_0.5` | Resolves Yes if Jordan Love records above 0.5 passing interceptions during the full duration of the National Football League game between the Atlanta Falcons and the Green Bay Packers originally scheduled for 8:15pm ET on September 24, 2026. |
| `UDXNFLRUSHLNG` | 41 | 39 | 0 | `UDXNFLRUSHLNG_ATLGB26SEP242015BIJANROBINSO_14.5` | Resolves Yes if Bijan Robinson records above 14.5 longest rush yards during the full duration of the National Football League game between the Atlanta Falcons and the Green Bay Packers originally scheduled for 8:15pm ET on September 24, 2026. |
| `UDXNFLPASSLNG` | 35 | 34 | 0 | `UDXNFLPASSLNG_ATLGB26SEP242015JORDANLOVE_29.5` | Resolves Yes if Jordan Love records above 29.5 longest passing completion yards during the full duration of the National Football League game between the Atlanta Falcons and the Green Bay Packers originally scheduled for 8:15pm ET on September 24, 2026. |
| `UDXNFLKICKPTS` | 26 | 22 | 0 | `UDXNFLKICKPTS_ATLGB26SEP24NICFOLK_12.5` | Resolves Yes if Nick Folk records above 12.5 kicking points during the full duration of the National Football League game between the Atlanta Falcons and the Green Bay Packers originally scheduled for 8:15pm ET on September 24, 2026. |
| `UDXNFLXPM` | 21 | 20 | 0 | `UDXNFLXPM_ATLGB26SEP242015NICKFOLK_0.5` | Resolves Yes if Nick Folk records above 0.5 extra points made during the full duration of the National Football League game between the Atlanta Falcons and the Green Bay Packers originally scheduled for 8:15pm ET on September 24, 2026. |
| `UDXNFLFGM` | 17 | 16 | 0 | `UDXNFLFGM_ATLGB26SEP242015NICKFOLK_0.5` | Resolves Yes if Nick Folk records above 0.5 field goals made during the full duration of the National Football League game between the Atlanta Falcons and the Green Bay Packers originally scheduled for 8:15pm ET on September 24, 2026. |
| `UDXNFLOVERTIME` | 16 | 16 | 0 | `UDXNFLOVERTIME_ARISF26SEP271605_OT` | Resolves Yes if any participating team records at least 1 kickoffs during overtime only of the National Football League game between the Arizona Cardinals and the San Francisco 49ers originally scheduled for 4:05pm ET on September 27, 2026. |
| `UDXNFLTEAMSALE` | 4 | 4 | 0 | `UDXNFLTEAMSALE_36JAN01_10B` | Will the next NFL team sell for above $10,000,000,000.00 before January 1, 2036? |
| `UDXNFLSACK` | 1 | 0 | 0 | `UDXNFLSACK_DETBUF26SEP172015BRADLEYCHUBB_1.25` | Resolves Yes if Bradley Chubb records above 1.25 sacks during the full duration of the National Football League game between the Detroit Lions and the Buffalo Bills originally scheduled for 8:15pm ET on September 17, 2026. |

### NCAAMFB

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXNCAAMFBGAMEWIN` | 240 | 240 | 3968 | `UDXNCAAMFBGAMEWIN_AAMUFAMU26SEP261900_AAMU` | Resolves Yes if Alabama A&M win the NCAA Football game between the Alabama A&M and the Florida A&M originally scheduled for 7:00pm ET on September 26, 2026. |
| `UDXNCAAMFBSPREAD` | 2488 | 2487 | 2029 | `UDXNCAAMFBSPREAD_AAMUFAMU26SEP261900_AAMU10.5` | Resolves Yes if Alabama A&M beat the Florida A&M by at least 10.5 points in the NCAA Football game between the Alabama A&M and the Florida A&M originally scheduled for 7:00pm ET on September 26, 2026. |
| `UDXNCAAMFBTOTAL` | 2133 | 2133 | 483 | `UDXNCAAMFBTOTAL_AAMUFAMU26SEP261900_31.5` | Resolves Yes if there are above 31.5 points in the NCAA Football game between the Alabama A&M and the Florida A&M originally scheduled for 7:00pm ET on September 26, 2026. |
| `UDXNCAAMFBTEAMTOTAL` | 3017 | 3017 | 14 | `UDXNCAAMFBTEAMTOTAL_AFANEV26SEP262230_A13.5` | Resolves Yes if the Air Force records above 13.5 points during the entire game, including regulation time and any officially designated overtime periods of the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBSPREAD1H` | 1243 | 1243 | 3 | `UDXNCAAMFBSPREAD1H_AFANEV26SEP262230_AFA10.5` | Resolves Yes if Air Force beat the Nevada by at least 10.5 points in the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBSPREAD2Q` | 198 | 198 | 1 | `UDXNCAAMFBSPREAD2Q_AFANEV26SEP262230_AFA1.5` | Resolves Yes if Air Force beat the Nevada by at least 1.5 points in the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBTOTAL1H` | 831 | 831 | 0 | `UDXNCAAMFBTOTAL1H_AFANEV26SEP262230_13.5` | Resolves Yes if there are above 13.5 points in the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBGAMEWIN1H` | 357 | 357 | 0 | `UDXNCAAMFBGAMEWIN1H_AAMUFAMU26SEP261900_AAMU` | Resolves Yes if Alabama A&M win the NCAA Football game between the Alabama A&M and the Florida A&M originally scheduled for 7:00pm ET on September 26, 2026. |
| `UDXNCAAMFBSPREAD2H` | 286 | 286 | 0 | `UDXNCAAMFBSPREAD2H_AFANEV26SEP262230_AFA2.5` | Resolves Yes if Air Force beat the Nevada by at least 2.5 points in the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBTOTAL2H` | 238 | 238 | 0 | `UDXNCAAMFBTOTAL2H_AFANEV26SEP262230_23.5` | Resolves Yes if there are above 23.5 points in the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBSPREAD1Q` | 218 | 218 | 0 | `UDXNCAAMFBSPREAD1Q_AFANEV26SEP262230_AFA1.5` | Resolves Yes if Air Force beat the Nevada by at least 1.5 points in the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBTOTAL1Q` | 216 | 216 | 0 | `UDXNCAAMFBTOTAL1Q_AFANEV26SEP262230_9.5` | Resolves Yes if there are above 9.5 points in the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBTOTAL2Q` | 195 | 195 | 0 | `UDXNCAAMFBTOTAL2Q_AFANEV26SEP262230_13.5` | Resolves Yes if there are above 13.5 points in the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBTOTAL3Q` | 190 | 190 | 0 | `UDXNCAAMFBTOTAL3Q_AFANEV26SEP262230_10.5` | Resolves Yes if there are above 10.5 points in the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBTOTAL4Q` | 187 | 187 | 0 | `UDXNCAAMFBTOTAL4Q_AFANEV26SEP262230_13.5` | Resolves Yes if there are above 13.5 points in the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBSPREAD3Q` | 186 | 186 | 0 | `UDXNCAAMFBSPREAD3Q_AFANEV26SEP262230_AFA1.5` | Resolves Yes if Air Force beat the Nevada by at least 1.5 points in the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBSPREAD4Q` | 178 | 178 | 0 | `UDXNCAAMFBSPREAD4Q_AFANEV26SEP262230_AFA1.5` | Resolves Yes if Air Force beat the Nevada by at least 1.5 points in the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBGAMEWIN2H` | 174 | 174 | 0 | `UDXNCAAMFBGAMEWIN2H_AFANEV26SEP262230_AFA` | Resolves Yes if Air Force win the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBOVERTIME` | 58 | 58 | 0 | `UDXNCAAMFBOVERTIME_AFANEV26SEP262230_OT` | Resolves Yes if any participating team records at least 1 kickoffs during overtime only of the NCAA Football game between the Air Force and the Nevada originally scheduled for 10:30pm ET on September 26, 2026. |
| `UDXNCAAMFBGAMEWIN1Q` | 33 | 33 | 0 | `UDXNCAAMFBGAMEWIN1Q_CLEMCAL26SEP252230_CAL` | Resolves Yes if California win the NCAA Football game between the Clemson and the California originally scheduled for 10:30pm ET on September 25, 2026. |
| `UDXNCAAMFBGAMEWIN2Q` | 33 | 33 | 0 | `UDXNCAAMFBGAMEWIN2Q_CLEMCAL26SEP252230_CAL` | Resolves Yes if California win the NCAA Football game between the Clemson and the California originally scheduled for 10:30pm ET on September 25, 2026. |
| `UDXNCAAMFBGAMEWIN3Q` | 33 | 33 | 0 | `UDXNCAAMFBGAMEWIN3Q_CLEMCAL26SEP252230_CAL` | Resolves Yes if California win the NCAA Football game between the Clemson and the California originally scheduled for 10:30pm ET on September 25, 2026. |
| `UDXNCAAMFBGAMEWIN4Q` | 33 | 33 | 0 | `UDXNCAAMFBGAMEWIN4Q_CLEMCAL26SEP252230_CAL` | Resolves Yes if California win the NCAA Football game between the Clemson and the California originally scheduled for 10:30pm ET on September 25, 2026. |

### WNBA

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXWNBAGAMEWIN` | 26 | 14 | 3837 | `UDXWNBAGAMEWIN_ATLNY26SEP232000_ATL` | Resolves Yes if the Atlanta Dream win the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBASPREAD` | 313 | 47 | 1305 | `UDXWNBASPREAD_ATLNY26SEP232000_ATL1.5` | Resolves Yes if the Atlanta Dream beat the New York Liberty by at least 1.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBATOTAL` | 337 | 51 | 1042 | `UDXWNBATOTAL_ATLNY26SEP232000_153.5` | Resolves Yes if there are above 153.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBAPTS` | 537 | 100 | 11 | `UDXWNBAPTS_ATLNY26SEP232000ALLISHAGRAY_14.5` | Resolves Yes if Allisha Gray records above 14.5 points during the entire game of the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBAREB` | 272 | 63 | 3 | `UDXWNBAREB_ATLNY26SEP232000ALLISHAGRAY_3.5` | Resolves Yes if Allisha Gray records above 3.5 total rebounds during the entire game of the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBATOTAL1H` | 68 | 9 | 2 | `UDXWNBATOTAL1H_ATLNY26SEP232000_86.5` | Resolves Yes if there are above 86.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBATOTAL1Q` | 56 | 9 | 1 | `UDXWNBATOTAL1Q_ATLNY26SEP232000_43.5` | Resolves Yes if there are above 43.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBA3PT` | 222 | 64 | 0 | `UDXWNBA3PT_ATLNY26SEP232000ALLISHAGRAY_0.5` | Resolves Yes if Allisha Gray records above 0.5 three-point field goals made during the entire game of the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBAAST` | 202 | 54 | 0 | `UDXWNBAAST_ATLNY26SEP232000ALLISHAGRAY_1.5` | Resolves Yes if Allisha Gray records above 1.5 assists during the entire game of the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBASPREAD1H` | 72 | 11 | 0 | `UDXWNBASPREAD1H_ATLNY26SEP232000_ATL0.5` | Resolves Yes if the Atlanta Dream beat the New York Liberty by above 0.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBASPREAD2H` | 63 | 15 | 0 | `UDXWNBASPREAD2H_ATLNY26SEP232000_ATL1.5` | Resolves Yes if the Atlanta Dream beat the New York Liberty by above 1.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBASPREAD2Q` | 60 | 9 | 0 | `UDXWNBASPREAD2Q_ATLNY26SEP232000_ATL0.5` | Resolves Yes if the Atlanta Dream beat the New York Liberty by above 0.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBASPREAD3Q` | 59 | 10 | 0 | `UDXWNBASPREAD3Q_ATLNY26SEP232000_ATL0.5` | Resolves Yes if the Atlanta Dream beat the New York Liberty by above 0.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBASPREAD4Q` | 59 | 9 | 0 | `UDXWNBASPREAD4Q_ATLNY26SEP232000_ATL0.5` | Resolves Yes if the Atlanta Dream beat the New York Liberty by above 0.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBASPREAD1Q` | 58 | 10 | 0 | `UDXWNBASPREAD1Q_ATLNY26SEP232000_ATL0.5` | Resolves Yes if the Atlanta Dream beat the New York Liberty by above 0.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBATOTAL2Q` | 57 | 8 | 0 | `UDXWNBATOTAL2Q_ATLNY26SEP232000_42.5` | Resolves Yes if there are above 42.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBATOTAL2H` | 56 | 14 | 0 | `UDXWNBATOTAL2H_ATLNY26SEP232000_76.5` | Resolves Yes if there are above 76.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBATOTAL3Q` | 56 | 9 | 0 | `UDXWNBATOTAL3Q_ATLNY26SEP232000_44.5` | Resolves Yes if there are above 44.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |
| `UDXWNBATOTAL4Q` | 56 | 8 | 0 | `UDXWNBATOTAL4Q_ATLNY26SEP232000_43.5` | Resolves Yes if there are above 43.5 points in the Women's National Basketball Association game between the Atlanta Dream and the New York Liberty originally scheduled for 8:00pm ET on September 23, 2026. |

### ATPCHL

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXATPCHLMATCHWIN` | 227 | 64 | 3105 | `UDXATPCHLMATCHWIN_ANDIVA26SEP240300_AANDREE` | Resolves Yes if Adrian Andreev wins the ATP Challenger match between Adrian Andreev and Ivan Ivanov originally scheduled for 3:00am ET on September 24, 2026. |

### WTA

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXWTAMATCHWIN` | 190 | 52 | 2860 | `UDXWTAMATCHWIN_BERKOS26SEP240330_EBERTEA` | Resolves Yes if Elena Ruxandra Bertea wins the WTA Tour match between Elena Ruxandra Bertea and Teodora Kostovic originally scheduled for 3:30am ET on September 24, 2026. |
| `UDXWTASPREAD` | 1291 | 120 | 0 | `UDXWTASPREAD_BIRMA26SEP232300_KBIRREL0.5` | Resolves Yes if Kimberly Birrell wins at least 0.5 more games than their opponent in the WTA Tour match between Kimberly Birrell and YeXin Ma originally scheduled for 11:00pm ET on September 23, 2026. |
| `UDXWTATOTAL` | 1166 | 114 | 0 | `UDXWTATOTAL_BIRMA26SEP232300_15.5` | Resolves Yes if there are above 15.5 games in the WTA Tour match between Kimberly Birrell and YeXin Ma originally scheduled for 11:00pm ET on September 23, 2026. |

### ATP

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXATPMATCHWIN` | 100 | 44 | 1298 | `UDXATPMATCHWIN_ATMFAR26SEP230000_JFARIA` | Resolves Yes if Jaime Faria wins the ATP Tour match between Terence Atmane and Jaime Faria originally scheduled for 12:00am ET on September 23, 2026. |
| `UDXATPTOTAL` | 550 | 176 | 6 | `UDXATPTOTAL_ATMFAR26SEP230000_21.5` | Resolves Yes if there are above 21.5 games in the ATP Tour match between Terence Atmane and Jaime Faria originally scheduled for 12:00am ET on September 23, 2026. |
| `UDXATPSPREAD` | 447 | 165 | 3 | `UDXATPSPREAD_ATMFAR26SEP230000_JFARIA1.5` | Resolves Yes if Jaime Faria wins at least 1.5 more games than their opponent in the ATP Tour match between Terence Atmane and Jaime Faria originally scheduled for 12:00am ET on September 23, 2026. |

### UFC

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXUFCFIGHTWIN` | 34 | 24 | 405 | `UDXUFCFIGHTWIN_ALACAS26SEP261720_ALATENG` | Resolves Yes if Alatengheili wins the Ultimate Fighting Championship fight between Alatengheili and John Castaneda originally scheduled for 5:20pm ET on September 26, 2026 during the entire fight. |
| `UDXUFCFIGHTWINROUND` | 82 | 52 | 0 | `UDXUFCFIGHTWINROUND_BARJR26SEP262120_RBARCELR1` | Resolves Yes if Raoni Barcelos wins the Ultimate Fighting Championship fight between Raoni Barcelos and Raul Rosas Jr. originally scheduled for 9:20pm ET on September 26, 2026 during Round 1. |
| `UDXUFCMOV` | 78 | 48 | 0 | `UDXUFCMOV_BARJR26SEP262120_RBARCELDEC` | Resolves Yes if Raoni Barcelos wins the Ultimate Fighting Championship fight between Raoni Barcelos and Raul Rosas Jr. originally scheduled for 9:20pm ET on September 26, 2026 by decision. |
| `UDXUFCEXACTTOTAL` | 41 | 26 | 0 | `UDXUFCEXACTTOTAL_BARJR26SEP262120_R1` | Resolves Yes if the Ultimate Fighting Championship fight between Raoni Barcelos and Raul Rosas Jr. originally scheduled for 9:20pm ET on September 26, 2026 concludes during Round 1. |
| `UDXUFCMOVFINISH` | 39 | 24 | 0 | `UDXUFCMOVFINISH_BARJR26SEP262120_DEC` | Resolves Yes if either fighter wins the Ultimate Fighting Championship fight between Raoni Barcelos and Raul Rosas Jr. originally scheduled for 9:20pm ET on September 26, 2026 by decision. |
| `UDXUFCTOTAL` | 28 | 18 | 0 | `UDXUFCTOTAL_BARJR26SEP262120_1.5` | Resolves Yes if the Ultimate Fighting Championship fight between Raoni Barcelos and Raul Rosas Jr. originally scheduled for 9:20pm ET on September 26, 2026 concludes during Rounds 2 through 5. |
| `UDXUFCDISTANCE` | 13 | 8 | 0 | `UDXUFCDISTANCE_BARJR26SEP262120_DIST` | Resolves Yes if the Ultimate Fighting Championship fight between Raoni Barcelos and Raul Rosas Jr. originally scheduled for 9:20pm ET on September 26, 2026 concludes during all scheduled rounds. |

### MLS

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXMLSGAMEWIN` | 48 | 48 | 9 | `UDXMLSGAMEWIN_CHICLT26SEP261930_CHI` | Resolves Yes if Chicago Fire FC score more goals than their opponent during regulation time of the Major League Soccer game between the Chicago Fire FC and the Charlotte FC originally scheduled for 7:30pm ET on September 26, 2026. |
| `UDXMLSTOTAL` | 148 | 141 | 7 | `UDXMLSTOTAL_CHICLT26SEP261930_0.5` | Resolves Yes if there are above 0.5 goals during regulation time of the Major League Soccer game between the Chicago Fire FC and the Charlotte FC originally scheduled for 7:30pm ET on September 26, 2026. |
| `UDXMLSSPREAD` | 109 | 105 | 1 | `UDXMLSSPREAD_CHICLT26SEP261930_CHI1.5` | Resolves Yes if Chicago Fire FC beat the Charlotte FC by at least 1.5 goals during regulation time of the Major League Soccer game between the Chicago Fire FC and the Charlotte FC originally scheduled for 7:30pm ET on September 26, 2026. |
| `UDXMLSTOTAL1H` | 83 | 80 | 0 | `UDXMLSTOTAL1H_CHICLT26SEP261930_0.5` | Resolves Yes if there are above 0.5 goals during the first half of the Major League Soccer game between the Chicago Fire FC and the Charlotte FC originally scheduled for 7:30pm ET on September 26, 2026. |
| `UDXMLSGAMEWIN1H` | 51 | 48 | 0 | `UDXMLSGAMEWIN1H_CHICLT26SEP261930_CHI` | Resolves Yes if Chicago Fire FC score more goals than their opponent during the first half of the Major League Soccer game between the Chicago Fire FC and the Charlotte FC originally scheduled for 7:30pm ET on September 26, 2026. |
| `UDXMLSBTTS` | 17 | 16 | 0 | `UDXMLSBTTS_CHICLT26SEP261930_BTTS` | Resolves Yes if both participating teams record at least 1 goals during regulation time of the Major League Soccer game between the Chicago Fire FC and the Charlotte FC originally scheduled for 7:30pm ET on September 26, 2026. |
| `UDXMLSSPREAD1H` | 15 | 13 | 0 | `UDXMLSSPREAD1H_CHICLT26SEP261930_CLT0.5` | Resolves Yes if Charlotte FC beat the Chicago Fire FC by at least 0.5 goals during the first half of the Major League Soccer game between the Chicago Fire FC and the Charlotte FC originally scheduled for 7:30pm ET on September 26, 2026. |

### LIGAMX

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXLIGAMXGAMEWIN` | 27 | 27 | 3 | `UDXLIGAMXGAMEWIN_ASLPUM26SEP271400_ASL` | Resolves Yes if Atlético de San Luis win the Mexican Liga MX game between the Atlético de San Luis and the Pumas de la Universidad Nacional Autonoma de Mexico originally scheduled for 2:00pm ET on September 27, 2026. |
| `UDXLIGAMXTOTAL` | 60 | 54 | 0 | `UDXLIGAMXTOTAL_ASLPUM26SEP271400_0.5` | Resolves Yes if there are above 0.5 goals in the Mexican Liga MX game between the Atlético de San Luis and the Pumas de la Universidad Nacional Autonoma de Mexico originally scheduled for 2:00pm ET on September 27, 2026. |
| `UDXLIGAMXTOTAL1H` | 45 | 45 | 0 | `UDXLIGAMXTOTAL1H_ASLPUM26SEP271400_0.5` | Resolves Yes if there are above 0.5 goals in the Mexican Liga MX game between the Atlético de San Luis and the Pumas de la Universidad Nacional Autonoma de Mexico originally scheduled for 2:00pm ET on September 27, 2026. |
| `UDXLIGAMXSPREAD` | 40 | 36 | 0 | `UDXLIGAMXSPREAD_ASLPUM26SEP271400_ASL1.5` | Resolves Yes if Atlético de San Luis beat the Pumas de la Universidad Nacional Autonoma de Mexico by at least 1.5 goals in the Mexican Liga MX game between the Atlético de San Luis and the Pumas de la Universidad Nacional Autonoma de Mexico originally scheduled for 2:00pm ET on September 27, 2026. |
| `UDXLIGAMXGAMEWIN1H` | 27 | 27 | 0 | `UDXLIGAMXGAMEWIN1H_ASLPUM26SEP271400_ASL` | Resolves Yes if Atlético de San Luis win the Mexican Liga MX game between the Atlético de San Luis and the Pumas de la Universidad Nacional Autonoma de Mexico originally scheduled for 2:00pm ET on September 27, 2026. |
| `UDXLIGAMXBTTS` | 9 | 9 | 0 | `UDXLIGAMXBTTS_ASLPUM26SEP271400_BTTS` | Resolves Yes if both participating teams each record at least 1 goals during regulation time of the Mexican Liga MX game between the Atlético de San Luis and the Pumas de la Universidad Nacional Autonoma de Mexico originally scheduled for 2:00pm ET on September 27, 2026. |
| `UDXLIGAMXSPREAD1H` | 8 | 8 | 0 | `UDXLIGAMXSPREAD1H_ASLPUM26SEP271400_PUM0.5` | Resolves Yes if Pumas de la Universidad Nacional Autonoma de Mexico beat the Atlético de San Luis by at least 0.5 goals in the Mexican Liga MX game between the Atlético de San Luis and the Pumas de la Universidad Nacional Autonoma de Mexico originally scheduled for 2:00pm ET on September 27, 2026. |

### ITFMEN

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXITFMENMATCHWIN` | 308 | 30 | 0 | `UDXITFMENMATCHWIN_ALVDAR26SEP231100_PALVARA` | Resolves Yes if Patricio Alvarado wins the International Tennis Federation match between Patricio Alvarado and Sean Daryabeigi originally scheduled for 11:00am ET on September 23, 2026. |

### ITFWOMEN

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXITFWOMENMATCHWIN` | 242 | 38 | 0 | `UDXITFWOMENMATCHWIN_ALAKOI26SEP231300_EKOIKE` | Resolves Yes if Ena Koike wins the International Tennis Federation match between Lucciana Perez Alarcon and Ena Koike originally scheduled for 1:00pm ET on September 23, 2026. |

### NBA

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXNBAEXPTEAM` | 2 | 2 | 0 | `UDXNBAEXPTEAM_28JAN01_LASVEGAS` | Will Las Vegas receive an NBA expansion team before January 1, 2028? |

### LALIGA (one expired row seen)

| Family | Total | Open | Parlay legs | Example ticker | Venue sentence |
| --- | ---: | ---: | ---: | --- | --- |
| `UDXLALIGASPREAD` | 1 | 0 | 0 | `UDXLALIGASPREAD_ATHLEV26SEP161530_LEV1.5` | Resolves Yes if Levante UD beat the Athletic Club Bilbao by at least 1.5 goals in the Spanish La Liga game between the Athletic Club Bilbao and the Levante UD originally scheduled for 3:30pm ET on September 16, 2026. |

## Appendix B — team code aliases, learned from GAMEWIN sentences

NCAAF (237 codes) is in `docs/underdog/team_aliases_2026-09-23.csv` only; the other leagues are inline. The CSV also gives the ticker each code was learned from.

### MLB — 30 codes, venue league name "Major League Baseball"

| Code | Venue name |
| --- | --- |
| `ARI` | Arizona Diamondbacks |
| `ATL` | Atlanta Braves |
| `BAL` | Baltimore Orioles |
| `BOS` | Boston Red Sox |
| `CHC` | Chicago Cubs |
| `CIN` | Cincinnati Reds |
| `CLE` | Cleveland Guardians |
| `COL` | Colorado Rockies |
| `CWS` | Chicago White Sox |
| `DET` | Detroit Tigers |
| `HOU` | Houston Astros |
| `KAN` | Kansas City Royals |
| `LAA` | Los Angeles Angels |
| `LAD` | Los Angeles Dodgers |
| `MIA` | Miami Marlins |
| `MIL` | Milwaukee Brewers |
| `MIN` | Minnesota Twins |
| `NYM` | New York Mets |
| `NYY` | New York Yankees |
| `OAK` | Oakland Athletics |
| `PHI` | Philadelphia Phillies |
| `PIT` | Pittsburgh Pirates |
| `SD` | San Diego Padres |
| `SEA` | Seattle Mariners |
| `SF` | San Francisco Giants |
| `STL` | St. Louis Cardinals |
| `TB` | Tampa Bay Rays |
| `TEX` | Texas Rangers |
| `TOR` | Toronto Blue Jays |
| `WAS` | Washington Nationals |

### NFL — 32 codes, venue league name "National Football League"

| Code | Venue name |
| --- | --- |
| `ARI` | Arizona Cardinals |
| `ATL` | Atlanta Falcons |
| `BAL` | Baltimore Ravens |
| `BUF` | Buffalo Bills |
| `CAR` | Carolina Panthers |
| `CHI` | Chicago Bears |
| `CIN` | Cincinnati Bengals |
| `CLE` | Cleveland Browns |
| `DAL` | Dallas Cowboys |
| `DEN` | Denver Broncos |
| `DET` | Detroit Lions |
| `GB` | Green Bay Packers |
| `HOU` | Houston Texans |
| `IND` | Indianapolis Colts |
| `JAX` | Jacksonville Jaguars |
| `KC` | Kansas City Chiefs |
| `LAC` | Los Angeles Chargers |
| `LAR` | Los Angeles Rams |
| `LV` | Las Vegas Raiders |
| `MIA` | Miami Dolphins |
| `MIN` | Minnesota Vikings |
| `NE` | New England Patriots |
| `NO` | New Orleans Saints |
| `NYG` | New York Giants |
| `NYJ` | New York Jets |
| `PHI` | Philadelphia Eagles |
| `PIT` | Pittsburgh Steelers |
| `SEA` | Seattle Seahawks |
| `SF` | San Francisco 49ers |
| `TB` | Tampa Bay Buccaneers |
| `TEN` | Tennessee Titans |
| `WSH` | Washington Commanders |

### WNBA — 15 codes, venue league name "Women's National Basketball Association"

| Code | Venue name |
| --- | --- |
| `ATL` | Atlanta Dream |
| `CHI` | Chicago Sky |
| `CONN` | Connecticut Sun |
| `DAL` | Dallas Wings |
| `GSV` | Golden State Valkyries |
| `IND` | Indiana Fever |
| `LA` | Los Angeles Sparks |
| `LV` | Las Vegas Aces |
| `MIN` | Minnesota Lynx |
| `NY` | New York Liberty |
| `PHX` | Phoenix Mercury |
| `POR` | Portland Fire |
| `SEA` | Seattle Storm |
| `TOR` | Toronto Tempo |
| `WSH` | Washington Mystics |

### MLS — 30 codes, venue league name "Major League Soccer"

| Code | Venue name |
| --- | --- |
| `ATL` | Atlanta United FC |
| `ATX` | Austin FC |
| `CHI` | Chicago Fire FC |
| `CIN` | FC Cincinnati |
| `CLB` | Columbus Crew |
| `CLT` | Charlotte FC |
| `COL` | Colorado Rapids |
| `DAL` | FC Dallas |
| `DC` | DC United |
| `HOU` | Houston Dynamo FC |
| `LA` | LA Galaxy |
| `LAF` | Los Angeles FC |
| `MIA` | Club Internacional de Fútbol Miami |
| `MIN` | Minnesota United FC |
| `MTL` | Club de Foot Montréal |
| `NE` | New England Revolution |
| `NSH` | Nashville SC |
| `NYC` | New York City Football Club |
| `NYR` | New York Red Bulls |
| `ORL` | Orlando City SC |
| `PHI` | Philadelphia Union |
| `POR` | Portland Timbers |
| `RSL` | Real Salt Lake |
| `SDG` | San Diego FC |
| `SEA` | Seattle Sounders FC |
| `SJ` | San Jose Earthquakes |
| `SKC` | Sporting Kansas City |
| `STL` | St. Louis City SC |
| `TOR` | Toronto FC |
| `VAN` | Vancouver Whitecaps FC |

### LIGAMX — 18 codes, venue league name "Mexican Liga MX"

| Code | Venue name |
| --- | --- |
| `ASL` | Atlético de San Luis |
| `ATL` | Atlante FC |
| `ATS` | Atlas FC |
| `CAZ` | CF Cruz Azul |
| `CDG` | CD Guadalajara |
| `CFA` | Club de Fútbol América |
| `CSL` | Club Santos Laguna |
| `CTJ` | Club Tijuana Xoloitzcuintles de Caliente |
| `FCJ` | FC Juárez |
| `LEO` | Club León |
| `MTY` | CF Monterrey |
| `NCX` | Club Necaxa |
| `PAC` | CF Pachuca |
| `PUE` | Club Puebla |
| `PUM` | Pumas de la Universidad Nacional Autonoma de Mexico |
| `QRO` | Querétaro FC |
| `TIG` | Club Tigres de la Universidad Autónoma de Nuevo León |
| `TOL` | Deportivo Toluca FC |

