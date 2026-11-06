"""One Optic side is one entity. A doubles side is the pair."""

from __future__ import annotations


def _person(row: dict) -> tuple[str, str, str]:
    """id, name, abbreviation from one competitor dict."""
    return (
        str(row.get("id") or "").strip(),
        str(row.get("name") or "").strip(),
        (row.get("abbreviation") or "").strip(),
    )


def fold_side(people: list) -> dict | None:
    """Collapse one side to a single competitor.

    A singles side is that player. A doubles side is one pair: a stable
    id from the member ids, the Optic name order joined with `` / ``,
    and every member id so odds for either player resolve to the pair.
    """
    rows = [_person(p) for p in people if isinstance(p, dict)]
    rows = [row for row in rows if row[0] or row[1]]
    if not rows:
        return None
    if len(rows) == 1:
        oid, name, abbr = rows[0]
        return {
            "id": oid,
            "name": name,
            "abbreviation": abbr,
            "member_ids": [oid] if oid else [],
        }
    return _pair_side(rows)


def _pair_side(rows: list[tuple[str, str, str]]) -> dict:
    """One pair entity. Differing abbreviations are left empty to mint."""
    ids = [oid for oid, _name, _abbr in rows if oid]
    names = [name for _oid, name, _abbr in rows if name]
    abbrs = {abbr for _oid, _name, abbr in rows if abbr}
    abbr = next(iter(abbrs)) if len(abbrs) == 1 else ""
    return {
        "id": "+".join(sorted(ids)),
        "name": " / ".join(names),
        "abbreviation": abbr,
        "member_ids": ids,
    }
