"""Canonical short codes for competitors, and TOML-safe key checks.

Leaf module: imports nothing from mappers, so both the bootstraps and the
control plane can use it. team_bootstrap owns the TOML writing; this owns
only the naming rules the two sides must agree on.
"""

import hashlib
import re
import unicodedata

# Canonical codes are at most 5 chars (the old counter truncated there).
# The first 9 slots stay the hashed walk: slot 0 is the bare base, slots
# 1-8 are {base}2..{base}9. A shorter base that has filled those nine
# continues at {base}10.. up to CODE_WIDTH (MMA10..MMA99), so one crowded
# prefix cannot abort the league.
CODE_WIDTH = 5
SUFFIX_SLOTS = 9

# Bare TOML table headers only. optic_from_bq falls back empty abbrs to the
# display name; stubbing that unquoted (e.g. [Rubio Nu]) is invalid TOML and
# corrupts the file for every later load. Pin those with a short bare code +
# optic_id instead (see config/paraguay_primera_division/team_aliases.toml).
_BARE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Longest section key across every config/*/team_aliases.toml is 6 chars, so
# anything longer is a display name, not an abbreviation.  Quotes, backslashes
# and control chars would need escaping — skip those rather than emit them.
ABBR_MAX_LEN = 6
_UNQUOTABLE_RE = re.compile(r'[\s"\\\x00-\x1f]')


def is_valid_bare_key(abbr: str) -> bool:
    """Whether ``abbr`` is safe as an unquoted TOML table header."""
    return bool(_BARE_KEY_RE.match(abbr))


def toml_section_key(abbr: str) -> str | None:
    """TOML table header for ``abbr``, or None if it needs a hand-pinned code.

    Accented Optic abbreviations (KÍ, ŽAL) and dotted esports codes (GEN.GA)
    are real abbreviations that only need quoting; skipping them leaves the
    completeness gate to abort the league every tick.  A name fallback
    ("Rubio Nu") is longer than any abbreviation and still gets skipped.
    """
    if is_valid_bare_key(abbr):
        return abbr
    if len(abbr) > ABBR_MAX_LEN or _UNQUOTABLE_RE.search(abbr):
        return None
    return f'"{abbr}"'


_TEAM_NOISE = frozenset({
    "FC", "AFC", "CF", "SC", "CD", "UD", "AF", "BK", "IF", "AC", "CP",
    "UNITED", "CITY", "TOWN", "CLUB", "DE", "LA", "THE", "B",
})
_SCHOOL_MARK = frozenset({"STATE", "TECH"})


# Latin letters NFKD leaves whole: no combining mark to strip, so the
# [A-Za-z0-9] split cut the word at them ("Lillestrøm" read as Lillestr + m
# and never fit Optic's "Lillestrom SK"; PolyUS uel-lms-rsss 2026-10-22).
# Same hand-audited set as mappers/shared.py _BASE_LETTER_FOLD (player
# entities); a test keeps the two equal. Kept here because this module is a
# leaf and shared.py changes rebuild the dkex-catalogue / ai-validation images.
BASE_LETTER_FOLD = str.maketrans({
    "ı": "i", "ß": "ss", "ø": "o", "Ø": "O", "ł": "l", "Ł": "L",
    "đ": "d", "Đ": "D", "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe",
    "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th",
})


def _ascii_words(name: str) -> list[str]:
    """[A-Za-z0-9] words after NFKD accent stripping only."""
    folded = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.findall(r"[A-Za-z0-9]+", ascii_name)


def tokens(name: str) -> list[str]:
    """Alphanumeric word tokens; accents fold so São ↔ Sao, Lillestrøm ↔ Lillestrom."""
    return _ascii_words(name.translate(BASE_LETTER_FOLD))


_PERSON = ("itf", "atp", "wta", "tennis", "ufc", "boxing", "mma", "darts")


def person_league(league: str) -> bool:
    """True when aliases are people (fighters/players), not clubs."""
    needle = league.lower()
    return any(part in needle for part in _PERSON)


def names_close(left: str, right: str, *, player: bool) -> bool:
    """True when display names are the same person/club, not a code collision."""
    at = [t.upper() for t in tokens(left)]
    bt = [t.upper() for t in tokens(right)]
    if not at or not bt:
        return False
    if at == bt:
        return True
    if player:
        return _player_names_close(at, bt)
    core_a = [t for t in at if t not in _TEAM_NOISE]
    core_b = [t for t in bt if t not in _TEAM_NOISE]
    return bool(core_a) and core_a == core_b


def school_marks(name: str) -> frozenset[str]:
    """Distinctive school tokens that are not legal-name suffixes."""
    words = [t.upper() for t in tokens(name)]
    marks = set(words) & _SCHOOL_MARK
    if any(words[i] == "A" and words[i + 1] == "M" for i in range(len(words) - 1)):
        marks.add("AM")
    return frozenset(marks)


def club_name_extends(left: str, right: str) -> bool:
    """True when one club name is the other plus a suffix (Côte d'Azur, 1901).

    Needs two shared core tokens so Santos ⊄ Santos Sao Paulo.
    State/Tech/A&M are not optional suffixes (North Carolina ⊄ NC State).
    """
    core_a = [t.upper() for t in tokens(left) if t.upper() not in _TEAM_NOISE]
    core_b = [t.upper() for t in tokens(right) if t.upper() not in _TEAM_NOISE]
    if len(core_a) < 2 or len(core_b) < 2:
        return False
    if school_marks(left) != school_marks(right):
        return False
    shorter, longer = (core_a, core_b) if len(core_a) <= len(core_b) else (core_b, core_a)
    return longer[: len(shorter)] == shorter


def club_and_spelling(left: str, right: str) -> bool:
    """True when the only difference is the word and (Bosnia and Herzegovina).

    Remaining cores must be equal, so Bosnia and Herzegovina does not match
    Bosnia. Does not loosen names_close.
    """
    if school_marks(left) != school_marks(right):
        return False
    core_a = [t.upper() for t in tokens(left) if t.upper() not in _TEAM_NOISE]
    core_b = [t.upper() for t in tokens(right) if t.upper() not in _TEAM_NOISE]
    if core_a.count("AND") + core_b.count("AND") != 1:
        return False
    bare_a = [word for word in core_a if word != "AND"]
    bare_b = [word for word in core_b if word != "AND"]
    return bool(bare_a) and bare_a == bare_b


def club_saint_spelling(left: str, right: str) -> bool:
    """True when the only difference is St versus Saint.

    Remaining cores must be equal, so St. Vincent does not match Saint
    Vincent and the Grenadines. Does not loosen names_close.
    """
    if school_marks(left) != school_marks(right):
        return False
    core_a = _saint_core(left)
    core_b = _saint_core(right)
    if len(core_a) < 2 or core_a != core_b:
        return False
    raw_a = [t.upper() for t in tokens(left) if t.upper() not in _TEAM_NOISE]
    raw_b = [t.upper() for t in tokens(right) if t.upper() not in _TEAM_NOISE]
    return raw_a != raw_b


def _saint_core(name: str) -> list[str]:
    """Club tokens with St folded to Saint, noise words dropped."""
    out: list[str] = []
    for raw in tokens(name):
        piece = raw.upper()
        if piece in _TEAM_NOISE:
            continue
        out.append("SAINT" if piece == "ST" else piece)
    return out


def person_name_extends(left: str, right: str) -> bool:
    """True when one person name is the other plus middle/extra family tokens.

    All shorter tokens appear in order in the longer. Needs two tokens so
    Rune ⊄ Holger Rune. Does not loosen names_close.
    """
    at = [t.upper() for t in tokens(left)]
    bt = [t.upper() for t in tokens(right)]
    if len(at) < 2 or len(bt) < 2 or len(at) == len(bt):
        return False
    shorter, longer = (at, bt) if len(at) < len(bt) else (bt, at)
    return _tokens_in_order(shorter, longer)


def person_name_concat(left: str, right: str) -> bool:
    """One spelling is a single token; the other joins the same tokens (Alatengheili)."""
    at = [t.upper() for t in tokens(left)]
    bt = [t.upper() for t in tokens(right)]
    if len(at) == 1 and len(bt) >= 2:
        return at[0] == "".join(bt)
    if len(bt) == 1 and len(at) >= 2:
        return bt[0] == "".join(at)
    return False


def _surname_initials_fit(full: list[str], short: list[str]) -> bool:
    """``short`` is ``Surname I. [I.]`` and ``full`` is ``Given [Middle] Surname``."""
    k = 0
    while k < len(short) and len(short[-1 - k]) == 1:
        k += 1
    surname, inits = short[: len(short) - k], short[len(short) - k:]
    if not k or not surname or len(full) < len(surname) + len(inits):
        return False
    given = full[: len(full) - len(surname)]
    return (
        full[len(given):] == surname
        and [g[0] for g in given[: len(inits)]] == inits
    )


def person_surname_initials(left: str, right: str) -> bool:
    """Optic's short fighter form (Richards C.) against the full name.

    The surname tokens must equal the full name's trailing tokens and every
    initial must start the given names in order (Tapia C. M. = Cesar Mateo
    Tapia). Not part of :func:`names_fit`; callers opt in.
    """
    at = [t.upper() for t in tokens(left)]
    bt = [t.upper() for t in tokens(right)]
    return _surname_initials_fit(at, bt) or _surname_initials_fit(bt, at)


def names_fit(left: str, right: str, *, player: bool) -> bool:
    """names_close, or a legal-name extension a human should review."""
    if names_close(left, right, player=player):
        return True
    if player:
        return person_name_extends(left, right) or person_name_concat(left, right)
    return (
        club_name_extends(left, right)
        or club_and_spelling(left, right)
        or club_saint_spelling(left, right)
    )


def _tokens_in_order(needle: list[str], haystack: list[str]) -> bool:
    """True when every needle token appears in order in haystack."""
    i = 0
    for tok in haystack:
        if i < len(needle) and tok == needle[i]:
            i += 1
    return i == len(needle)


def _player_names_close(at: list[str], bt: list[str]) -> bool:
    """Same first+last, or reversed given-name / family-name order."""
    if len(at) < 2 or len(bt) < 2:
        return False
    if at[0] == bt[0] and at[-1] == bt[-1]:
        return True
    return at[0] == bt[-1] and at[-1] == bt[0]


def _code_base(name: str) -> str:
    """Short prefix fallback_code hashes slots against.

    Unfolded on purpose: codes are merge keys, so a name must keep the
    base it was coded under before tokens() folded ø / ß / æ.
    """
    toks = _ascii_words(name)
    if not toks:
        return "X"
    if len(toks) == 1:
        token = toks[0].upper()
        return token[:3] if len(token) >= 3 else token
    initials = "".join(token[0].upper() for token in toks)
    if len(initials) >= 3:
        return initials[:4]
    first = toks[0].upper()
    return (initials + first[1:])[:3] or initials


def _code_for_slot(base: str, slot: int) -> str | None:
    """Code for one slot, or None when it would exceed CODE_WIDTH."""
    code = base if slot == 0 else f"{base}{slot + 1}"
    if len(code) > CODE_WIDTH:
        return None
    return code


def _max_slot(base: str) -> int:
    """Highest slot index whose code still fits in CODE_WIDTH."""
    if len(base) > CODE_WIDTH:
        return -1
    room = CODE_WIDTH - len(base)
    if room <= 0:
        return 0
    return (10 ** room) - 2


def _candidate_codes(base: str, seed: int) -> list[str]:
    """Primary 9 slots first, then wider suffixes in seed order."""
    codes: list[str] = []
    for offset in range(SUFFIX_SLOTS):
        code = _code_for_slot(base, (seed + offset) % SUFFIX_SLOTS)
        if code is not None:
            codes.append(code)
    extra = list(range(SUFFIX_SLOTS, _max_slot(base) + 1))
    if not extra:
        return codes
    start = seed % len(extra)
    for offset in range(len(extra)):
        code = _code_for_slot(base, extra[(start + offset) % len(extra)])
        if code is not None:
            codes.append(code)
    return codes


def fallback_code(name: str, used: set[str], optic_id: str) -> str:
    """Invent a short canonical code that does not collide with used.

    Suffix is seeded from optic_id so discovery order can't swap two
    competitors onto each other's codes. Bare base is one of the hashed
    primary slots, not first-come. A full primary family (MMA..MMA9)
    continues at MMA10.. while the code stays within CODE_WIDTH.
    """
    base = _code_base(name)
    seed = int(
        hashlib.sha1(optic_id.encode(), usedforsecurity=False).hexdigest(),
        16)
    for code in _candidate_codes(base, seed):
        if code not in used:
            return code
    raise ValueError(
        f"no free canonical code for {name!r} (base {base!r})")
