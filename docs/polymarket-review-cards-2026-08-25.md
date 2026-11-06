# Polymarket Path 2 Review card payloads (2026-08-25)

> Historical note. Tip/console steps here are retired; see CLAUDE.md.

#
# Submit via mapping console (test first):
#   POST https://mapping.mm-test.whiteswandata.com/api/entry/league/submit
#   or Entry → League form / batch cart
#
# Approve is human-only. After tip_leagues soccer-poly fix deploys, tip-only
# Path 2 leagues parse with soccer_market_rules.
#
# Card A1 — germany_bundesliga: bul → bun (copy all exchanges)

## A1 germany_bundesliga (update)

```json
{
  "league": "germany_bundesliga",
  "sport": "soccer",
  "optic_league_id": "germany_-_bundesliga",
  "fixture_source": "api",
  "acknowledge_shadow": true,
  "note": "2026-08-25: bridge live prefix is bun (Bundesliga). tip carried bul (Bulgaria Parva Liga). Evidence: bun~8k RFQ occ actionable wrong_prefix; Optic germany_-_bundesliga books fixtures.",
  "exchanges": [
    {
      "sportsbook": "optic",
      "enabled": true,
      "parser_profile": "optic_standard_v1",
      "source_league_id": "germany_-_bundesliga"
    },
    {
      "sportsbook": "kalshi",
      "enabled": true,
      "parser_profile": "kalshi_generic_v1",
      "settings": {
        "prefix": "KXBUNDESLIGA",
        "ticker_home_first": true,
        "line_offset": 0.5
      }
    },
    {
      "sportsbook": "polymarket",
      "enabled": true,
      "parser_profile": "poly_generic_v1",
      "source_league_id": "germany_-_bundesliga",
      "settings": {
        "slug_prefix": "bun",
        "optic_league_id": "germany_-_bundesliga",
        "question_style": "mlb_suffix"
      }
    },
    {
      "sportsbook": "crypto.com",
      "enabled": true,
      "parser_profile": "crypto_generic_v1",
      "source_league_id": "DEB",
      "settings": {
        "league": "DEB",
        "sport_grouping": "SOCCER",
        "period_type": "90 Minutes and Stoppage Time",
        "game_prop_period_type": "90 Minutes and Stoppage Time",
        "game_prop_accept_round_periods": false
      }
    }
  ]
}
```

## A2 efl_cup — enable Polymarket slug_prefix efl

```json
{
  "league": "efl_cup",
  "sport": "soccer",
  "optic_league_id": "england_-_efl_cup",
  "fixture_source": "api",
  "acknowledge_shadow": true,
  "note": "2026-08-25: bridge prefix efl is EFL Cup (Birmingham/Nottingham Forest/Leeds). elc/el1/el2 are Championship/L1/L2. Census+RFQ: ~152k actionable path2_off occ. Optic england_-_efl_cup live.",
  "exchanges": [
    {
      "sportsbook": "optic",
      "enabled": true,
      "parser_profile": "optic_standard_v1",
      "source_league_id": "england_-_efl_cup"
    },
    {
      "sportsbook": "kalshi",
      "enabled": true,
      "parser_profile": "kalshi_generic_v1",
      "settings": {
        "prefix": "KXEFLCUP",
        "ticker_home_first": true,
        "line_offset": 0.5
      }
    },
    {
      "sportsbook": "crypto.com",
      "enabled": true,
      "parser_profile": "crypto_generic_v1",
      "source_league_id": "EFLC",
      "settings": {
        "league": "EFLC",
        "sport_grouping": "SOCCER",
        "period_type": "90 Minutes and Stoppage Time",
        "game_prop_period_type": "90 Minutes and Stoppage Time",
        "game_prop_accept_round_periods": false
      }
    },
    {
      "sportsbook": "polymarket",
      "enabled": true,
      "parser_profile": "poly_generic_v1",
      "source_league_id": "england_-_efl_cup",
      "settings": {
        "slug_prefix": "efl",
        "optic_league_id": "england_-_efl_cup",
        "question_style": "mlb_suffix"
      }
    }
  ]
}
```

## Card B — korea_k1 diagnosis (NOT a new-league card)

