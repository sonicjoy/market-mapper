"""Protected ("insurance") player props ride their base prop's Optic odd.

Optic never carries ``<base>_insurance``, so no Optic row exists for them and
the loader (which needs an Optic ``market_id`` to join on) would drop every
one.  The base prop is the same bet except for the protection rider, so the
insurance row takes the base row's Optic odd with ``_insurance`` appended to
``id`` and ``market_id``.  No base row, no stamp: missing > wrong.
"""

from __future__ import annotations

from collections.abc import MutableMapping

from mappers.exchanges.optic import GameRef, Odd
from mappers.shared import CanonicalRow

SUFFIX = "_insurance"


def stamp_insurance_rows(
    row_index: MutableMapping[tuple, CanonicalRow],
    odd_lookup: MutableMapping[str, Odd],
    game_ref_lookup: MutableMapping[str, GameRef],
) -> int:
    """Give each unstamped insurance row its base prop's suffixed Optic odd."""
    stamped = 0
    for key, row in list(row_index.items()):
        if row.optic_id is not None or not row.market_type.endswith(SUFFIX):
            continue
        base_key = (*key[:4], row.market_type.removesuffix(SUFFIX), *key[5:])
        base = row_index.get(base_key)
        odd = odd_lookup.get(base.optic_id) if base and base.optic_id else None
        ref = game_ref_lookup.get(base.optic_id) if base and base.optic_id else None
        if odd is None or ref is None:
            continue
        derived = odd.model_copy(update={
            "id": f"{odd.id}{SUFFIX}",
            "market_id": f"{odd.market_id}{SUFFIX}",
            "source_ids": {},
        })
        odd_lookup[derived.id] = derived
        game_ref_lookup[derived.id] = ref
        row.optic_id = derived.id
        stamped += 1
    return stamped
