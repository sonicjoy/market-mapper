"""Code-owned crypto.com team ids merge under the tip's crypto_id aliases."""

from mappers.exchanges.optic import Fixture
from mappers.pipeline import (
    ScheduleEntry,
    _crypto_alias_canonicals,
    _with_code_crypto_team_ids,
)
from mappers.vocab.crypto_team_ids import CRYPTO_TEAM_ID_OVERRIDES, CRYPTO_TEAM_IDS


def test_code_ids_fill_gaps_only():
    out = _with_code_crypto_team_ids({}, "ncaaf", {"TEX", "OKL"})
    assert out["50000109"] == "TEX"
    assert out["50000105"] == "OKL"


def test_tip_wins_on_conflict():
    out = _with_code_crypto_team_ids({"50000109": "OTHER"}, "ncaaf", {"TEX", "OTHER"})
    assert out["50000109"] == "OTHER"


def test_unknown_canonical_is_skipped():
    out = _with_code_crypto_team_ids({}, "ncaaf", set())
    assert "50000109" not in out


def test_other_leagues_untouched():
    tip = {"x": "Y"}
    assert _with_code_crypto_team_ids(tip, "nfl", {"Y"}) == tip


def test_table_is_one_canonical_per_id():
    for league, ids in CRYPTO_TEAM_IDS.items():
        assert all(isinstance(v, str) and v for v in ids.values()), league


def test_schedule_key_canonical_binds_without_tip_entity():
    """UEL/UECL keys like AZ have no tip entity; the pipeline passes the
    Optic schedule keys in `canonicals`, so the code id still binds."""
    out = _with_code_crypto_team_ids({}, "europa_league", {"AZ", "ARM"})
    assert out["90000679"] == "AZ"


def test_schedule_key_absent_still_skipped():
    out = _with_code_crypto_team_ids({}, "europa_conference_league", {"AJX"})
    assert "90000664" not in out   # ATA not on the schedule this run


def test_celje_not_bound_to_celta_key():
    """Optic keys NK Celje and RC Celta both CEL in europa_league; only
    Celta (90000622) may hold CEL, never Celje (90000816)."""
    uel = CRYPTO_TEAM_IDS["europa_league"]
    assert "90000816" not in uel
    assert [cid for cid, key in uel.items() if key == "CEL"] == ["90000622"]


def _entry(home: str, away: str) -> ScheduleEntry:
    return ScheduleEntry(Fixture(
        fixture_id="fx", game_id="g", sportradar_id=None,
        start_et="2026-10-22T12:45:00", start_date="2026-10-22T16:45:00Z",
        home=home, away=away, home_name=home, away_name=away,
        team_map={}, odds=[], is_live=False,
    ))


def test_call_site_canonicals_include_schedule_keys():
    """The set run() passes must reach schedule-only keys (AZ has no tip
    entity), or every UEL/UECL code id is skipped again."""
    canon = _crypto_alias_canonicals({"ARM"}, [_entry("ARM", "AZ")])
    assert canon == {"ARM", "AZ"}
    out = _with_code_crypto_team_ids({}, "europa_league", canon)
    assert out["90000679"] == "AZ"


def test_tennis_wu_binds_challenger_key():
    out = _with_code_crypto_team_ids({}, "atp_challenger", {"JCI9", "YWI5"})
    assert out["730131"] == "YWI5"


def test_override_beats_tip():
    tip = {"140005785": "GUG", "140005281": "KSO5"}
    out = _with_code_crypto_team_ids(tip, "ufc", {"GUG", "KSO5", "NGO7"})
    assert out["140005785"] == "NGO7"
    assert out["140005281"] == "KSO5"   # non-override tip ids untouched


def test_override_needs_known_canonical():
    tip = {"140005785": "GUG"}
    out = _with_code_crypto_team_ids(tip, "ufc", {"GUG"})
    assert out["140005785"] == "GUG"   # NGO7 not on the schedule: keep tip


def test_no_id_in_both_tables():
    for league, ids in CRYPTO_TEAM_ID_OVERRIDES.items():
        assert not set(ids) & set(CRYPTO_TEAM_IDS.get(league, {})), league


def test_ids_unique_per_canonical_within_league():
    """One canonical per team: two crypto ids on one key would mean two
    teams were bound to the same entity (the Celje/Celta trap)."""
    for league, ids in CRYPTO_TEAM_IDS.items():
        assert len(set(ids.values())) == len(ids), league
