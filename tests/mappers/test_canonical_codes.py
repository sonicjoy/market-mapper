"""fallback_code keeps a crowded 3-letter base from aborting a league; tokens() folds ø / ß / æ."""

import re

import pytest

from mappers.canonical_codes import BASE_LETTER_FOLD, _code_base, fallback_code, names_fit, tokens
from mappers.shared import _BASE_LETTER_FOLD

_NAME = "Maximilian Marterer"


def _primary_full() -> set[str]:
    return {"MMA", *(f"MMA{n}" for n in range(2, 10))}


def test_fresh_name_stays_in_the_primary_nine_slots():
    code = fallback_code(_NAME, set(), "oid-marterer")
    assert code == "MMA" or re.fullmatch(r"MMA[2-9]", code)


def test_free_primary_slot_beats_an_extended_suffix():
    used = {"MMA", *(f"MMA{n}" for n in range(2, 9))}
    assert fallback_code(_NAME, used, "any-optic-id") == "MMA9"


def test_extended_suffix_when_primary_slots_are_full():
    used = _primary_full()
    code = fallback_code(_NAME, used, "oid-marterer")
    assert re.fullmatch(r"MMA[1-9][0-9]", code)
    assert code not in used
    assert fallback_code(_NAME, set(used), "oid-marterer") == code


def test_total_exhaustion_still_raises():
    used = {"MMA", *(f"MMA{n}" for n in range(2, 100))}
    with pytest.raises(ValueError, match="no free canonical code"):
        fallback_code(_NAME, used, "oid-marterer")


# === tokens(): letters NFKD cannot fold ===


def test_tokens_fold_letters_nfkd_leaves_whole():
    assert tokens("Lillestrøm SK") == ["Lillestrom", "SK"]
    assert tokens("Bodø/Glimt") == ["Bodo", "Glimt"]
    assert tokens("Brøndby IF") == ["Brondby", "IF"]
    assert tokens("ŁKS Łódź") == ["LKS", "Lodz"]
    assert tokens("São Paulo") == ["Sao", "Paulo"]


def test_folded_club_name_fits_optic_ascii_spelling():
    assert names_fit("Lillestrøm SK", "Lillestrom SK", player=False)
    assert not names_fit("Lillestrøm SK", "Molde FK", player=False)


def test_fold_table_matches_the_player_entity_fold():
    assert BASE_LETTER_FOLD == _BASE_LETTER_FOLD


def test_code_base_keeps_the_unfolded_words():
    # Codes are merge keys: a name coded before the fold keeps its base.
    assert _code_base("Lillestrøm SK") == "LMS"
