"""Fail-closed unique name binds for gap harvest (Kalshi / crypto / Poly).

Bind keys are yearless, punctuation-folded words (split on space and
underscore). Collision on a key skips that key; no unique key → no pin.
Person names need two core tokens so a one-token label cannot bind.
A unique surname in a pair or slate is not identity when the needle already
has a given name (Francesco Ferrari ⊄ Gianmarco Ferrari).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from mappers.canonical_codes import names_fit, school_marks, tokens
from mappers.handicap_name_crumb import is_esports_map_winner
from mappers.vocab.esports_question import esports_series_sides
from mappers.vocab.soccer_question import soccer_draw_sides

PARTICLES = frozenset({
    "de", "del", "la", "el", "los", "las", "fc", "cf", "cd", "sc", "club",
    "united", "city", "the", "of", "and", "y", "da", "do", "di", "a", "al",
    "csyd", "cs", "ud", "ac", "as", "fk", "if", "bk", "sk", "il", "ca",
})
_DROP = PARTICLES | frozenset({"state", "university", "univ", "college"})
_MIN_TOKEN = 4
_YEAR = re.compile(r"^(19|20)\d{2}$")
_VS = re.compile(
    r"^(?:will\s+)?(?P<a>.+?)\s+(?:vs\.?|beat)\s+(?P<b>.+?)(?:\?|(?::.*))?$",
    re.I,
)
Side = Literal["home", "away"]


def alnum_words(name: str) -> list[str]:
    """Space/underscore words with punctuation stripped, lowercased."""
    out: list[str] = []
    for raw in re.split(r"[\s_]+", (name or "").strip()):
        folded = re.sub(r"[^a-z0-9]", "", raw.casefold())
        if folded:
            out.append(folded)
    return out


def name_bind_keys(name: str, *, person: bool = False) -> list[str]:
    """Ordered unique-bind keys: last yearless word, then first (people only).

    Person names with fewer than two core tokens return no keys (Rune).
    Clubs stay last-token so Santos ⊄ Santos Sao Paulo.
    """
    words = alnum_words(name)
    yearless = [w for w in words if not _YEAR.fullmatch(w)]
    core = [w for w in yearless if w not in _DROP]
    if person and len(core) < 2:
        return []
    keys: list[str] = []
    if not core:
        return keys
    for token in (core[-1],):
        if token in _DROP or len(token) < _MIN_TOKEN or token in keys:
            continue
        keys.append(token)
    if person and core[0] != core[-1]:
        token = core[0]
        if token not in _DROP and len(token) >= _MIN_TOKEN and token not in keys:
            keys.append(token)
    return keys


_CORE_DROP = frozenset(p.upper() for p in _DROP) | frozenset({
    "FC", "AFC", "CF", "SC", "CD", "UD", "AF", "BK", "IF", "AC", "CP",
    "UNITED", "CITY", "TOWN", "CLUB", "DE", "LA", "THE", "B",
})
_CLUB_FAMILY = frozenset({"REAL", "ATLETICO", "INTER"})
_SUFFIX_DRESSING = frozenset({"ATHLETIC", "CALCIO"})


def club_bind_name_ok(left: str, right: str) -> bool:
    """True when a short book label is a core prefix/suffix of the Optic name.

    Prefix: Bayern ⊂ Bayern Munich. Suffix extras are club dressing only
    (AD Ceuta, Athletic Club Bilbao) so Valencia ⊄ Other Valencia.
    Real/Atlético/Inter stay distinct (Madrid ⊄ Real Madrid).
    """
    if school_marks(left) != school_marks(right):
        return False
    shorter, _longer, extra, kind = _core_extend(left, right)
    if not shorter or extra is None or (set(extra) & _CLUB_FAMILY):
        return False
    if kind == "suffix":
        return all(len(token) <= 3 or token in _SUFFIX_DRESSING for token in extra)
    return True


def _club_cores(name: str) -> list[str]:
    """Yearless core tokens; particles and team noise dropped."""
    out: list[str] = []
    for raw in tokens(name):
        token = raw.upper()
        if token in _CORE_DROP or _YEAR.fullmatch(token):
            continue
        out.append(token)
    return out


def _core_extend(
    left: str, right: str,
) -> tuple[list[str], list[str], list[str] | None, str]:
    """Shorter/longer cores, extras, and prefix/suffix/equal — or None extras."""
    left_c, right_c = _club_cores(left), _club_cores(right)
    if not left_c or not right_c:
        return left_c, right_c, None, ""
    if left_c == right_c:
        return left_c, right_c, [], "equal"
    shorter, longer = (left_c, right_c) if len(left_c) <= len(right_c) else (right_c, left_c)
    n = len(shorter)
    if longer[:n] == shorter:
        return shorter, longer, longer[n:], "prefix"
    if longer[-n:] == shorter:
        return shorter, longer, longer[:-n], "suffix"
    return shorter, longer, None, ""


def unique_side(needle: str, home: str, away: str, *, person: bool) -> Side | Literal[""]:
    """Sole fixture side that is this entity, else empty.

    Exact string, then names_fit (people), then unique bind keys. A unique
    surname in the pair is not enough for a full person name.
    """
    side = _exact_side(needle, home, away)
    if side:
        return side
    if person:
        side = _fit_side(needle, home, away)
        if side:
            return side
    return _key_side(needle, home, away, person=person)


def person_unique_hit_ok(needle: str, chosen: str) -> bool:
    """True when a unique-key hit is the same person, not a shared surname.

    One-token needles have no given name to confirm (Jones and Ferrari are
    both surnames). Full names need names_fit, or every needle bind key
    (given + family) in the chosen *full* name so middle tokens count.
    """
    keys = name_bind_keys(needle, person=True)
    if not keys:
        return False
    if names_fit(needle, chosen, player=True):
        return True
    hay = _person_words(chosen)
    return all(k in hay for k in keys)


def expand_person_pair(
    left: str, right: str, full_names: list[str],
) -> tuple[str, str] | None:
    """Title sides expanded to unique full names, else None.

    One-token Kalshi fight titles (``Gibson vs Husain``) become the FIGHT
    yes_sub_title that contains that token. Length is not a signal.
    """
    a, b = expand_person_label(left, full_names), expand_person_label(right, full_names)
    if a and b and a != b:
        return a, b
    return None


def expand_person_label(needle: str, full_names: list[str]) -> str:
    """Unchanged full name, or the sole list entry containing this token."""
    text = (needle or "").strip()
    if not text:
        return ""
    if name_bind_keys(text, person=True):
        return text
    token = next(iter(_person_words(text)), "")
    if not token:
        return ""
    hits = [name for name in full_names if token in _person_words(name)]
    return hits[0] if len(hits) == 1 else ""


def _person_words(name: str) -> set[str]:
    """Yearless folded words from a person display name."""
    return {w for w in alnum_words(name) if not _YEAR.fullmatch(w)}


def _exact_side(needle: str, home: str, away: str) -> Side | Literal[""]:
    """home/away on casefold equality, else empty."""
    n, h, a = needle.casefold().strip(), home.casefold().strip(), away.casefold().strip()
    if n and n == h and n != a:
        return "home"
    if n and n == a and n != h:
        return "away"
    return ""


def _fit_side(needle: str, home: str, away: str) -> Side | Literal[""]:
    """home/away when names_fit hits exactly one side."""
    home_hit = names_fit(needle, home, player=True)
    away_hit = names_fit(needle, away, player=True)
    if home_hit and not away_hit:
        return "home"
    if away_hit and not home_hit:
        return "away"
    return ""


def _key_side(needle: str, home: str, away: str, *, person: bool) -> Side | Literal[""]:
    """home/away from a unique bind key that still names the same entity."""
    home_keys = set(name_bind_keys(home, person=person))
    away_keys = set(name_bind_keys(away, person=person))
    for key in name_bind_keys(needle, person=person):
        hits: list[Side] = []
        if key in home_keys:
            hits.append("home")
        if key in away_keys:
            hits.append("away")
        if len(hits) != 1:
            continue
        side = hits[0]
        chosen = home if side == "home" else away
        if person and not person_unique_hit_ok(needle, chosen):
            continue
        if _school_marks_ok(needle, chosen, person=person):
            return side
    return ""


def _school_marks_ok(needle: str, other: str, *, person: bool) -> bool:
    """People skip the check; clubs must share State/Tech/A&M marks."""
    return person or school_marks(needle) == school_marks(other)


def vs_sides(question: str) -> tuple[str, str] | None:
    """Two display names from a vs/beat question, else None.

    Tennis tournament prefixes (``M15 Hurghada: A vs B``) are stripped when
    the body after the last colon still matches; soccer ``A vs B: O/U`` keeps
    the full string so the line suffix does not become a side. Esports series
    titles use the live moneyline grammar (names stop at ``(BO<n>)``); per-map
    winners are not vs-name overlays. Soccer 3-way draw titles trail the market
    phrase after team B with no colon, so they use the live draw grammar.
    """
    text = (question or "").strip()
    if not text:
        return None
    if is_esports_map_winner(text):
        return None
    esports = esports_series_sides(text)
    if esports is not None:
        return esports
    draw = soccer_draw_sides(text)
    if draw is not None:
        return draw
    if ":" in text:
        body = text.rsplit(":", 1)[-1].strip()
        hit = _match_vs(body)
        if hit is not None:
            return hit
    return _match_vs(text)


def _match_vs(text: str) -> tuple[str, str] | None:
    """``a, b`` from a vs/beat string, else None."""
    match = _VS.match(text)
    if match is None:
        return None
    left, right = match.group("a").strip(), match.group("b").strip()
    if not left or not right:
        return None
    return left, right


def optic_side(
    title: str, idx: int, optic: dict[str, Any], *, player: bool = False,
) -> tuple[str, str]:
    """Map ticker code order onto Optic home/away via title names.

    Clubs keep substring containment (Valencia ⊂ Valencia CF). People use
    names_fit plus unique bind keys — never substring (Rune ⊄ Holger Rune),
    never a shared surname (Francesco ⊄ Gianmarco Ferrari), and never index
    fallback (missing > wrong).
    """
    core = title.split(":", 1)[0]
    parts = [p.strip() for p in core.replace(" vs. ", " vs ").split(" vs ", 1)]
    needle = parts[idx] if idx < len(parts) else ""
    home = str(optic.get("home") or "")
    away = str(optic.get("away") or "")
    home_id = str(optic.get("home_id") or "")
    away_id = str(optic.get("away_id") or "")
    if not needle:
        return "", ""
    home_hit = names_fit(needle, home, player=player)
    away_hit = names_fit(needle, away, player=player)
    if not player:
        folded = needle.casefold()
        home_hit = home_hit or folded in home.casefold()
        away_hit = away_hit or folded in away.casefold()
    if home_hit and not away_hit:
        return home, home_id
    if away_hit and not home_hit:
        return away, away_id
    side = unique_side(needle, home, away, person=player)
    if side == "home":
        return home, home_id
    if side == "away":
        return away, away_id
    return "", ""
