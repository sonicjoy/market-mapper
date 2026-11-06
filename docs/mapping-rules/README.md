# Mapping rules

**Mapping rules are code.** Leagues, market-type vocab, venue league ids and
aliases live in Python, ship by MR and are checked by the mapping regression
gate (`regression/`, CI job `regression:mapping-gate`). Where each kind of
rule lives, and the hard rules (no tip, no console, no ticker parsing):
[`CLAUDE.md`](../../CLAUDE.md).

The BigQuery rule-set tip and `mappers/seed/sot.py` are legacy. The mapper
still loads the tip today; that is being removed. See
[`m1-status.md`](m1-status.md).

---

## CSV exports in this folder

| File | Contents |
|---|---|
| `canonical_types.csv` | Glossary of every canonical `MarketType` (scope + shape) |
| `optic_spine.csv` | One row per `(league, optic_market_id)` → canonical type, with Kalshi / crypto.com / Polymarket / PX vendor keys that stamp onto the same type |
| `platform_only.csv` | Vendor keys with **no** Optic counterpart (`mapped_no_optic`) or deliberately ignored (`ignored`) |

These are a frozen human/diff aid, not a source of rules. The generator
(`scripts/export_mapping_rules.py`) was deleted in `68ace910`, so they are no
longer regenerated. `optic_spine.csv` is still copied into the image
(`deploy/Dockerfile`) and read by `mappers/control_plane/` and some tests.

Platform columns in `optic_spine.csv` use `;`-joined vendor keys. Crypto prefixes: `game_line:`, `period[<period>]:`, `prop:`, `game_prop:`, `team_prop:`. PX prefixes: `exact:`, `suffix:`.

## Retired docs

`console-deploy.md`, `control-plane-api.md`, `mapper-chat.md`,
`gap-propose.md` and `r068-prod-hold.md` describe the mapping console and
its CronJobs. They are kept for the facts needed to switch those things off.
They are not a way to ship mapping.
