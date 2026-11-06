"""Run the STX pass offline over files and write ``market_mapping``-shaped rows. Reads files only; writes one file.

Usage:
    python -m mappers.exchanges.stx_run --markets DIR/stx_markets.jsonl \\
        --optic-fixtures DIR/optic_fixtures_odds.jsonl [--players DIR/stx_event_players.jsonl] \\
        [--optic-players SELECTIONS.json] [--as-of 2026-10-28T11:43:44Z] --out stx_mapping.jsonl

``--optic-fixtures`` takes the pipeline's Optic fetch (``optic_fixtures_odds.jsonl``, Optic's ``/fixtures/odds``
records; player selections are read off their odds) or the workspace capture ``{"fixtures": [...]}``.
``--optic-players`` takes the workspace capture of player selections (``{"games": {...: {fixture_id, rows}}}``).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mappers.exchanges.stx import StxMarket, market_from_row
from mappers.exchanges.stx_fixtures import OpticFixtureRef, fixture_from_record
from mappers.exchanges.stx_pass import StxContext, market_mapping_row, run_pass
from mappers.exchanges.stx_players import Roster, optic_player_index, roster_from_payload
from mappers.shared import parse_iso_datetime


def _records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        return [r for r in (json.loads(line) for line in text.splitlines() if line.strip()) if isinstance(r, dict)]
    return [doc] if isinstance(doc, dict) else [r for r in doc if isinstance(r, dict)]


def read_catalogue(rows: Iterable[dict[str, Any]]) -> list[StxMarket]:
    """Typed markets from catalogue rows; unreadable rows are skipped."""
    return [m for r in rows if (m := market_from_row(r)) is not None]


def read_rosters(bodies: Iterable[dict[str, Any]]) -> dict[str, Roster | None]:
    """``{event_id: roster}`` from ``/events/{id}/players`` bodies (None where STX listed no team)."""
    return {str(b["event_id"]): roster_from_payload(b) for b in bodies if b.get("event_id")}


def read_optic(records: Iterable[dict[str, Any]]) -> tuple[list[OpticFixtureRef], dict[str, dict]]:
    """Fixtures and per-fixture player indexes from Optic fixture records (or a ``{"fixtures": [...]}`` wrapper)."""
    fixtures: list[OpticFixtureRef] = []
    players: dict[str, dict] = {}
    for rec in records:
        items = rec["fixtures"] if isinstance(rec.get("fixtures"), list) else [rec]
        for item in items:
            fx = fixture_from_record(item)
            if fx is None:
                continue
            fixtures.append(fx)
            sel = [
                (o.get("player_id"), o.get("selection"))
                for o in item.get("odds") or []
                if isinstance(o, dict) and "," not in str(o.get("player_id") or "")  # h2h odds list several players
            ]
            if any(pid for pid, _ in sel):
                players[fx.fixture_id] = optic_player_index(sel)
    return fixtures, players


def read_optic_selections(doc: dict[str, Any]) -> dict[str, dict]:
    """Per-fixture player indexes from the workspace capture ``{"games": {name: {fixture_id, rows}}}``."""
    out: dict[str, dict] = {}
    for game in (doc.get("games") or {}).values():
        rows = game.get("rows") or []
        out[str(game["fixture_id"])] = optic_player_index((r.get("player_id"), r.get("selection")) for r in rows)
    return out


def main() -> None:
    """CLI entry: map a catalogue file onto Optic fixtures and write the rows."""
    p = argparse.ArgumentParser(description="Map STX markets onto Optic fixtures (offline, no BigQuery).")
    p.add_argument("--markets", type=Path, required=True)
    p.add_argument("--optic-fixtures", type=Path, required=True)
    p.add_argument("--players", type=Path, help="stx_event_players.jsonl")
    p.add_argument("--optic-players", type=Path, help="captured Optic player selections")
    p.add_argument("--as-of", help="ISO time events must start after (default: now)")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    fixtures, players = read_optic(_records(args.optic_fixtures))
    for doc in _records(args.optic_players) if args.optic_players else []:
        players.update(read_optic_selections(doc))
    as_of = parse_iso_datetime(args.as_of) if args.as_of else datetime.now(UTC)
    ctx = StxContext(
        fixtures=fixtures,
        as_of=as_of,
        optic_players=players,
        rosters=read_rosters(_records(args.players)) if args.players else {},
    )
    sides, tally = run_pass(read_catalogue(_records(args.markets)), ctx)
    with args.out.open("w", encoding="utf-8") as fh:
        for s in sides:
            fh.write(json.dumps(market_mapping_row(s), separators=(",", ":")) + "\n")
    for line in tally.lines():
        print(line, file=sys.stderr)


if __name__ == "__main__":
    main()
