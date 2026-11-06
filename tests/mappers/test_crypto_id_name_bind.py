"""Catalogue EXTERNAL_*_ID in-memory pins onto Optic fixture sides."""

from __future__ import annotations

from mappers.crypto_id_name_bind import pin_crypto_ids_from_selections
from mappers.exchanges.crypto_com import Selection
from mappers.exchanges.optic import Fixture
from mappers.pipeline import ScheduleEntry
from mappers.shared import AliasValue, MatchKey

_DATE = "2026-05-19"
_HOME_ID = "140001001"
_AWAY_ID = "140001002"


def _entry() -> ScheduleEntry:
    fx = Fixture(
        fixture_id="ufc-fx-1",
        game_id="g1",
        sportradar_id=None,
        start_et=f"{_DATE}T20:00:00",
        start_date=f"{_DATE}T00:00:00Z",
        home="CKI",
        away="BRT",
        home_name="Giga Chikadze",
        away_name="Joanderson Brito",
        team_map={"oid-cki": "CKI", "oid-brt": "BRT"},
        odds=[],
        is_live=False,
    )
    return ScheduleEntry(fx)


def _selection() -> Selection:
    return Selection(
        security_id="1",
        symbol="NX.F.OPT.UFC-00013-260519-M.O.1.1.20261231",
        league="UFC",
        sport="MMA",
        start_date=f"{_DATE}T16:30:00Z",
        home_participant="Giga Chikadze",
        away_participant="Joanderson Brito",
        external_home_id=_HOME_ID,
        external_away_id=_AWAY_ID,
        external_game_id="NX.F.OPT.UFC-00013-260519",
        market_group="Fight Line",
        contract_type="Moneyline",
        period="Full Fight",
        outcome_type=None,
        value=None,
        selection_name="Giga Chikadze to win",
        crypto_market_id="m1",
        crypto_outcome_id="o1",
        participant="Giga Chikadze",
        player_id=_HOME_ID,
    )


def test_pin_crypto_ids_from_catalogue_names() -> None:
    entry = _entry()
    index = {MatchKey(_DATE, "CKI", "BRT"): [entry]}
    aliases: dict[str, AliasValue] = {}
    pinned = pin_crypto_ids_from_selections(
        {"egid": [_selection()]},
        index,
        aliases,
        player=True,
    )
    assert pinned == 2
    assert aliases[_HOME_ID] == "CKI"
    assert aliases[_AWAY_ID] == "BRT"


def test_pin_ufc_ring_name_onto_optic_legal_name() -> None:
    """Tina Black is the crypto.com label for Valesca Machado."""
    fx = Fixture(
        fixture_id="ufc-fx-machado",
        game_id="g-machado",
        sportradar_id=None,
        start_et=f"{_DATE}T20:00:00",
        start_date=f"{_DATE}T00:00:00Z",
        home="VMA5",
        away="MAE8",
        home_name="Valesca Machado",
        away_name="Melissa Amaya",
        team_map={"oid-vma": "VMA5", "oid-mae": "MAE8"},
        odds=[],
        is_live=False,
    )
    sel = _selection()
    sel.league = "UFC"
    sel.home_participant = "Tina Black"
    sel.away_participant = "Melissa Amaya"
    sel.external_home_id = "140001286"
    sel.external_away_id = "140005844"
    index = {MatchKey(_DATE, "VMA5", "MAE8"): [ScheduleEntry(fx)]}
    aliases: dict[str, AliasValue] = {"140005844": "MAE8"}
    pinned = pin_crypto_ids_from_selections(
        {"egid": [sel]}, index, aliases, player=True,
    )
    assert pinned == 1
    assert aliases["140001286"] == "VMA5"


def test_pin_crypto_ids_surname_spelling_variant() -> None:
    fx = Fixture(
        fixture_id="fx-shel",
        game_id="g-shel",
        sportradar_id=None,
        start_et=f"{_DATE}T10:00:00",
        start_date=f"{_DATE}T14:00:00Z",
        home="SHEL",
        away="LITU",
        home_name="Abdullah Shelbayh",
        away_name="Li Tu",
        team_map={"8029841F6C68": "SHEL", "3A8D00CF0E05": "LITU"},
        odds=[],
        is_live=False,
    )
    sel = _selection()
    sel.league = "ATP"
    sel.home_participant = "Abedallah Shelbayh"
    sel.away_participant = "Li Tu"
    sel.external_home_id = "1130651"
    sel.external_away_id = "385908"
    index = {MatchKey(_DATE, "SHEL", "LITU"): [ScheduleEntry(fx)]}
    aliases: dict[str, AliasValue] = {}
    pinned = pin_crypto_ids_from_selections(
        {"egid": [sel]}, index, aliases, player=True,
    )
    assert pinned == 2
    assert aliases["1130651"] == "SHEL"
    assert aliases["385908"] == "LITU"


def test_pin_skips_when_ids_already_mapped() -> None:
    entry = _entry()
    index = {MatchKey(_DATE, "CKI", "BRT"): [entry]}
    aliases: dict[str, AliasValue] = {_HOME_ID: "CKI", _AWAY_ID: "BRT"}
    assert pin_crypto_ids_from_selections(
        {"egid": [_selection()]}, index, aliases, player=True,
    ) == 0
