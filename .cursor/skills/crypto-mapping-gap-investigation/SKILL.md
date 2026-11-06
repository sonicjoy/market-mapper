---
name: crypto-mapping-gap-investigation
description: >-
  Investigates crypto.com FIFA mapping gaps in mmmapper: BigQuery gap SQL,
  catalogue vs QR vs market_mapping probes, gap_reason classification, Optic
  96h horizon, spread ladder rules, actionable vs expected gap_reason. Use for
  gap CSV exports, unmapped NX.F.OPT.FIFA symbols, or "why is this symbol
  unmapped".
---

# Crypto mapping gap investigation

## Quick start

```bash
# Single-symbol probe (default project marketmaking-test)
.venv/Scripts/python.exe .cursor/skills/crypto-mapping-gap-investigation/scripts/probe_symbol.py \
  "NX.F.OPT.FIFA-00001-260711-M.O.1.67.20260830"

# Full gap drill-down (substitute {project} in SQL)
# BigQuery/sql/crypto_mapping_gaps.sql
```

Durable domain memory: `~/.cursor/knowledge/mmmapper/technical/crypto-mapping-gaps.md`

## Investigation workflow

```
- [ ] 1. Parse symbol → fixture prefix, kickoff date, market/outcome slots
- [ ] 2. Run probe_symbol.py OR filter crypto_mapping_gaps.sql to symbol
- [ ] 3. Catalogue: crypto_underlying_securities (exact + base maturity match)
- [ ] 4. Mapped: market_mapping for fixture prefix (crypto.com, start_date filter)
- [ ] 5. Read gap_reason + action from gap SQL
- [ ] 6. Classify verdict (table below)
- [ ] 7. Report with fixture identity when known
- [ ] 8. If the fix is a new miss class: fix it in code with a test (CLAUDE.md), not a one-off pin
```

## Symbol anatomy

For reading a symbol while you investigate. Mapper code must not parse it:
identity and market come from the catalogue's typed fields
(`meta_*`, `EXTERNAL_HOME_ID` / `EXTERNAL_AWAY_ID`).

```
NX.F.OPT.FIFA-{eventId}-{yymmdd}-M.O.{market#}.{outcome#}.{maturityYYYYMMDD}
```

| Part | Meaning |
|------|---------|
| `eventId` | Crypto fixture id (`00001`, `00002`, …) — **not** Kalshi ticker |
| `yymmdd` | Kickoff date bucket (fallback kickoff if catalogue missing) |
| `M.O.{market#}` | Market group slot — opaque without catalogue |
| `.{outcome#}` | Outcome slot — opaque without catalogue |
| `.{maturity}` | Maturity suffix; strip for base match |

**Without catalogue:** only heuristic is `M.O.1.[123]` → likely Moneyline (3-Way). All other slots need `crypto_underlying_securities`.

`NX.F.OPT.TENNIS` is shared by ATP / WTA / Challenger / ITF. Narrow the
league with catalogue `meta_league` (ATP → `atp` + `atp_challenger`). Do not take the first inferred slug (often
`wta`) and do not treat another tour's book as `name_mismatch`.

**Date-only placeholders:** crypto often stamps a matchweek as
`YYYY-MM-DDT04:00:00+00:00` (Eastern midnight of the ticker `yymmdd`, or
fixed `04:00 UTC` in winter) until a real kickoff is filled in. That is
**not** a missing `crypto_id` — `name_mismatch` against the
placeholder day's other games is a false classification. Mapper
unique-binds `{home, away}` when EVENT_DATE is a placeholder (fail-closed
on two meetings). Probe searches the full Optic horizon before
`name_mismatch`. Do not pin.

MLB has **no full-game** `Moneyline (3-Way)`. That contract is F5 and F3
only. Map `Moneyline (3-Way)` @ `1st-5th Inning` → `f5_moneyline_3way`
(Optic `1st_half_moneyline_3-way`) and @ `1st-3rd Inning` →
`f3_moneyline_3way` (Optic `1st_3_innings_moneyline_3-way`). Do not pin
aliases and do not stamp onto 2-way `moneyline`. Crypto F3 Spread / Total
Runs have **no** Optic counterpart — leave them unwired (load drops
crypto-only rows). The Optic side is the code vocab
(`mappers/vocab/baseball_markets.py` maps `1st_3_innings_moneyline_3-way`).
A missing crypto contract type is a vocab change in code with a test,
bound to a live Optic `market_id`, never a tip `mapping_market_rules` row.

Catalogue fields: `meta_predict_market_type`, `meta_predict_contract_type`, `meta_event_date`, `meta_name`.

Code: `mappers/exchanges/crypto_com.py`, soccer vocab
`mappers/exchanges/crypto_soccer.py`, team ids `mappers/vocab/crypto_team_ids.py`.
The World Cup `CRYPTO` league settings still come from the legacy tip.

## BigQuery tables

