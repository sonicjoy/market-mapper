# MERGE verification tests

Verification of the stage → MERGE upsert flow in `load_mappings.py`,
run against `greg_sandbox.market_mapping` on 2026-03-12.

## 1. Idempotent reload

Loaded `data/2026-03-12/06_40/mappings.jsonl` (7,113 rows), snapshotted
the table, then reloaded the same file. Result: all non-timestamp fields
identical, `last_updated` refreshed on all rows.

## 2. Hacked reload — mutations across all null-pattern combinations

Temporarily patched `load_mappings.py` to mutate the staged data before
MERGE, then verified the target table reflected the expected changes.
The `entity` and `line` key columns are nullable, so the MERGE ON
clause uses `IS NOT DISTINCT FROM` for NULL-safe matching. All four
combinations of nullability were tested.

### Value changes (MERGE UPDATE path)

Each hack changed a non-key field on existing rows, verifying that the
MERGE matched on key columns (including NULLs) and updated the value.

| Target rows | entity | line | Field changed | New value | Rows affected |
|---|---|---|---|---|---|
| ATL/BKN moneyline side=ATL | NULL | NULL | `fixture_id` | `TEST_CHANGED_FIXTURE` | 2 |
| ATL/BKN cj_mccollum double_double | SET | NULL | `game_id` | `TEST_CHANGED_GAME` | 2 |
| IND/PHX all player_points | SET | SET | `selection` | `HACKED` | 137 |
| MEM/DAL all game_total | NULL | SET | `grouping_key` | `HACKED_GK` | 32 |

All four were confirmed via SELECT after the hacked load.

### Dropped rows (MERGE preserves unmatched target rows)

Rows omitted from the stage should remain in the target, since MERGE
has no WHEN NOT MATCHED BY SOURCE clause.

| Target rows | Rows omitted from stage |
|---|---|
| All ORL vs WAS rows | 182 |
| MIA/MIL moneyline (entity=NULL, line=NULL) | 4 |
| ATL/BKN team_total entity=ATL line=113.5 over | 1 |

All preserved rows confirmed present after the hacked load.

### Inserted rows (MERGE INSERT path)

Three synthetic rows were added to the stage with keys not present in
the target, covering three null-pattern variants:

| Synthetic row | entity | line |
|---|---|---|
| TST/HCK moneyline | NULL | NULL |
| TST/HCK player_points fake_player 99.5 | SET | SET |
| TST/HCK player_double_double fake_player | SET | NULL |

All three appeared in the target after the hacked load. Final row count
was 7,116 (7,113 + 3).

### No duplicate keys

After every load (clean, hacked, and restored), confirmed 0 duplicate
key groups across all 9 key columns.

## 3. Restore to clean state

Reverted `load_mappings.py`, truncated the table, and reloaded the
original data. All 7,113 rows matched the pre-hack snapshot (excluding
`last_updated`).
