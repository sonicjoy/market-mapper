"""Tests for shared empty-abbreviation team bootstrap (BQ SoT in-memory pins)."""

import json
from pathlib import Path

import pytest

from mappers.seed.sot import reset_sot_cache
from mappers.team_bootstrap import _fallback_code, bootstrap_empty_abbrs, pin_shared_optic_abbr


@pytest.fixture(autouse=True)
def _bq_sot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAPPING_SOT", "bq")
    reset_sot_cache()


def _write_optic(path, league_id, competitors):
    home, away = competitors
    path.write_text(
        json.dumps({
            "id": "fx1",
            "game_id": "g1",
            "start_date": "2026-07-29T12:00:00Z",
            "home_competitors": [home],
            "away_competitors": [away],
            "league": {"id": league_id},
            "odds": [],
        }) + "\n",
        encoding="utf-8",
    )


def test_sot_bootstrap_uses_seed_overrides(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write_optic(
        data / "optic_fixtures_odds.jsonl",
        "itf_men",
        (
            {"id": "OID1", "name": "Player One", "abbreviation": ""},
            {"id": "OID2", "name": "Player Two", "abbreviation": "PTW"},
        ),
    )
    overrides = bootstrap_empty_abbrs(
        data, "itf_men", Path(),
        seed_used={"PTW"},
        seed_overrides={"OID2": "PTW"},
    )
    assert overrides["OID1"]
    assert overrides["OID2"] == "PTW"


def test_no_optic_source_returns_seed_overrides(tmp_path):
    assert bootstrap_empty_abbrs(
        tmp_path / "data", "league_of_legends", Path(),
        seed_overrides={"x": "Y"},
    ) == {"x": "Y"}


def test_fallback_code_skips_collisions():
    used = {"ABC", "ABD"}
    assert _fallback_code("Some Long Name", used, "optic-1") not in used


def _mma_primary() -> set[str]:
    return {"MMA", *(f"MMA{n}" for n in range(2, 10))}


def test_bootstrap_mints_extended_code_when_primary_slots_are_full(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write_optic(
        data / "optic_fixtures_odds.jsonl",
        "itf_men",
        (
            {"id": "OID-MM", "name": "Maximilian Marterer", "abbreviation": ""},
            {"id": "OID-OP", "name": "Opponent", "abbreviation": "OPP"},
        ),
    )
    overrides = bootstrap_empty_abbrs(
        data, "itf_men", Path(), seed_used=_mma_primary(),
    )
    code = overrides["OID-MM"]
    assert code not in _mma_primary()
    assert code.startswith("MMA")
    assert len(code) == 5


def test_bootstrap_raises_when_the_code_space_is_full(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write_optic(
        data / "optic_fixtures_odds.jsonl",
        "itf_men",
        (
            {"id": "OID-MM", "name": "Maximilian Marterer", "abbreviation": ""},
            {"id": "OID-OP", "name": "Opponent", "abbreviation": "OPP"},
        ),
    )
    used = {"MMA", *(f"MMA{n}" for n in range(2, 100))}
    with pytest.raises(ValueError, match="no free canonical code"):
        bootstrap_empty_abbrs(data, "itf_men", Path(), seed_used=used)


def test_bootstrap_pins_a_doubles_pair_not_each_player(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "optic_fixtures_odds.jsonl").write_text(json.dumps({
        "id": "fx1",
        "game_id": "g1",
        "start_date": "2026-09-22T18:00:00Z",
        "home_competitors": [
            {"id": "d2", "name": "Theodore Winegar", "abbreviation": ""},
            {"id": "d1", "name": "Jean-Julien Rojer", "abbreviation": ""},
        ],
        "away_competitors": [
            {"id": "a1", "name": "Other Side", "abbreviation": "OTH"},
        ],
        "league": {"id": "atp_doubles"},
        "odds": [],
    }) + "\n", encoding="utf-8")
    overrides = bootstrap_empty_abbrs(data, "atp_doubles", Path())
    assert "d1" not in overrides
    assert "d2" not in overrides
    assert overrides["d1+d2"]


def test_shared_abbr_longer_name_keeps_optic_abbr(tmp_path):
    """Nantes and Nancy both ship NAN; Nancy keeps it, Nantes gets a fallback."""
    data = tmp_path / "data"
    data.mkdir()
    nantes = "F55591A73993AEC0"
    nancy = "2CFB9C9E1EE9DE97"
    _write_optic(
        data / "optic_fixtures_odds.jsonl",
        "france_-_ligue_2",
        (
            {"id": nantes, "name": "FC Nantes", "abbreviation": "NAN"},
            {"id": nancy, "name": "AS Nancy-Lorraine", "abbreviation": "NAN"},
        ),
    )
    overrides = bootstrap_empty_abbrs(
        data, "france_-_ligue_2", Path(), seed_used={"EAG"},
    )
    assert overrides[nancy] == "NAN"
    assert overrides[nantes] != "NAN"
    assert overrides[nantes]


def test_pin_shared_optic_abbr_skips_already_overridden():
    used = {"NAN"}
    overrides = {"2CFB9C9E1EE9DE97": "NAN"}
    added = pin_shared_optic_abbr(
        ("F55591A73993AEC0", "FC Nantes", "NAN"),
        ("2CFB9C9E1EE9DE97", "AS Nancy-Lorraine", "NAN"),
        overrides,
        used,
    )
    assert len(added) == 1
    assert added[0][0] == "F55591A73993AEC0"
    assert added[0][1] != "NAN"
