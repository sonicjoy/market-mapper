"""The underlying row dict must carry every column the catalogue query selects."""

from datetime import UTC, datetime
from types import SimpleNamespace

from fetch.crypto_com_underlying import (
    UNDERLYING_CATALOGUE_QUERY,
    _underlying_row_to_dict,
)
from fetch.crypto_com_underlying_flat import infer_game_line_outcome


def _select_columns() -> list[str]:
    select = UNDERLYING_CATALOGUE_QUERY.split("FROM", 1)[0].replace("SELECT", "")
    return [c.strip() for c in select.split(",") if c.strip()]


def _row(**over) -> SimpleNamespace:
    row = SimpleNamespace(**{c: f"v-{c}" for c in _select_columns()})
    row.publish_time = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)
    for k, v in over.items():
        setattr(row, k, v)
    return row


def test_row_dict_carries_every_selected_column():
    assert set(_select_columns()) <= set(_underlying_row_to_dict(_row()))


def test_typed_game_line_survives_the_row_dict():
    row = _row(
        meta_predict_contract_type="Spread",
        meta_predict_outcome_type="Away",
        meta_predict_value="-2.5",
    )
    assert infer_game_line_outcome(_underlying_row_to_dict(row)) == ("Away", -2.5)
