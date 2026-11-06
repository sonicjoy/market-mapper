---
name: add-new-league
description: >-
  Wire a league onto a venue the code-owned way: venue league tables and
  market vocab in Python under mappers/, a test, pytest, an MR, and the
  regression gate. Covers DKEX, SX Bet, Underdog, Novig, Kalshi and the
  venues whose league ids still sit on the legacy tip. Use for "map league X
  on venue Y", a new venue league id, or a new sport shape. Never a tip
  mapping_league row or a console proposal.
---

# Wire a league (code-owned)

Policy: `CLAUDE.md`. A league change is code plus a test, shipped by MR and
checked by the `regression:mapping-gate` job.

## Step 0 — is the league in the run set?

The map run set is still built from enabled tip `mapping_leagues` rows
(`mappers/run.py` `LEAGUES = load_tip_leagues()`,
`mappers/seed/tip_leagues.py` `resolve_run_leagues`). There is no
code-owned league list yet.

- League already in the run set (it has a slug in
  `tests/fixtures/sot/tip.json` and in prod `market_mapping`): go on.
- League not in the run set: stop. Adding it needs a code-owned league
  registry that does not exist yet. Do not add a tip row, do not run
  `scripts/submit_*`. Raise it with the owner.

## Step 1 — evidence

Confirm every venue ↔ Optic pairing against live data before writing it:
live fixture counts on both sides, named fixtures that match by id or by
kickoff + both team names. Put the date and evidence in a comment on the
table entry. Leaving a venue unwired is fine when it has no live book for
the league; say so in the MR.

## Step 2 — the venue table

| Venue | What decides the league | Test |
|---|---|---|
| DKEX | `VENUE_TOKEN_BY_SLUG` (+ `LEAGUE_TOKENS` for display `subTopic`s) in `mappers/exchanges/dkex_leagues.py`, applied by `with_code_dkex` | `tests/mappers/test_tip_leagues.py` |
| SX Bet | `SLUG_BY_LEAGUE_ID` (SX `leagueId` → slug) in `mappers/exchanges/sxbet_leagues.py`, applied by `with_code_sxbet` | `tests/mappers/test_sxbet.py` |
| Underdog | `UNDERDOG_LEAGUE_SLUGS` in `mappers/vocab/underdog_markets.py`, applied by `with_code_underdog` | `tests/mappers/test_underdog_code_coverage.py` |
| Novig | `NOVIG_LEAGUE_NAMES` (slug → Novig `event.league`) in `mappers/vocab/novig_markets.py`, applied by `with_code_novig` | `tests/mappers/test_novig.py` |
| Kalshi | Nothing per league. Every league maps Kalshi by sport; market type comes from Kalshi's typed scope in `mappers/vocab/kalshi_scopes.py` | `tests/mappers/test_kalshi_scope_typing.py` |

The `with_code_*` functions live in `mappers/seed/tip_factories.py` and run
for every league in `_build_run_set` (`mappers/seed/tip_leagues.py`).

Polymarket, Polymarket US, ProphetX and crypto.com still take their league
id / inner code / tournament id from the tip league row's exchange settings
(`build_tip_league` / `apply_tip_exchange_settings` in
`mappers/seed/tip_factories.py`). That is migration debt. To wire one of
these, add a code-owned table following the DKEX / SX pattern (table in the
venue module, a `with_code_<venue>` step, a test). Do not add a tip
exchange row.

## Step 3 — market types

Market vocab is per sport, not per league:

- Vocab: `mappers/vocab/<sport>_markets.py`, venue vocab in
  `mappers/vocab/<venue>_markets.py`, canonical types in
  `mappers/market_types.py`.
- Parser profiles (sport × venue grammar): `mappers/profiles/<sport>.py`,
  registered in `PROFILES` (`mappers/profiles/registry.py`).
- Code-seeded market rules: `mappers/seed/*_rules.py`.

A new shape (new sport, new prop family) means a vocab or profile change
with a test under `tests/mappers/`. Never derive a market type or line from
a ticker, slug or symbol; use the venue's typed field (Kalshi
`competition_scope` / `floor_strike` / `strike_type`, Polymarket US
`sportsMarketType`).

## Step 4 — ship

```
- [ ] Step 0: league is in the run set (else stop and raise)
- [ ] Every wired venue live-confirmed; evidence comment on the entry
- [ ] Venue table entry + vocab / profile change if needed
- [ ] Test next to it
- [ ] GCP_PROJECT=rs-marketmaking .venv/bin/pytest -q
- [ ] Optional local replay: python -m regression.live_gate --candidate HEAD
      --baseline origin/main --snapshots 0 --snapshot <tick> --league <slug>
      --out /tmp/gate
- [ ] MR; read the regression:mapping-gate delta (added rows are reported;
      removed rows need a waiver in regression/waivers.toml)
```

## Synthetic fixture leagues

Kalshi series that Optic has no fixture for (ITF doubles) are onboarded in
`synthetic/series.toml`. See `synthetic/README.md`.

## Do not

- Add or enable a league on the tip, or run
  `python -m BigQuery.activate_mapping_rule_set`.
- Edit `tests/fixtures/sot/tip.json` to make a new league appear.
- Propose through the console or Mapper Chat.
- Add a Python module per league; league data is a table entry, logic
  belongs in the profile or venue matcher.