| Table | Role |
|-------|------|
| `processed_upstream_us.crypto_underlying_securities` | Catalogue (SecurityList metadata) |
| `processed_upstream_us.crypto_security_def` | Complement + fixture ids (flattened `meta_*` columns) |
| `processed_upstream_us.crypto_quote_requests` | QR leg symbols (`symbols[].legs[].symbol`) |
| `markets_us.market_mapping` | Mapped output (`json_value(source_ids,'$.symbol')`) |

**Do not** use `raw_ingestion_us.crypto_com_fix_messages2` for gap QR counts (replaced Jul 2026). `EXTERNAL_HOME_ID`/`AWAY_ID` now come from `crypto_security_def` `meta_external_*_id` / `meta_*_participant` columns — the fetch identity bridge reads those columns, not the raw FIX table.

**Projects:** `marketmaking-test` has full upstream tables. `rs-marketmaking` may lack `crypto_quote_requests` / catalogue, so a manual query there can fail on a missing table.

**Partition rule:** always `where start_date > timestamp_sub(current_timestamp(), interval 90 day)` on `market_mapping`.

## Gap SQL

The mapper does not publish a crypto.com coverage alert. RFQ leftovers are
fixed in code. These queries are for a manual drill-down.
`gap_reason` containing `actionable` is a true mapper gap.

| File | Purpose |
|------|---------|
| `BigQuery/sql/crypto_mapping_gaps.sql` | Per-symbol drill-down |
| `BigQuery/sql/crypto_mapping_gaps_summary.sql` | Rollup |
| `BigQuery/crypto_gap_sql.py` | Substitutes project and league into those templates |

**Params:** lookback 5h QR, catalogue 14d, **optic horizon 96h**, min 5 QRs, prefix `NX.F.OPT.FIFA`.

## gap_reason decision tree

| gap_reason | Usually means | Actionable? |
|------------|---------------|-------------|
| `not in catalogue (wait for upstream)` | QR-only; no SecurityDef for fixture | No |
| `outside Optic horizon` | Kickoff > 96h; Optic/Kalshi not quoting yet | No |
| `crypto-only spread (beyond Optic ladder)` | Fixture has mapped spreads; extra legs are crypto extended ladder | No |
| `completed fixture (stale symbol): …` | Game finished; superseded symbols still RFQ'd | No |
| `tournament/future market (by design)` | Out of mapper scope | No |
| `in catalogue (base match only)` | Maturity suffix mismatch | No |
| `actionable prop gap` | Mapped player-prop type, in horizon, unmapped | **Yes** |
| `actionable game-prop gap` | BTTS in horizon, unmapped | **Yes** |
| `actionable game-line gap: {type}` | ML/Total/Spread/To Advance in horizon, unmapped | **Yes** (Spread: only if fixture has **zero** mapped spreads) |
| `unmapped player/game prop/line: …` | Catalogue type not in mapper vocab | Investigate config |

### Spread nuance

Optic/Kalshi publish a **subset** of spread lines. Crypto lists a wider handicap ladder. Unmapped spread legs on fixtures that **already have** mapped `point_spread` rows → `crypto-only spread`, not mapper failure.

Optic spread lines are **live from API** (`optic.build_rows()` / `asian_handicap`), not a static code ladder.

### Horizon nuance

96h matches `world_cup.py` `horizon_hours=96`. Applies to **game lines, player props, and game props** (BTTS). Early crypto RFQ before Optic posts lines is expected — not actionable.

## Verdict template

```markdown
## {symbol}

| | |
|---|---|
| Fixture | {prefix} → {teams if known} |
| Kickoff | {UTC} ({hours}h out) |
| Catalogue | {market_group / contract_type or NONE} |
| Mapped | {count} crypto.com rows on fixture |
| gap_reason | {from SQL} |

**Verdict:** {upstream wait | horizon wait | expected ladder | mapper bug | missing crypto_id}
**Why:** {one sentence}
**Next:** {wait / escalate upstream / fix mapper code / fix gap SQL / add code id via add-team-alias}
```

When the root cause is a missing crypto team id, add it to
`CRYPTO_TEAM_IDS` in `mappers/vocab/crypto_team_ids.py` from id evidence
(Optic-stamped crypto rows joined to `crypto_security_def`), with a test in
`tests/mappers/test_crypto_team_ids.py`. See
`.cursor/skills/add-team-alias/SKILL.md`. No tip pin, no console card.

## Known fixture identities

| Prefix | Match (catalogue or schedule-aligned) |
|--------|----------------------------------------|
| `FIFA-00001-260706` | England @ Mexico |
| `FIFA-00002-260706` | Spain @ Portugal |
| `FIFA-00002-260707` | Egypt @ Argentina |
| `FIFA-00001-260707` | Belgium @ USA |
| `FIFA-00001-260709` | Morocco @ France (partial prop catalogue) |
| `FIFA-00001-260711` | QF — early BTTS RFQ, outside 96h horizon |

## When to update memory

After confirming a new pattern, append to `~/.cursor/knowledge/mmmapper/technical/crypto-mapping-gaps.md`:
- new fixture identity
- gap SQL / classification rule change
- upstream table or schema change

See [reference.md](reference.md) for probe SQL snippets and alert code pointers.
