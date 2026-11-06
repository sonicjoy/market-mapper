---
name: add-team-alias
description: >-
  Add or fix a team / player / fighter identity binding the code-owned way:
  edit the venue's code alias or id table under mappers/, add a test, run
  pytest, open an MR and read the regression gate delta. Use for "code X is
  unmapped", a venue name that does not reach its Optic competitor, an id
  collision, or "bind A to B". Never a tip pin, console card or Mapper Chat.
---

# Bind a team / player / fighter (code-owned)

Policy: `CLAUDE.md`. An alias is a line of Python in the table that owns
that venue, plus a test. It is not a tip `entity_alias`, a console pin or
a Mapper Chat stage.

## 1. Prefer a typed id over a name

Check first whether the venue already gives identity in a typed field. If
it does, the fix is in the venue matcher, not an alias:

- Kalshi: milestone Optic fixture / competitor ids and `custom_strike`
  (`fetch/kalshi.py`, `mappers/exchanges/kalshi.py`). There are no Kalshi
  team-code aliases any more.
- Novig: returns Optic's own fixture / team / player ids
  (`mappers/exchanges/novig.py`, `docs/adding-novig.md`).
- Polymarket US: gateway `marketSides[].team` (`id`, `league`,
  `abbreviation`) and `sportsMarketType` (`fetch/polymarket_usa_gateway.py`,
  `mappers/exchanges/polymarket_usa_sides.py`).
- crypto.com: catalogue `EXTERNAL_HOME_ID` / `EXTERNAL_AWAY_ID` from
  `processed_upstream_us.crypto_security_def`.

Never split, regex or suffix-match a ticker, slug or symbol to get a side.

## 2. Pick the table

| Venue / shape | Table | Read by | Test |
|---|---|---|---|
| DKEX team name → Optic competitor id | `OPTIC_IDS_BY_DKEX_NAME` in `mappers/exchanges/dkex_names.py` | `dkex_pass.py` | `tests/mappers/test_dkex_name_fits.py`, `test_dkex_pass.py` |
| DKEX player name → Optic player id | `OPTIC_PLAYER_IDS_BY_DKEX_NAME` (same file) | `dkex_players.py` | `tests/mappers/test_dkex_pass.py` |
| SX Bet name → Optic competitor id | `OPTIC_IDS_BY_SX_NAME` in `mappers/exchanges/sxbet_names.py` | `sxbet_pass.py` | `tests/mappers/test_sxbet_pass.py` |
| crypto.com team id → canonical | `CRYPTO_TEAM_IDS` in `mappers/vocab/crypto_team_ids.py` | `mappers/pipeline.py` `_with_code_crypto_team_ids` | `tests/mappers/test_crypto_team_ids.py` |
| Polymarket tennis player name | `TENNIS_TEAM_NAME_ALIASES` in `mappers/vocab/tennis_aliases.py` | `mappers/profiles/tennis.py` | `tests/mappers/test_itf.py` |
| Polymarket football / basketball / UFC name | `FOOTBALL_` / `BASKETBALL_` / `UFC_POLY_TEAM_NAME_ALIASES` in `mappers/vocab/{football,basketball,combat}_markets.py` | `mappers/profiles/{football,basketball,combat}.py` | `tests/mappers/test_cfl.py` (football); add one for the others |

Prefer an Optic id table (DKEX / SX style) over a name → name table: an id
cannot drift onto another competitor.

If no table fits the venue, add one in the venue's `mappers/exchanges/`
module or `mappers/vocab/*_aliases.py`, wire it where the venue matches,
and test it. Do not route it through `mappers/seed/sot.py`.

## 3. Evidence before the line

Missing beats wrong. Add an entry only when:

- the venue event and the Optic fixture are the same game (date ±1 day,
  both sides agree), and
- the binding is unique: one Optic candidate, no surname-only or
  one-token person label, no club short that also fits another club.

Write the evidence in a comment on the entry (date measured, Optic fixture
or competitor id). Do not bind market selections as names: Yes/No,
Over/Under, exact score, `to score` markets, handicap crumbs
(`Name (-1.5)`), per-map / per-game winners.

Never loosen `names_close` / `names_fit` (`mappers/canonical_codes.py`) to
make a pair fit.

## 4. Ship

```
- [ ] Typed-id check (step 1) — alias really needed
- [ ] Entry added with evidence comment
- [ ] Test next to it (binds the pair; a near-miss stays unbound)
- [ ] GCP_PROJECT=rs-marketmaking .venv/bin/pytest -q
- [ ] MR; read the regression:mapping-gate row delta (removed rows need
      a waiver in regression/waivers.toml)
```

## Legacy (do not use)

The tip still carries `mapping_entities` aliases that `mappers/seed/sot.py`
loads, and `CRYPTO_TEAM_IDS` today only fills ids the tip lacks (the tip
wins a conflict and the conflict is printed).
To replace a wrong tip crypto alias, add the id to
`CRYPTO_TEAM_ID_OVERRIDES` (same file), which beats the tip when its key
is known that run. That is migration debt. When
a tip alias is wrong, move the correct binding into code; do not edit the
tip, `tests/fixtures/sot/tip.json`, or run any `scripts/submit_*` /
`scripts/propose_*` script.
