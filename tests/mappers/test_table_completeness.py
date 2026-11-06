"""MarketType coverage invariants — every type is accounted for.

Catches accidental gaps when adding new market types or leagues.
Tests are parameterized over the LEAGUES registry so that new
league modules are automatically covered.

Invariants tested:
  - PX suffix list is longest-first (prevents shorter suffix matching
    before a longer one that contains it, e.g. " Points" before
    " Total Points")
  - OUTPUT_ORDER covers every MarketType member exactly once
  - _PX_TYPE_FOR_SHAPE covers every Shape (so classify_market's
    cross-check never hits None)
"""

import pytest

from mappers.exchanges.px import _PX_TYPE_FOR_SHAPE
from mappers.market_types import MarketType, Shape
from mappers.run import LEAGUES

_LEAGUE_IDS = sorted(LEAGUES)


# === Per-league invariants ===

@pytest.mark.parametrize("league_key", _LEAGUE_IDS)
def test_px_suffix_longest_first(league_key):
    """PX suffix list must be ordered by decreasing length.

    classify_market walks the list linearly and returns on first
    match.  A shorter suffix that appears before a longer one it's
    contained in would cause misclassification.
    """
    cfg = LEAGUES[league_key].PX
    if cfg is None:
        pytest.skip(f"{league_key} has no PX coverage")
    lengths = [len(s) for s, _ in cfg.suffix]
    assert lengths == sorted(lengths, reverse=True), (
        f"{league_key}: PX suffix list is not longest-first: "
        f"{[s for s, _ in cfg.suffix]}")


def _used_types(league) -> set[MarketType]:
    """Collect all MarketType values referenced by a league's exchange configs."""
    types: set[MarketType] = set()
    if league.PX is not None:
        types.update(league.PX.exact.values())
        types.update(mt for _, mt in league.PX.suffix)
    types.update(league.OPTIC.table_types.values())
    return types


@pytest.mark.parametrize("league_key", _LEAGUE_IDS)
def test_output_order_covers_all_used_types(league_key):
    """OUTPUT_ORDER must include every type used by the league's exchange configs.

    Types not in OUTPUT_ORDER get sort rank 99 (sorted to the end),
    which is fine for truly unused types but indicates a gap for types
    the league actually maps.
    """
    league = LEAGUES[league_key]
    order_set = set(league.OUTPUT_ORDER)
    used = _used_types(league)

    missing = used - order_set
    assert not missing, (
        f"{league_key}: MarketType values in exchange configs but "
        f"missing from OUTPUT_ORDER: "
        f"{sorted(mt.value for mt in missing)}")

    dupes = [mt for mt in league.OUTPUT_ORDER
             if league.OUTPUT_ORDER.count(mt) > 1]
    assert not dupes, (
        f"{league_key}: duplicates in OUTPUT_ORDER: "
        f"{sorted(mt.value for mt in set(dupes))}")


# === Global invariants (not per-league) ===

def test_px_type_for_shape_covers_all_shapes():
    """_PX_TYPE_FOR_SHAPE must have an entry for every Shape value.

    classify_market cross-checks PX's type field against this dict.
    A missing entry would raise at classification time for any
    MarketType with that shape.
    """
    missing = set(Shape) - set(_PX_TYPE_FOR_SHAPE)
    assert not missing, (
        f"Shape values missing from _PX_TYPE_FOR_SHAPE: "
        f"{sorted(s.value for s in missing)}")
