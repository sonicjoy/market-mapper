"""A fixture's Optic player selections, matched by DKEX participant name."""

from __future__ import annotations

import re
from typing import Any

from mappers.canonical_codes import names_close, names_fit
from mappers.exchanges.dkex_names import OPTIC_PLAYER_IDS_BY_DKEX_NAME, player_alike
from mappers.shared import normalize_player_name


class PlayerPool:
    """A fixture's Optic player selections, matched by DKEX participant name.

    Optic's player selections include multi-player ones ("Jalen Hurts +
    DeVonta Smith"), which a loose name fit would also accept for "Jalen
    Hurts".  So the match is tiered, most specific first, and stops at
    the first tier that hits: the exact canonical name, then
    ``names_close``, then ``names_fit``.  A tier with more than one hit is
    ambiguous and resolves to nothing.
    """

    def __init__(self, fx: Any) -> None:
        self._shown = sorted({
            normalize_player_name(odd.selection)
            for odd in fx.odds
            if odd.player_id and odd.selection
        })
        # A multi-player selection is never one DKEX participant: it may
        # match a fuzzy tier (``C.J. Stroud`` fits ``cj_stroud_+_cameron_ward``)
        # and put a single player's market on a combo entity.
        # Optic also lists a player as ``<club> :: <player>``; that is the
        # same person, so it must not count as a second hit.
        plain = {s for s in self._shown if "+" not in s and _CLUB_SEP not in s}
        self._singles = sorted(plain | {
            s for s in self._shown
            if "+" not in s and _CLUB_SEP in s and s.split(_CLUB_SEP, 1)[1] not in plain})
        # "No Goalscorer" / "No Touchdown Scorer": Optic's affirmative-only
        # "nobody scores" selection carries no player id.
        self._nobody = {
            kw: sorted({normalize_player_name(odd.selection) for odd in fx.odds
                        if not odd.player_id and odd.selection
                        and odd.selection.lower().startswith("no ") and kw in odd.selection.lower()})
            for kw in ("goal", "touchdown")}
        self._by_id = {odd.player_id: normalize_player_name(odd.selection)
                       for odd in fx.odds if odd.player_id and odd.selection and "+" not in odd.selection
                       and " :: " not in odd.selection}
        self._cache: dict[str, str | None] = {}

    def resolve(self, participant_id: str, name: str) -> str | None:
        """Canonical player for a DKEX participant: a unique name match, else None."""
        if participant_id not in self._cache:
            self._cache[participant_id] = self._match(name)
        return self._cache[participant_id]

    def drop_collisions(self, participants: dict[str, str]) -> list[tuple[str, list[str]]]:
        """Resolve an event's player participants; drop any two that share a player.

        ``participants`` maps participant id -> name.  Two distinct DKEX
        players cannot be one Optic player, so when ids resolve to the same
        canonical name at least one fuzzy match is wrong and nothing says
        which: every id in the clash resolves to nothing, dropping its markets
        whole.  Returns ``(canonical, [participant names])`` per clash.
        """
        by_player: dict[str, list[str]] = {}
        for pid, name in participants.items():
            player = self.resolve(pid, name)
            if player is not None:
                by_player.setdefault(player, []).append(pid)
        clashes = []
        for player, pids in by_player.items():
            if len(pids) > 1:
                clashes.append((player, [participants[pid] for pid in pids]))
                for pid in pids:
                    self._cache[pid] = None
        return clashes

    def _match(self, name: str) -> str | None:
        # DKEX tags a participant with the team when two players share a
        # name: ``Emmett Mosley (TEX)``.
        tag = _position_tag(name or "")
        name = _TEAM_SUFFIX.sub("", name or "").strip()
        if not name:
            return None
        exact = normalize_player_name(name)
        if exact in self._shown:
            return exact
        # Two players can share a name ("Elias Pettersson (F)" / "(D)", Optic
        # "Elias Pettersson (C)" / "Elias Nils Pettersson").  A position tag on
        # both sides must agree, and a tagged Optic selection with this exact
        # name is that player, not a longer legal name that merely extends it.
        if tag is not None:
            same = {s for s in self._singles
                    if _optic_base(s) == exact and _optic_tag(s) is not None
                    and _tags_agree(tag, _optic_tag(s))}
            if len(same) == 1:
                return same.pop()
        pinned = {self._by_id[i] for i in OPTIC_PLAYER_IDS_BY_DKEX_NAME.get(name.casefold(), ()) if i in self._by_id}
        if len(pinned) == 1:
            return pinned.pop()
        low = name.lower()
        if low.startswith("no ") and "scorer" in low:
            kw = "goal" if "goal" in low else "touchdown" if "touchdown" in low else None
            hits = self._nobody.get(kw, []) if kw else []
            return hits[0] if len(hits) == 1 else None
        for fits in (names_close, names_fit):
            hits = {s for s in self._singles
                    if _tags_agree(tag, _optic_tag(s)) and fits(name, _optic_base(s), player=True)}
            if hits:
                return next(iter(hits)) if len(hits) == 1 else None
        for fits in (_nickname_fits, player_alike):
            hits = {s for s in self._singles if fits(exact, s)}
            if hits:
                return next(iter(hits)) if len(hits) == 1 else None
        return None


