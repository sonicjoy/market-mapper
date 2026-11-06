"""Attach proposal evidence to one alias pin (same entity, same league)."""

from __future__ import annotations

_POLY_TEXT = frozenset({"slug", "question", "market", "outcome", "description"})
_CRYPTO_BOOKS = frozenset({"crypto", "crypto.com"})


def parse_ref(ref: str) -> tuple[str, str, str]:
    """Split evidence ref into head, mid, rest."""
    parts = ref.split(":", 2)
    if len(parts) < 2:
        return ref, "", ""
    if len(parts) == 2:
        return parts[0], parts[1], ""
    return parts[0], parts[1], parts[2]


def pin_alias_refs(
    own: list[str],
    extra: list[str],
    code: str,
    name: str,
    sportsbook: str,
    league: str = "",
) -> list[str]:
    """Source-book harvest refs; bag extras must be that book and the full name."""
    book_l = sportsbook.strip().lower()
    own_src = [ref for ref in own if _from_source(ref, book_l) or _note_ref(ref)]
    extras = [ref for ref in extra if _from_source(ref, book_l)]
    prefix = slug_prefix_from(own_src) or league_slug_prefix(league)
    matched = refs_for_alias(extras, code, name, sportsbook, slug_prefix=prefix)
    return list(dict.fromkeys([*own_src, *matched]))


def refs_for_alias(
    evidence: list[str],
    code: str,
    canonical_name: str,
    sportsbook: str = "",
    *,
    slug_prefix: str = "",
) -> list[str]:
    """Proposal-level refs that belong to this alias."""
    code_l = code.strip().lower()
    name_l = canonical_name.strip().lower()
    book_l = sportsbook.strip().lower()
    return [
        ref for ref in evidence
        if _ref_matches(ref, code_l, name_l, book_l, slug_prefix)
    ]


def league_slug_prefix(league: str) -> str:
    """Polymarket slug token for a mapping league (`itf_men` → `itf`)."""
    raw = (league or "").strip().lower()
    for suffix in ("_men", "_women"):
        if raw.endswith(suffix):
            return raw[: -len(suffix)]
    return raw


def slug_prefix_from(refs: list[str]) -> str:
    """First token of this pin's Polymarket slug, if harvest stored one."""
    for ref in refs:
        head, mid, rest = parse_ref(ref)
        if head != "polymarket" or mid != "slug" or not rest:
            continue
        token = rest.strip().lower().split("-", 1)[0]
        if token:
            return token
    return ""


def hay_mentions(hay: str, name_l: str) -> bool:
    """True when the text contains this alias's full name."""
    name = name_l.strip().lower()
    return bool(name) and name in hay.lower()


def _note_ref(ref: str) -> bool:
    return ref.startswith(("note:", "ai:", "AI suggestion"))


def _from_source(ref: str, book_l: str) -> bool:
    """True when the ref was produced by this pin's sportsbook."""
    if not book_l:
        return False
    head, mid, rest = parse_ref(ref)
    head_l = head.lower()
    if book_l in _CRYPTO_BOOKS:
        return head_l in {"crypto", "crypto_id"}
    if book_l == "polymarket_usa":
        return head_l == "polymarket_usa" or (head_l == "gap" and mid == "usa-inner")
    if book_l == "polymarket":
        return head_l == "polymarket"
    return head_l == book_l


def _same_slug_league(rest: str, slug_prefix: str) -> bool:
    if not slug_prefix:
        return True
    low = rest.strip().lower()
    return low.startswith(f"{slug_prefix}-") or low == slug_prefix


def _ref_matches(
    ref: str,
    code_l: str,
    name_l: str,
    book_l: str,
    slug_prefix: str,
) -> bool:
    if not _from_source(ref, book_l):
        return False
    # Match on `rest` only. The scheme prefix is not the alias name.
    head, mid, rest = parse_ref(ref)
    if head.lower() == "crypto_id":
        return mid.strip().lower() == code_l
    return (
        _crypto_ref_matches(head, mid, rest, code_l, name_l)
        or (head == "gap" and _gap_matches(rest, name_l, slug_prefix))
        or _poly_usa_ref_matches(head, mid, rest, code_l, name_l)
        or _poly_ref_matches(head, mid, rest, code_l, name_l, slug_prefix)
        or _optic_ref_matches(head, mid, rest, book_l, code_l, name_l)
    )


def _crypto_ref_matches(
    head: str,
    mid: str,
    rest: str,
    code_l: str,
    name_l: str,
) -> bool:
    """crypto:symbol is owned by the cid it is tagged with; the rest name it."""
    if head != "crypto":
        return False
    if mid == "symbol":
        cid, sep, _symbol = rest.partition(":")
        return bool(sep) and cid.strip().lower() == code_l
    return hay_mentions(rest, name_l)


def _poly_usa_ref_matches(
    head: str,
    mid: str,
    rest: str,
    code_l: str,
    name_l: str,
) -> bool:
    if head != "polymarket_usa":
        return False
    shown = rest.strip().lower()
    if mid == "code":
        return bool(code_l) and shown == code_l
    if mid == "name":
        return bool(name_l) and (shown == name_l or name_l in shown)
    return hay_mentions(rest, name_l)


def _poly_ref_matches(
    head: str,
    mid: str,
    rest: str,
    code_l: str,
    name_l: str,
    slug_prefix: str,
) -> bool:
    if head != "polymarket":
        return False
    if mid == "name":
        return bool(code_l) and rest.strip().lower() == code_l
    if mid not in _POLY_TEXT or not hay_mentions(rest, name_l):
        return False
    if mid == "slug":
        return _same_slug_league(rest, slug_prefix)
    return True


def _optic_ref_matches(
    head: str,
    mid: str,
    rest: str,
    book_l: str,
    code_l: str,
    name_l: str,
) -> bool:
    if head != "optic":
        return False
    if mid == "competitor":
        cid, _, shown = rest.partition(":")
        if book_l == "optic" and code_l and cid.lower() == code_l:
            return True
        return bool(name_l) and shown.strip().lower() == name_l
    if mid == "fixture":
        return hay_mentions(rest, name_l)
    return bool(name_l) and name_l in rest.lower()


def _gap_matches(rest: str, name_l: str, slug_prefix: str) -> bool:
    if not hay_mentions(rest, name_l):
        return False
    if "-" in rest.strip():
        return _same_slug_league(rest, slug_prefix)
    return True
