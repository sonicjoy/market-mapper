"""Deterministic Huddle → Optic matcher (NFL). Merge-only onto Optic rows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple

from mappers.exchanges.optic import Fixture
from mappers.market_types import MarketType, Scope, Shape
from mappers.shared import (
    TIE_SIDE,
    CanonicalRow,
    normalize_line,
    normalize_player_name,
)
from mappers.team_side import team_side
from mappers.vocab.football_huddle import resolve_market_type

__all__ = [
    "HuddleConfig",
    "HuddleSelection",
    "parse_selection",
    "build_rows",
    "run_huddle_pass",
]


@dataclass(frozen=True)
class HuddleConfig:
    """Tip-built Huddle settings for one league."""

    competition_ids: tuple[str, ...]
    table_types: dict[str, MarketType]
    ignored_codes: frozenset[str] = frozenset()


class HuddleSelection(NamedTuple):
    """One huddle_dedup_state selection plus Sportradar join id."""

    event_id: str
    market_id: str
    selection_id: str
    market_code: str
    selection_code: str
    competition_id: str
    betradar_extid: str
    start_date: str
    line: float | None
    team: int | None
    milestone: float | None
    player_name: str | None
    period: float | None
    half: float | None


def parse_selection(raw: dict[str, object]) -> HuddleSelection | None:
    """Parse one JSONL object; drop rows missing join keys."""
    event_id = str(raw.get("event_id") or "").strip()
    market_id = str(raw.get("market_id") or "").strip()
    selection_id = str(raw.get("selection_id") or "").strip()
    market_code = str(raw.get("market_code") or "").strip()
    selection_code = str(raw.get("selection_code") or "").strip()
    extid = str(raw.get("betradar_extid") or "").strip()
    if not all((event_id, market_id, selection_id, market_code, selection_code, extid)):
        return None
    return HuddleSelection(
        event_id=event_id,
        market_id=market_id,
        selection_id=selection_id,
        market_code=market_code,
        selection_code=selection_code.upper(),
        competition_id=str(raw.get("competition_id") or "").strip(),
        betradar_extid=extid,
        start_date=str(raw.get("start_date") or "").strip(),
        line=_opt_float(raw.get("line")),
        team=_opt_int(raw.get("team")),
        milestone=_opt_float(raw.get("milestone")),
        player_name=str(raw.get("player_name") or "").strip() or None,
        period=_opt_float(raw.get("period")),
        half=_opt_float(raw.get("half")),
    )


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def build_rows(
    selections: list[HuddleSelection],
    *,
    cfg: HuddleConfig,
    league: str,
    sr_index: dict[str, Fixture],
) -> list[CanonicalRow]:
    """CanonicalRows for selections that 1-1 bind a fixture + Optic type."""
    allowed = frozenset(cfg.competition_ids)
    out: list[CanonicalRow] = []
    for sel in selections:
        if allowed and sel.competition_id not in allowed:
            continue
        if sel.market_code in cfg.ignored_codes:
            continue
        fx = sr_index.get(sel.betradar_extid)
        if fx is None:
            continue
        mt = resolve_market_type(
            sel.market_code,
            half=sel.half,
            period=sel.period,
            table_types=cfg.table_types,
        )
        if mt is None:
            continue
        if _drop_tie_leg(sel.selection_code, mt):
            continue
        row = _row_for(sel, fx, mt, league)
        if row is not None:
            out.append(row)
    return out


def _drop_tie_leg(selection_code: str, mt: MarketType) -> bool:
    """Skip Draw/Neither on 2-way Optic types; keep them on three_way."""
    if selection_code not in {"DRAW", "NEITHER"}:
        return False
    return mt.shape != Shape.THREE_WAY


def attach_huddle_stamp(
    row_index: dict[tuple, CanonicalRow],
    hr: CanonicalRow,
) -> str:
    """Stamp Huddle ids onto the matching Optic row, else drop."""
    # Deferred: pipeline imports this module for run_huddle_pass.
    from mappers.pipeline import row_key

    existing = row_index.get(row_key(hr))
    if existing is None:
        return "dropped_no_optic"
    existing.huddle_selection_id = hr.huddle_selection_id
    existing.huddle_event_id = hr.huddle_event_id
    existing.huddle_market_id = hr.huddle_market_id
    existing.huddle_market_code = hr.huddle_market_code
    existing.huddle_selection_code = hr.huddle_selection_code
    existing.huddle_betradar_extid = hr.huddle_betradar_extid
    return "stamped"


def _row_for(
    sel: HuddleSelection,
    fx: Fixture,
    mt: MarketType,
    league: str,
) -> CanonicalRow | None:
    side, entity, line = _shape_fields(sel, fx, mt)
    if side is None:
        return None
    return CanonicalRow(
        league=league,
        start_date=fx.start_date,
        home=fx.home,
        away=fx.away,
        market_type=mt.value,
        entity=entity,
        line=normalize_line(line) if line is not None else None,
        side=side,
        huddle_selection_id=sel.selection_id,
        huddle_event_id=sel.event_id,
        huddle_market_id=sel.market_id,
        huddle_market_code=sel.market_code,
        huddle_selection_code=sel.selection_code,
        huddle_betradar_extid=sel.betradar_extid,
    )


def _shape_fields(
    sel: HuddleSelection,
    fx: Fixture,
    mt: MarketType,
) -> tuple[str | None, str | None, float | None]:
    """Return (side, entity, line) or side None to drop."""
    code = sel.selection_code
    if mt.shape == Shape.MONEYLINE:
        return _home_away(code, fx), None, None
    if mt.shape == Shape.SPREAD:
        side = _home_away(code, fx)
        return side, None, _spread_line(sel)
    if mt.shape == Shape.TOTAL:
        side = _over_under(code)
        entity = _team_entity(sel, fx) if mt.scope == Scope.TEAM else None
        if mt.scope == Scope.TEAM and entity is None:
            return None, None, None
        return side, entity, sel.line
    if mt.shape == Shape.THREE_WAY:
        return _three_way_side(code, fx), None, _three_way_line(sel, mt)
    if mt.shape == Shape.OVER_UNDER:
        if not sel.player_name:
            return None, None, None
        return _over_under(code), normalize_player_name(sel.player_name), sel.line
    if mt.shape == Shape.YES_NO:
        return _yes_no(code, mt), _yes_no_entity(sel, mt), None
    return None, None, None


def _home_away(code: str, fx: Fixture) -> str | None:
    """HOME/AWAY on the Sportradar fixture, which is Optic's home/away too."""
    claimed = {"HOME": fx.home, "AWAY": fx.away}.get(code, "")
    return team_side(
        claimed, home=fx.home, away=fx.away,
        home_name=fx.home_name, away_name=fx.away_name,
    )