_CLUB_SEP = "_::_"
#: Trailing ``(TEX)`` DKEX appends to disambiguate two players of one name.
_TEAM_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")
#: Shortest first name accepted as the start of a longer one (``Cam`` / ``Cameron``).
_MIN_NICKNAME = 3


#: DKEX position tags, and the Optic tags that name the same kind of player.
#: Only these count as a position: a two-letter team code ("(KC)") does not.
_TAG_COMPATIBLE: dict[str, frozenset[str]] = {
    "F": frozenset({"F", "C", "W", "LW", "RW"}),
    "C": frozenset({"F", "C"}),
    "W": frozenset({"F", "W", "LW", "RW"}),
    "LW": frozenset({"F", "W", "LW"}),
    "RW": frozenset({"F", "W", "RW"}),
    "D": frozenset({"D"}),
    "G": frozenset({"G"}),
}
_DKEX_TAG = re.compile(r"\(([A-Za-z]{1,2})\)\s*$")
_OPTIC_TAG = re.compile(r"_\(([a-z]{1,2})\)$")


def _position_tag(name: str) -> str | None:
    """``"F"`` for ``"Elias Pettersson (F)"``; ``None`` for no tag or a team code."""
    m = _DKEX_TAG.search(name)
    tag = m.group(1).upper() if m else None
    return tag if tag in _TAG_COMPATIBLE else None


def _optic_tag(shown: str) -> str | None:
    """Position tag of a canonical Optic selection (``elias_pettersson_(c)`` -> ``"C"``)."""
    m = _OPTIC_TAG.search(shown)
    return m.group(1).upper() if m else None


def _optic_base(shown: str) -> str:
    """A canonical Optic selection without its position tag."""
    return _OPTIC_TAG.sub("", shown) if _optic_tag(shown) else shown


def _tags_agree(dkex_tag: str | None, optic_tag: str | None) -> bool:
    """False only when both sides carry a position and they name different ones."""
    if dkex_tag is None or optic_tag is None:
        return True
    return optic_tag in _TAG_COMPATIBLE[dkex_tag]


def _nickname_fits(want: str, shown: str) -> bool:
    """True for ``cam_skattebo`` vs ``cameron_skattebo``: same family name, one given name the start of the other."""
    a, b = want.split("_"), shown.split("_")
    if len(a) < 2 or len(b) < 2 or a[-1] != b[-1]:
        return False
    short, long_ = sorted((a[0], b[0]), key=len)
    return len(short) >= _MIN_NICKNAME and long_.startswith(short)
