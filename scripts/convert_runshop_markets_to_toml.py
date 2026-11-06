"""Convert runshop_mappings.markets CSV export to runshop_markets.toml."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def convert(csv_path: Path, out_path: Path) -> int:
    rows: list[dict[str, str | int | float]] = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw_value = row["value"]
            if raw_value in ("", "NULL", None):
                continue
            rows.append({
                "id": int(row["id"]),
                "market": row["market"],
                "value": float(row["value"]),
                "selection": row["selection"],
                "sport_id": int(row["sport_id"]),
            })

    lines = [
        "# Runshop market dictionary (sport_id=100002 soccer).",
        "# Source: runshop_mappings.markets — regenerate via:",
        "#   python scripts/convert_runshop_markets_to_toml.py <markets.csv>",
        "",
        "[[market]]",
    ]
    body: list[str] = []
    for i, row in enumerate(rows):
        if i > 0:
            body.append("")
            body.append("[[market]]")
        body.append(f'id = {row["id"]}')
        body.append(f'market = {row["market"]!r}')
        body.append(f'value = {row["value"]}')
        body.append(f'selection = {row["selection"]!r}')
        body.append(f'sport_id = {row["sport_id"]}')

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines + body) + "\n", encoding="utf-8")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert Runshop markets CSV to TOML config",
    )
    parser.add_argument(
        "csv",
        type=Path,
        help="Path to markets.csv export",
    )
    parser.add_argument(
        "-o", "--out",
        type=Path,
        default=Path("config/world_cup/runshop_markets.toml"),
        help="Output TOML path",
    )
    args = parser.parse_args()
    count = convert(args.csv, args.out)
    print(f"Wrote {count} markets to {args.out}")


if __name__ == "__main__":
    main()