`kor` is already on the tip (`slug_prefix=kor`, `fixture_source=bq`, horizon 1440).
Baseline classifies ~71k occ as **actionable game-line gap** (Path 2 on + Optic
fixture name match) — meaning clobs are not being published. Investigate:

1. BQ-optic pipeline tick for `korea_k1` / `BQ_OPTIC_LEAGUES`
2. `dropped_no_optic` in mapper logs (Optic priced moneyline only?)
3. Alias / name containment failures the census SQL does not catch
4. Whether `market_mapping` has any recent Polymarket rows for league=`korea_k1`

Do **not** re-propose the league unless tip settings are wrong.

## Card C — England pyramid (batch leagues)

| league | optic_league_id | slug_prefix | clone_from |
|--------|-----------------|-------------|------------|
| england_championship | england_-_championship | elc | epl |
| england_league_1 | england_-_league_1 | el1 | epl |
| england_league_2 | england_-_league_2 | el2 | epl |
| england_national_league | england_-_national_league | enl | epl |
| england_fa_cup | england_-_fa_cup | efa | epl |

Each new league: optic + polymarket (`poly_generic_v1`, settings slug_prefix),
`clone_market_rules_from: epl`, `fixture_source: api` (or `bq` if API empty).

Template (replace LEAGUE / OPTIC / PREFIX):

```json
{
  "league": "england_championship",
  "sport": "soccer",
  "optic_league_id": "england_-_championship",
  "fixture_source": "api",
  "clone_market_rules_from": "epl",
  "acknowledge_shadow": true,
  "note": "2026-08-25 census: elc → england_-_championship; bridge Burnley v Middlesbrough.",
  "exchanges": [
    {
      "sportsbook": "optic",
      "enabled": true,
      "parser_profile": "optic_standard_v1",
      "source_league_id": "england_-_championship"
    },
    {
      "sportsbook": "polymarket",
      "enabled": true,
      "parser_profile": "poly_generic_v1",
      "source_league_id": "england_-_championship",
      "settings": {
        "slug_prefix": "elc",
        "optic_league_id": "england_-_championship",
        "question_style": "mlb_suffix"
      }
    }
  ]
}
```

## Cards D / E — Europe + Asia/Americas/MEA

Same template. Skip leagues already on tip (canpl, etc.).

| league | optic | prefix |
|--------|-------|--------|
| spain_la_liga_2 | spain_-_la_liga_2 | es2 |
| france_ligue_2 | france_-_ligue_2 | fr2 |
| italy_serie_b | italy_-_serie_b | itsb |
| germany_bundesliga_2 | germany_-_bundesliga_2 | bl2 |
| netherlands_eredivisie | netherlands_-_eredivisie | ere |
| belgium_jupiler_pro_league | belgium_-_jupiler_pro_league | bel1 |
| switzerland_super_league | switzerland_-_super_league | sui |
| scotland_premiership | scotland_-_premiership | scop |
| italy_coppa_italia | italy_-_coppa_italia | itc |
| austria_ofb_cup | austria_-_ofb_cup | atc |
| japan_j1_league | japan_-_j1_league | jap |
| japan_j2_league | japan_-_j2_league | ja2 |
| uruguay_primera_division | uruguay_-_primera_division | uru1 |
| israel_premier_league | israel_-_premier_league | isr |
| qatar_stars_league | qatar_-_stars_league | qat1 |

`canpl` already wired — skip.

## Cards F / G — esports + cricket

**needs_code gate first.** Tip-only soccer poly now attaches `soccer_market_rules`.
Esports/cricket tip-only still has no sport factory — either:

1. Add Python modules (valorant/mlbb/ow/hok/cricket_*) with
   `esports_market_rules` / cricket rules, then tip pin — **deploy required**, or
2. Extend `tip_leagues` for esports profiles — **deploy required**.

Valorant `round-handicap` and cricket `completed-match` shapes: drop the shape
rather than inventing a recognizer today. Moneyline / map handicap / total maps
reuse `esports_market_rules` when a Python module exists.

For today: land soccer cards A–E; F/G recorded as needs_code pending deploy of
tip esports factory or league modules.
