#!/usr/bin/env python3
"""Verify Optic's natural key uniqueness across all data files.

Parses every optic_fixtures_odds.jsonl in data/ and checks:

1. odd.id is unique per game (baseline sanity).
2. The 6-tuple (game_id, market_id, selection, selection_line, points,
   grouping_key) is unique per odd across all files.
3a. 1:1 mapping between odd.id and the 6-tuple — same discriminating
    power, just different representations.
3b. 1:1 mapping between slug (third component of odd.id) and
    (selection, selection_line, points, grouping_key) within each
    (game_id, market_id) — tells us whether the slug encodes
    grouping_key info.
3c. 1:1 mapping between slug and (selection, selection_line, points)
    WITHOUT grouping_key — tells us whether grouping_key adds info
    beyond what the slug carries.

Usage:
    python scripts/verify_optic_key.py [data_root]
    python scripts/verify_optic_key.py          # defaults to data/
"""

import json
import sys
from collections import defaultdict
from pathlib import Path


def parse_odds(path):
    """Yield (game_id, odd) pairs from an optic_fixtures_odds.jsonl file."""
    with open(path) as f:
        for line in f:
            game = json.loads(line)
            game_id = game["game_id"]
            for odd in game.get("odds", []):
                yield game_id, odd


def main():
    data_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")
    files = sorted(data_root.rglob("optic_fixtures_odds.jsonl"))
    if not files:
        sys.exit(f"No optic_fixtures_odds.jsonl files found under {data_root}")

    total_odds = 0
    total_files = len(files)

    # Check 1: odd.id unique per game
    check1_dupes = []

    # Check 2: 6-tuple unique globally
    seen_tuples = defaultdict(list)  # tuple -> list of (file, odd.id)

    # Check 3a: odd.id <-> 6-tuple bijectivity
    id_to_tuple = {}   # odd.id -> 6-tuple
    tuple_to_id = {}   # 6-tuple -> odd.id

    # Check 3b: slug <-> (sel, sel_line, points, gk) within (game_id, market_id)
    # Key: (game_id, market_id, slug) -> (sel, sel_line, points, gk)
    slug_to_fields_gk = {}
    fields_gk_to_slug = {}  # (game_id, market_id, sel, sel_line, points, gk) -> slug
    check3b_mismatches = []

    # Check 3c: slug <-> (sel, sel_line, points) without grouping_key
    slug_to_fields = {}
    fields_to_slug = {}  # (game_id, market_id, sel, sel_line, points) -> slug
    check3c_mismatches = []

    for fpath in files:
        # Check 1: per-game uniqueness
        game_odds = defaultdict(list)  # game_id -> list of odd.id

        for game_id, odd in parse_odds(fpath):
            total_odds += 1
            odd_id = odd["id"]
            market_id = odd["market_id"]
            selection = odd.get("selection", "")
            selection_line = odd.get("selection_line")
            points = odd.get("points")
            grouping_key = odd.get("grouping_key", "")

            game_odds[game_id].append(odd_id)

            # --- Check 2: 6-tuple ---
            t6 = (game_id, market_id, selection, selection_line,
                  points, grouping_key)
            seen_tuples[t6].append((str(fpath), odd_id))

            # --- Check 3a: odd.id <-> 6-tuple ---
            if odd_id in id_to_tuple:
                if id_to_tuple[odd_id] != t6:
                    print(f"  3a FAIL: same odd.id maps to different tuples:")
                    print(f"    odd.id: {odd_id}")
                    print(f"    tuple1: {id_to_tuple[odd_id]}")
                    print(f"    tuple2: {t6}")
            else:
                id_to_tuple[odd_id] = t6

            if t6 in tuple_to_id:
                if tuple_to_id[t6] != odd_id:
                    print(f"  3a FAIL: same tuple maps to different odd.ids:")
                    print(f"    tuple: {t6}")
                    print(f"    id1:   {tuple_to_id[t6]}")
                    print(f"    id2:   {odd_id}")
            else:
                tuple_to_id[t6] = odd_id

            # --- Extract slug from odd.id ---
            parts = odd_id.split(":", 2)
            if len(parts) != 3:
                print(f"  WARNING: odd.id doesn't have 3 colon parts: {odd_id}")
                continue
            slug = parts[2]

            # --- Check 3b: slug <-> (sel, sel_line, points, gk) ---
            slug_key = (game_id, market_id, slug)
            fields_gk = (selection, selection_line, points, grouping_key)

            if slug_key in slug_to_fields_gk:
                if slug_to_fields_gk[slug_key] != fields_gk:
                    check3b_mismatches.append({
                        "direction": "slug -> fields+gk",
                        "slug_key": slug_key,
                        "fields1": slug_to_fields_gk[slug_key],
                        "fields2": fields_gk,
                    })
            else:
                slug_to_fields_gk[slug_key] = fields_gk

            reverse_key_gk = (game_id, market_id) + fields_gk
            if reverse_key_gk in fields_gk_to_slug:
                if fields_gk_to_slug[reverse_key_gk] != slug:
                    check3b_mismatches.append({
                        "direction": "fields+gk -> slug",
                        "fields": reverse_key_gk,
                        "slug1": fields_gk_to_slug[reverse_key_gk],
                        "slug2": slug,
                    })
            else:
                fields_gk_to_slug[reverse_key_gk] = slug

            # --- Check 3c: slug <-> (sel, sel_line, points) without gk ---
            fields_no_gk = (selection, selection_line, points)

            if slug_key in slug_to_fields:
                if slug_to_fields[slug_key] != fields_no_gk:
                    check3c_mismatches.append({
                        "direction": "slug -> fields",
                        "slug_key": slug_key,
                        "fields1": slug_to_fields[slug_key],
                        "fields2": fields_no_gk,
                    })
            else:
                slug_to_fields[slug_key] = fields_no_gk

            reverse_key = (game_id, market_id) + fields_no_gk
            if reverse_key in fields_to_slug:
                if fields_to_slug[reverse_key] != slug:
                    check3c_mismatches.append({
                        "direction": "fields -> slug",
                        "fields": reverse_key,
                        "slug1": fields_to_slug[reverse_key],
                        "slug2": slug,
                    })
            else:
                fields_to_slug[reverse_key] = slug

        # Check 1: find dupes within this game
        for gid, ids in game_odds.items():
            seen = {}
            for oid in ids:
                if oid in seen:
                    check1_dupes.append((str(fpath), gid, oid))
                else:
                    seen[oid] = True

    # --- Report ---
    print(f"\n{'='*60}")
    print(f"Scanned {total_files} files, {total_odds:,} total odds")
    print(f"Unique odd.ids: {len(id_to_tuple):,}")
    print(f"Unique 6-tuples: {len(tuple_to_id):,}")
    print()

    # Check 1
    if check1_dupes:
        print(f"CHECK 1 FAIL: {len(check1_dupes)} duplicate odd.ids within games:")
        for fpath, gid, oid in check1_dupes[:10]:
            print(f"  {fpath}  game={gid}  odd.id={oid}")
    else:
        print("CHECK 1 PASS: odd.id is unique per game")

    # Check 2
    dupes_2 = {t: locs for t, locs in seen_tuples.items() if len(locs) > 1}
    # Filter to dupes within the same file (cross-file dupes are expected
    # since the same game appears in multiple fetches).
    intra_file_dupes = {}
    for t, locs in dupes_2.items():
        by_file = defaultdict(list)
        for fpath, oid in locs:
            by_file[fpath].append(oid)
        for fpath, oids in by_file.items():
            if len(oids) > 1:
                intra_file_dupes.setdefault(t, []).extend(
                    (fpath, oid) for oid in oids)

    if intra_file_dupes:
        print(f"CHECK 2 FAIL: {len(intra_file_dupes)} duplicate 6-tuples "
              f"within same file:")
        for t, locs in list(intra_file_dupes.items())[:5]:
            print(f"  tuple: {t}")
            for fpath, oid in locs[:3]:
                print(f"    {fpath}  odd.id={oid}")
    else:
        print("CHECK 2 PASS: 6-tuple is unique per odd (within each file)")

    # Check 3a
    if len(id_to_tuple) == len(tuple_to_id):
        print("CHECK 3a PASS: odd.id <-> 6-tuple is 1:1 "
              f"({len(id_to_tuple):,} distinct values)")
    else:
        print(f"CHECK 3a FAIL: odd.id count ({len(id_to_tuple):,}) != "
              f"6-tuple count ({len(tuple_to_id):,})")

    # Check 3b
    if check3b_mismatches:
        print(f"CHECK 3b FAIL: {len(check3b_mismatches)} slug <-> "
              f"(sel, sel_line, points, grouping_key) mismatches:")
        for m in check3b_mismatches[:5]:
            print(f"  {m}")
    else:
        print(f"CHECK 3b PASS: slug <-> (sel, sel_line, points, grouping_key) "
              f"is 1:1 within (game_id, market_id)")

    # Check 3c
    if check3c_mismatches:
        print(f"CHECK 3c FAIL: {len(check3c_mismatches)} slug <-> "
              f"(sel, sel_line, points) mismatches (without grouping_key):")
        for m in check3c_mismatches[:5]:
            print(f"  {m}")
        if len(check3c_mismatches) > 5:
            print(f"  ... and {len(check3c_mismatches) - 5} more")
    else:
        print(f"CHECK 3c PASS: slug <-> (sel, sel_line, points) is 1:1 "
              f"(grouping_key adds no info beyond slug)")

    print()

    # Exit non-zero if anything failed
    failed = (check1_dupes or intra_file_dupes
              or len(id_to_tuple) != len(tuple_to_id)
              or check3b_mismatches or check3c_mismatches)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
