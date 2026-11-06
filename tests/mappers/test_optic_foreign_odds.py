"""Optic /fixtures/odds sometimes returns another fixture's odds inside a game.

2026-10-09 NHL: the Dallas @ Colorado (15 Oct) fixture carried all ten odds of
the Colorado @ Dallas (14 Oct) fixture under their own `…-10-13:` id prefix.
`all_game_ref_lookup` is keyed by odd id, so the later fixture won the key and
the earlier game's rows were stamped with the later game's game_id/fixture_id.
"""

from __future__ import annotations

import json
from pathlib import Path

from mappers.exchanges.optic import OpticConfig, load_fixtures
from tests.mappers.test_doubleheader import _optic_game


def _write(path: Path, *games: dict) -> None:
    path.write_text("".join(json.dumps(g) + "\n" for g in games), encoding="utf-8")


def _odd_ids(index) -> dict[str, set[str]]:
    return {
        f.fixture_id: {o.id for o in f.odds}
        for fixtures in index.values() for f in fixtures
    }


def _games():
    a = _optic_game(game_id="27720-13005-2026-10-13", fixture_id="fixA",
                    start_date="2026-10-14T00:30:00Z")
    b = _optic_game(game_id="27720-13005-2026-10-14", fixture_id="fixB",
                    start_date="2026-10-15T01:30:00Z")
    return a, b


def test_drops_odds_carrying_another_loaded_games_id(tmp_path: Path, capsys):
    a, b = _games()
    b["odds"] = a["odds"] + b["odds"]  # contamination: A's odds inside B
    path = tmp_path / "optic.jsonl"
    _write(path, a, b)

    index = load_fixtures(path, OpticConfig(league_id="mlb", table_types={}))

    ids = _odd_ids(index)
    assert ids["fixA"] == {o["id"] for o in a["odds"]}
    assert ids["fixB"] == {
        "27720-13005-2026-10-14:moneyline:home",
        "27720-13005-2026-10-14:moneyline:away",
    }
    assert "foreign odds" in capsys.readouterr().err


def test_keeps_stale_prefix_that_matches_no_loaded_game(tmp_path: Path):
    """Reschedule leftover: old-date prefix, no fixture owns it — keep it."""
    a, _ = _games()
    stale = dict(a["odds"][0], id="27720-13005-2026-10-09:moneyline:home")
    a["odds"] = a["odds"] + [stale]
    path = tmp_path / "optic.jsonl"
    _write(path, a)

    index = load_fixtures(path, OpticConfig(league_id="mlb", table_types={}))

    assert stale["id"] in _odd_ids(index)["fixA"]
