"""Detector for Polymarket handicap/spread name crumbs."""

from __future__ import annotations

from mappers.handicap_name_crumb import (
    bare_label,
    is_handicap_name_crumb,
    is_handicap_question,
    is_selection_alias,
    is_selection_question,
)


def test_handicap_name_crumb_signed_line() -> None:
    assert is_handicap_name_crumb("Mihalka (-1.5)")
    assert is_handicap_name_crumb("DV1 (+1.5)")
    assert not is_handicap_name_crumb("Anna Mihalka")
    assert not is_handicap_name_crumb("FC Porto (U21)")


def test_handicap_question_leads() -> None:
    assert is_handicap_question("Set Handicap: Mihalka (-1.5) vs Grubor (+1.5)")
    assert is_handicap_question("Map Handicap: DV1 (-1.5) vs Forsaken (+1.5)")
    assert not is_handicap_question("M15 Hurghada: Omar Kandil vs Lorenzo Lorusso")
    assert is_selection_question("US Open ATP: Completed Match: Tomas Etcheverry vs Jacob Fearnley")
    assert is_selection_question("Exact Score: Yunnan Yukun 0 - 3 Chongqing Tonglianglong FC?")
    assert is_selection_question("Austin FC to score first vs. Seattle Sounders FC?")
    assert is_selection_question("Austin FC vs. Seattle Sounders FC: Neither team to score first?")
    assert is_selection_question("Will there be a team to score in the first half?")
    assert is_selection_question("Sassuolo vs Frosinone: Both Teams to Score in Second Half")
    assert is_selection_question(
        "Counter-Strike: 3DMAX vs Infinite - Map 2 Winner",
    )
    assert is_selection_question(
        "LoL: Kits Esports vs SDM Tigres (BO3) - Game 2 Winner",
    )
    assert not is_selection_question(
        "Counter-Strike: Vitality vs 100 Thieves (BO1) - Esports World Cup Group C",
    )


def test_bare_label_strips_signed_line() -> None:
    assert bare_label("Shapovalov (-1.5)") == "Shapovalov"
    assert bare_label("Anna Mihalka") == "Anna Mihalka"


def test_selection_alias_excludes_market_outcomes() -> None:
    assert is_selection_alias("Shapovalov (-1.5)")
    assert is_selection_alias("Over 11.5")
    assert is_selection_alias("Under")
    assert is_selection_alias("Yes")
    assert is_selection_alias("2-0")
    assert is_selection_alias("Any Other Score")
    assert is_selection_alias("Austin FC to score first")
    assert is_selection_alias("FC Schalke 04 to score first")
    assert is_selection_alias("Austin FC to score first?")
    assert is_selection_alias("Both Teams to Score")
    assert is_selection_alias("Player to score 2+")
    assert not is_selection_alias("Denis Shapovalov")
    assert not is_selection_alias("RB Leipzig")
    assert not is_selection_alias("BIG")
    assert not is_selection_alias("Austin FC")
