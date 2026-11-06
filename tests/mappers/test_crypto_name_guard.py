"""Crossed crypto_id vs catalogue name must not stamp."""

from mappers.exchanges.crypto_name_guard import skip_crossed_stamp


def test_skip_when_ids_are_swapped() -> None:
    names = {"NUR": "Umar Nurmagomedov", "SYO": "Song Yadong"}
    assert skip_crossed_stamp(
        "Song Yadong", "Umar Nurmagomedov", "NUR", "SYO", names, league="ufc",
    )


def test_keep_when_ids_match_names() -> None:
    names = {"NUR": "Umar Nurmagomedov", "SYO": "Song Yadong"}
    assert not skip_crossed_stamp(
        "Song Yadong", "Umar Nurmagomedov", "SYO", "NUR", names, league="ufc",
    )


def test_keep_fc_and_umlaut_spelling() -> None:
    names = {"LIV": "Liverpool", "NFO": "Nottingham Forest"}
    assert not skip_crossed_stamp(
        "Liverpool FC", "Nottingham Forest FC", "LIV", "NFO", names,
        league="england_premier_league",
    )