def _over_under(code: str) -> str | None:
    if code in {"OVER", "UNDER"}:
        return code.lower()
    return None


def _yes_no(code: str, mt: MarketType) -> str | None:
    if mt.scope == Scope.PLAYER and mt.shape == Shape.YES_NO:
        if code == "YES":
            return "yes"
        return None
    if code in {"YES", "NO"}:
        return code.lower()
    return None


def _spread_line(sel: HuddleSelection) -> float | None:
    """Huddle publishes the home-perspective line on both HOME and AWAY legs."""
    if sel.line is None:
        return None
    if sel.selection_code == "AWAY":
        return -sel.line
    return sel.line


def _yes_no_entity(sel: HuddleSelection, mt: MarketType) -> str | None:
    if mt.scope != Scope.PLAYER:
        return None
    if not sel.player_name:
        return None
    return normalize_player_name(sel.player_name)


def _team_entity(sel: HuddleSelection, fx: Fixture) -> str | None:
    """team 0 is home and team 1 is away on that same Sportradar fixture."""
    label = {0: "HOME", 1: "AWAY"}.get(sel.team if sel.team is not None else -1, "")
    return _home_away(label, fx)


def _three_way_side(code: str, fx: Fixture) -> str | None:
    if code in {"DRAW", "NEITHER"}:
        return TIE_SIDE
    return _home_away(code, fx)


def _three_way_line(sel: HuddleSelection, mt: MarketType) -> float | None:
    if mt is MarketType.RACE_TO_POINTS:
        return sel.milestone if sel.milestone is not None else sel.line
    return None


def run_huddle_pass(
    *,
    data_dir: Path,
    cfg: HuddleConfig,
    league: str,
    fixtures: list[Fixture],
    row_index: dict[tuple, CanonicalRow],
) -> tuple[int, int]:
    """Parse huddle_markets.jsonl and stamp merge-only. Returns (stamped, dropped)."""
    path = data_dir / "huddle_markets.jsonl"
    selections = _load_selections(path)
    sr_index = {
        fx.sportradar_id: fx for fx in fixtures if fx.sportradar_id
    }
    stamped = dropped = 0
    for row in build_rows(selections, cfg=cfg, league=league, sr_index=sr_index):
        if attach_huddle_stamp(row_index, row) == "stamped":
            stamped += 1
        else:
            dropped += 1
    return stamped, dropped


def _load_selections(path: Path) -> list[HuddleSelection]:
    if not path.is_file():
        return []
    out: list[HuddleSelection] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        try:
            parsed = parse_selection(raw)
        except (TypeError, ValueError):
            continue
        if parsed is not None:
            out.append(parsed)
    return out
