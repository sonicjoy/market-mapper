"""STX in the mapping tick: stamp each mapped STX side onto the matching Optic row of one league.

The offline pass (``stx_pass.run_pass``) decides every side of every STX market. This module runs it for ONE league
of the tick against the pipeline's own Optic schedule (``fixture_from_mmmapper``: the same team codes and kickoff
strings the Optic rows carry) and stamps the result onto the Optic row with the same canonical key, the DKEX /
Underdog shape (``attach_*_row`` in ``pipeline.py``):

* **stamped** -- the first STX side on an Optic row.
* **satellite** -- a second STX market on the same canonical bet (YES ``home_winner`` and NO ``away_winner`` are both
  the home team). Load emits the STX row alone, so every market keeps its own row. The maker looks a leg up by
  ``(market_id, selection_id)``.
* **dropped_no_optic** -- no Optic row has the key (Optic does not price that market or line): nothing lands, the
  count says so. A wrong bind is worse than an unmapped market (``CLAUDE.md``).

What lands in ``markets_us.market_mapping`` (``BigQuery/load_mappings.py``, sportsbook ``STX``) is
``source_ids = {market_id, selection_id: yes|no, event_id, tie_pays_half: bool}`` beside the Optic ``fixture_id`` /
``market_id`` / ``selection`` / ``selection_line`` / ``points``. ``tie_pays_half`` is ALWAYS written, true or false, so
a maker can treat a missing key as "not a row this mapper wrote" and refuse.

Input files in the tick's data dir (written by ``fetch/stx.py`` only where the STX key is wired; absent = no-op):
``stx_markets.jsonl``, ``stx_event_players.jsonl``. Output besides the rows: a tally line per league on stderr and
``stx_unmapped.<league>.jsonl`` (one line per refused side with its reason).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mappers.exchanges.stx import SPORTSBOOK, StxMarket, market_from_row
from mappers.exchanges.stx_fixtures import fixture_from_mmmapper
from mappers.exchanges.stx_leagues import COMPETITIONS, competition_for
from mappers.exchanges.stx_pass import StxContext, StxSideMapping, run_pass
from mappers.exchanges.stx_players import optic_player_index, roster_from_payload
from mappers.shared import CanonicalRow
from mappers.vocab.stx_markets import TIE_PAYS_HALF

MARKETS_FILE = "stx_markets.jsonl"
ROSTERS_FILE = "stx_event_players.jsonl"
UNMAPPED_FILE = "stx_unmapped.{league}.jsonl"

Attach = Callable[[dict, dict, list, CanonicalRow], str]


def stx_source_ids(market_id: str, selection_id: str, event_id: str | None, tie_pays_half: bool) -> dict[str, Any]:
    """The ``source_ids`` of one STX row. The maker's lookup contract: ``market_id`` + ``selection_id``."""
    return {
        "market_id": market_id,
        "selection_id": selection_id,
        "event_id": event_id,
        "tie_pays_half": bool(tie_pays_half),
    }


def canonical_row(s: StxSideMapping, league: str) -> CanonicalRow | None:
    """A mapped side as mmmapper's canonical row (the key ``row_index`` is looked up with), or None."""
    if not (s.mapped and s.fixture and s.rule and s.selection_side):
        return None
    fx = s.fixture
    return CanonicalRow(
        league=league,
        start_date=fx.start_date,
        home=fx.home.code,
        away=fx.away.code,
        market_type=s.rule.market_type.value,
        entity=s.entity,
        line=s.line,
        side=s.selection_side,
        stx_market_id=s.market.market_id,
        stx_side=s.side,
        stx_event_id=s.market.event_id,
        stx_tie_pays_half=TIE_PAYS_HALF in s.rule.flags,
    )


def _stamp(row: CanonicalRow, sr: CanonicalRow) -> None:
    row.stx_market_id = sr.stx_market_id
    row.stx_side = sr.stx_side
    row.stx_event_id = sr.stx_event_id
    row.stx_tie_pays_half = sr.stx_tie_pays_half


