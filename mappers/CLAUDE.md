# CLAUDE.md — `mappers/`
Root rules and deploy facts: `../CLAUDE.md` (read its Agent rules first). This card is only the map of this package.

## Purpose
Builds `market_mapping` rows: venue contract → Optic `game_id` / `fixture_id` / `market_id` / `selection`. Optic REST v3 is the spine; venues bind by typed ids and code tables.

## Entry points
| File | Role |
|---|---|
| `run.py` | league fan-out (`python -m mappers.run <dir> --league …`; `--write-mappings` writes to BQ, omit it locally) |
| `pipeline.py` | the matcher, `run()` (3.5k lines, over the size guard by history; do not grow it, add a module) |
| `exchanges/<venue>*.py` | per-venue matching (`dkex_pass.py`, `dkex_names.py`, `underdog.py`, kalshi, novig, polymarket*, sxbet) |
| `vocab/*_markets.py`, `market_types.py` | market-type vocab per sport / venue |
| `profiles/` | parser profile per sport × venue grammar (`registry.py`) |
| `seed/code_leagues.py` | `CODE_LEAGUES`; `seed/*_rules.py` code-seeded market rules; `seed/tip_*.py` is legacy |
| `shared.py`, `canonical_codes.py`, `name_match.py` | name normalisation and `names_close` / `names_fit` (never loosen to bind an id) |
| `control_plane/` | dead console backend, do not extend |

## Test and repro
```bash
GCP_PROJECT=rs-marketmaking .venv/bin/pytest -q tests/mappers          # tests live in ../tests/mappers
python -m fetch --league <l> --out-dir <dir> && python -m mappers.run <dir> --league <l>   # local run, no write
```
Env for local runs: `GCP_PROJECT=rs-marketmaking`, `PYTHONPATH=.`; set `MAP_LEAGUE_WORKERS=1` if you monkeypatch (ProcessPool spawn cannot pickle patches on macOS).

## Gotchas
- Fix a name miss with an exact id pin (`dkex_names.py` `OPTIC_IDS_BY_DKEX_NAME` / `OPTIC_PLAYER_IDS_BY_DKEX_NAME`), not a looser matcher.
- One uncaught exception in a league drops it for every venue while the tick exits 0 (`run.py` prints `ALERT:`).
- Underdog contract types come from `external_ids.optic_odds.market_id` plus the contract sentence; vocab is `vocab/underdog_markets.py`.
- Correct score is YES-only, keyed by the winner, `correct_score_line(won, lost)` = won + lost/100 (shared by Optic and Polymarket).
- Every mapping change needs a test and shows its row delta in the `regression:mapping-gate` job; removed rows need `regression/waivers.toml`.
- No ticker parsing; sides and strikes come from typed venue fields.