def attach_stx_row(
    row_index: dict[tuple, CanonicalRow],
    alt_stx: dict[tuple, CanonicalRow],
    all_rows: list[CanonicalRow],
    sr: CanonicalRow,
    *,
    key_of: Callable[[CanonicalRow], tuple],
) -> str:
    """Stamp STX ``(market_id, yes/no)`` onto the matching Optic row: stamped, satellite or dropped_no_optic.

    ``duplicate`` when the same (key, market_id, side) was already attached.
    """
    if sr.stx_market_id is None or sr.stx_side is None:
        return "dropped_no_optic"
    key = key_of(sr)
    alt_key = (key, sr.stx_market_id, sr.stx_side)
    if alt_key in alt_stx:
        return "duplicate"
    existing = row_index.get(key)
    if existing is None:
        return "dropped_no_optic"
    if existing.stx_market_id is None:
        _stamp(existing, sr)
        alt_stx[alt_key] = existing
        return "stamped"
    sr.stx_satellite = True
    if sr.optic_id is None:
        sr.optic_id = existing.optic_id
    all_rows.append(sr)
    alt_stx[alt_key] = sr
    return "satellite"


def _read_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def optic_players(entries: list) -> dict[str, dict]:
    """Per-fixture Optic player indexes from the tick's own parsed odds.

    A head-to-head odd carries several players in one ``player_id`` (``"A,B,B"``, ``player_rebounds_h2h_*``); it is
    not one player's id and would make every matchup player "ambiguous" (live Ontario tick 2026-10-29: 3 ids for one
    NBA player), so only single-id odds count.
    """
    out: dict[str, dict] = {}
    for e in entries:
        fx = e.fixture
        sel = [(o.player_id, o.selection) for o in fx.odds if o.player_id and "," not in o.player_id]
        if sel:
            out[fx.fixture_id] = optic_player_index(sel)
    return out


def league_competitions(league: str) -> set[str]:
    """STX competition names whose run-set league is ``league``."""
    return {c.name for c in COMPETITIONS.values() if c.slug == league}


def _league_markets(league: str, data_dir: Path) -> list[StxMarket]:
    """This league's STX markets from the tick's catalogue (typed rows of its competitions only)."""
    names = league_competitions(league)
    if not names:
        return []
    rows = _read_lines(data_dir / MARKETS_FILE)
    markets = [m for r in rows if (m := market_from_row(r)) and competition_for(m.competition, m.sport)]
    return [m for m in markets if m.competition in names]


def _write_unmapped(league: str, sides: list[StxSideMapping], data_dir: Path) -> None:
    lines = [
        {
            "league": league,
            "market_id": s.market.market_id,
            "event_id": s.market.event_id,
            "selection_id": s.side,
            "rules": s.market.rules,
            "reason": s.reason,
        }
        for s in sides
        if not s.mapped
    ]
    if lines:
        out = data_dir / UNMAPPED_FILE.format(league=league)
        out.write_text("".join(json.dumps(u, separators=(",", ":")) + "\n" for u in lines), encoding="utf-8")


def run_league(
    league: str,
    entries: list,
    row_index: dict[tuple, CanonicalRow],
    all_rows: list[CanonicalRow],
    data_dir: Path,
    *,
    key_of: Callable[[CanonicalRow], tuple],
    as_of: datetime | None = None,
) -> Counter | None:
    """Map this league's STX markets onto the tick's Optic rows; the tally, or None when STX has nothing to do here."""
    markets = _league_markets(league, data_dir)
    if not markets:
        return None
    rosters = {
        str(b["event_id"]): roster_from_payload(b) for b in _read_lines(data_dir / ROSTERS_FILE) if b.get("event_id")
    }
    ctx = StxContext(
        fixtures=[fixture_from_mmmapper(e.fixture) for e in entries],
        as_of=as_of or datetime.now(UTC),
        rosters=rosters,
        optic_players=optic_players(entries) if any(m.rules == "player_stat_line" for m in markets) else {},
    )
    sides, pass_tally = run_pass(markets, ctx)
    tally: Counter = Counter()
    alt_stx: dict[tuple, CanonicalRow] = {}
    for s in sides:
        row = canonical_row(s, league)
        if row is None:
            tally[f"unmapped:{s.reason_code}"] += 1
        else:
            tally[attach_stx_row(row_index, alt_stx, all_rows, row, key_of=key_of)] += 1
    _write_unmapped(league, sides, data_dir)
    _print_tally(league, pass_tally.joined_events, pass_tally.events, tally)
    return tally


def _print_tally(league: str, joined: int, events: int, tally: Counter) -> None:
    attached = ("stamped", "satellite", "dropped_no_optic", "duplicate")
    head = ", ".join(f"{k} {tally[k]}" for k in attached if tally[k])
    reasons = ", ".join(f"{k.split(':', 1)[1]} {n}" for k, n in tally.most_common() if k.startswith("unmapped:"))
    print(
        f"  {SPORTSBOOK.lower()} [{league}]: {joined}/{events} events joined; {head or 'nothing attached'}"
        f"; unmapped by reason: {reasons or 'none'}",
        file=sys.stderr,
    )
