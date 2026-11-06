"""Polymarket US outcome identity read from the market ``title`` — the one exception.

Everywhere else Path 2 maps on typed gateway fields only. Four per-outcome
enums carry no typed outcome at all, though: ``ufc_method_of_victory``,
``ufc_method_of_finish``, ``ufc_round_of_victory``, ``ufc_round_of_finish``,
``soccer_game_exact_score`` / ``soccer_game_first_half_exact_score``,
``tennis_match_exact_score``, ``football_game_double_result`` and
``football_game_highest_scoring_quarter``. Each lists one Yes/No market per outcome
(or per round), and the only thing telling
"Hiestand by Decision" from "Hiestand by Submission" is text: ``title``
(= ``titleShort``), ``question``, ``description`` and the slug. The sides
say only Yes / No, there is no participant id or metadata, and Optic
carries no ``Polymarket (USA)`` passthrough for them (gateway checked
2026-09-27).

Ruled 2026-09-27: map them from ``title``, strictly, Yes side only.

How:

* **Closed grammar.** Each enum accepts exactly the title shapes the venue
  publishes (inventoried on the 2026-09-26 snapshot, every market of every
  group); anything else — ``Other``, a new wording, a typo — drops. We never
  parse the slug, and never fall back to the question or description.
* **Names checked against typed teams.** A fighter, player or club named in
  the title must fit exactly one of the event's two typed ``teams``; the
  side then comes from that team's bind, the same as every typed market.
  This drops stale titles: on 2026-09-26 an Amaya vs Black group still read
  "V. Machado by …" and an Aguilar vs Barrena group "Cardozo wins 2-0",
  left over from a late opponent change.
* **Yes only.** A No is the union of every other outcome in the group,
  never one Optic selection, so only the Yes side is stamped (and the
  complement pass skips these market types). The exception is round of
  finish: "ends before Round N begins" is a true binary, exactly Optic
  ``to_start_round_N`` with Yes/No swapped, so both of its sides map.
  Likewise ``esports_game_kills_odd_even_N``: one market, Yes = odd, No =
  even; its title is checked only to confirm that fixed outcome.

Why not elsewhere: text is not part of the venue contract and can change
without notice. The grammar is kept small on purpose, so a wording change
makes the market unmapped instead of wrongly mapped (missing > wrong).
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from mappers.canonical_codes import tokens
from mappers.exchanges.polymarket_usa_records import UsMarket, UsTeam
from mappers.fight_props import (
    METHOD_DECISION,
    METHOD_KO_TKO_DQ,
    METHOD_SUBMISSION,
    canonicalize_fight_prop_key,
)
from mappers.market_types import MarketType
from mappers.shared import TIE_SIDE, correct_score_line

# Venue method label → canonical key (``mappers.fight_props``). The venue's
# KO/TKO/DQ is Optic's "KO/TKO/DQ" bucket, not its plain "KO/TKO".
_METHODS: dict[str, str] = {
    "decision": METHOD_DECISION,
    "ko/tko/dq": METHOD_KO_TKO_DQ,
    "submission": METHOD_SUBMISSION,
}

_MOV_RE = re.compile(r"^(?P<who>.+?) by (?P<method>Decision|KO/TKO/DQ|Submission)$")
_WINS_RE = re.compile(r"^(?P<who>\S.*?) wins (?P<w>\d{1,2})-(?P<l>\d{1,2})(?P<rest>.*)$")
_DRAW_RE = re.compile(r"^Draw (?P<w>\d{1,2})-(?P<l>\d{1,2})(?P<rest>.*)$")
_FIRST_HALF = " in 1st half"
_ROV_RE = re.compile(r"^(?P<who>\S.*?) in Round (?P<n>[1-5])$")
_ROF_RE = re.compile(r"^Fight ends before Round (?P<n>[2-5]) begins$")
# "ARI 1H / NYG Game", "ARI 1H / Tie", "1H Tie / NYG Game", "1H Tie / Tie".
_HTFT_RE = re.compile(r"^(?:(?P<ht>[A-Za-z0-9]+) 1H|1H Tie) / (?:(?P<ft>[A-Za-z0-9]+) Game|Tie)$")
_HSQ_RE = re.compile(r"^(?P<n>1st|2nd|3rd|4th) Quarter$")
# Records (league listing) and the market lookup word it differently.
_ODD_RE = re.compile(r"^(?:Odd total kills in game (?P<a>[1-5])|Game (?P<b>[1-5]) Total Kills Odd)$")

# (team_id, winner_goals, loser_goals); team_id "" = the draw.
Scoreline = tuple[str, int, int]


def _upper_tokens(text: str) -> list[str]:
    """Accent-folded word tokens, upper-cased."""
    return [t.upper() for t in tokens(text)]


def _team_names(team: UsTeam) -> list[list[str]]:
    """Token lists of every typed name the team carries."""
    names = (team.name, *team.alt_names)
    return [toks for toks in (_upper_tokens(n) for n in names) if toks]


def _initials_surname_fit(short: list[str], full: list[str]) -> bool:
    """``B. Hiestand`` against ``Brady Hiestand``: surname tail + initials."""
    k = 0
    while k < len(short) and len(short[k]) == 1:
        k += 1
    inits, surname = short[:k], short[k:]
    if not surname or len(full) < len(surname) + len(inits):
        return False
    given = full[: len(full) - len(surname)]
    return (
        full[len(given):] == surname
        and len(given) >= len(inits)
        and [g[0] for g in given[: len(inits)]] == inits
    )


def _unique_team(market: UsMarket, who: str) -> str | None:
    """The one typed team ``who`` names (initials + surname), else None."""
    short = _upper_tokens(who)
    if not short:
        return None
    hits = {
        t.team_id for t in market.teams
        if any(_initials_surname_fit(short, full) for full in _team_names(t))
    }
    return next(iter(hits)) if len(hits) == 1 else None


def _abbr_team(market: UsMarket, code: str) -> str | None:
    """The one typed team whose ``abbreviation`` is ``code``, else None."""
    want = code.strip().casefold()
    hits = {t.team_id for t in market.teams if t.abbreviation.casefold() == want}
    return next(iter(hits)) if want and len(hits) == 1 else None


def mov_outcome(market: UsMarket) -> tuple[str, str] | None:
    """``<I. Surname> by <Method>`` → (team_id, method key).

    The group's ``Draw`` leg is not mapped: Optic emits no method_of_victory
    draw row (``fight_props.is_emittable_method``).
    """
    match = _MOV_RE.match(market.title.strip())
    if match is None:
        return None
    team = _unique_team(market, match["who"])
    method = _METHODS.get(match["method"].casefold())
    return (team, method) if team and method else None


def mof_outcome(market: UsMarket) -> str | None:
    """``Decision`` / ``KO/TKO/DQ`` / ``Submission`` → method key.

    Settles on how the fight ends, by either fighter. ``Decision`` excludes
    a draw, which Optic's method_of_ending lists as its own outcome.
    """
    return _METHODS.get(market.title.strip().casefold())


def rov_outcome(market: UsMarket) -> tuple[str, int] | None:
    """``<Surname> in Round N`` → (team_id, N).

    The group's "Decision / Draw / No Contest" leg is not mapped: Optic
    round_betting has no single selection for it.
    """
    match = _ROV_RE.match(market.title.strip())
    if match is None:
        return None
    team = _unique_team(market, match["who"])
    return (team, int(match["n"])) if team else None


def rof_round(market: UsMarket) -> int | None:
    """``Fight ends before Round N begins`` → N."""
    match = _ROF_RE.match(market.title.strip())
    return int(match["n"]) if match else None


def exact_score_outcome(
    market: UsMarket, *, first_half: bool, by_abbreviation: bool,
) -> Scoreline | None:
    """``<who> wins W-L`` or ``Draw N-N`` (+ `` in 1st half``) → scoreline.

    ``who`` is the team abbreviation (soccer) or the player's surname
    (tennis). ``Other`` and any other shape drop; the period suffix must
    match the enum exactly.
    """
    title = market.title.strip()
    suffix = _FIRST_HALF if first_half else ""
    draw = _DRAW_RE.match(title)
    if draw is not None:
        w, lo = int(draw["w"]), int(draw["l"])
        return ("", w, lo) if draw["rest"] == suffix and w == lo else None
    wins = _WINS_RE.match(title)
    if wins is None or wins["rest"] != suffix:
        return None
    w, lo = int(wins["w"]), int(wins["l"])
    if w <= lo:
        return None
    who = wins["who"]
    team = _abbr_team(market, who) if by_abbreviation else _unique_team(market, who)
    return (team, w, lo) if team else None


def htft_outcome(market: UsMarket) -> tuple[str, str] | None:
    """``<ABBR> 1H / <ABBR> Game`` (either may be ``Tie``) → (1H team_id, FT team_id).

    '' stands for the tie. Abbreviations must name one typed team each.
    """
    match = _HTFT_RE.match(market.title.strip())
    if match is None:
        return None
    out = []
    for code in (match["ht"], match["ft"]):
        team = _abbr_team(market, code) if code else ""
        if team is None:
            return None
        out.append(team)
    return out[0], out[1]


def hsq_quarter(market: UsMarket) -> str | None:
    """``Nth Quarter`` → ``qN``."""
    match = _HSQ_RE.match(market.title.strip())
    return f"q{match['n'][0]}" if match else None


def odd_kills_map(market: UsMarket) -> int | None:
    """Map number of an "odd total kills" market, else None."""
    match = _ODD_RE.match(market.title.strip())
    return int(match["a"] or match["b"]) if match else None


TITLE_KINDS = frozenset({
    "mov", "mof", "rov", "rof", "exact_score", "exact_score_1h", "tennis_exact_score",
    "double_result", "hsq", "odd_even",
})


def _rov_bets(
    market_type: str, market: UsMarket, team_sides: Mapping[str, str],
    side_names: Mapping[str, str],
) -> list[tuple]:
    """Optic keys round_betting on ITS fighter name ("Brady Hiestand :: 1st Round")."""
    rov = rov_outcome(market)
    side = team_sides.get(rov[0]) if rov else None
    name = side_names.get(side) if side else None
    if rov is None or not name:
        return []
    key = canonicalize_fight_prop_key(f"{name} :: {rov[1]} Round")
    return [(market_type, None, None, "yes", key)]


def _rof_bets(market: UsMarket) -> list[tuple]:
    """Venue Yes (ends before round N) = Optic to_start_round_N No, and back."""
    n = rof_round(market)
    if n is None:
        return []
    flip = {"yes": "no", "no": "yes"}
    sides = [flip.get(s.description.strip().casefold()) for s in market.sides]
    if sorted(s for s in sides if s) != ["no", "yes"] or len(sides) != 2:
        return []
    mt = MarketType(f"to_start_round_{n}").value
    return [(mt, None, None, side) for side in sides]


def _htft_bets(
    market_type: str, market: UsMarket, team_sides: Mapping[str, str],
) -> list[tuple]:
    """Yes of one halftime / full-time outcome, keyed like Optic's."""
    outcome = htft_outcome(market)
    if outcome is None:
        return []
    sides = [team_sides.get(t) if t else TIE_SIDE for t in outcome]
    if not all(sides):
        return []
    return [(market_type, None, None, "yes", "|".join(str(s) for s in sides))]


def _outcome_bets(
    market_type: str, market: UsMarket, team_sides: Mapping[str, str], kind: str,
) -> list[tuple]:
    """Halftime / full time and highest-scoring quarter (Yes only); odd kills."""
    if kind == "double_result":
        return _htft_bets(market_type, market, team_sides)
    if kind == "hsq":
        quarter = hsq_quarter(market)
        return [(market_type, None, None, "yes", quarter)] if quarter else []
    n = odd_kills_map(market)
    if n is None or MarketType(market_type) is not MarketType[f"MAP_{n}_KILLS_ODD"]:
        return []
    sides = sorted(s.description.strip().casefold() for s in market.sides)
    if sides != ["no", "yes"]:
        return []
    return [(market_type, None, None, "yes"), (market_type, None, None, "no")]


def title_bets(
    market_type: str,
    market: UsMarket,
    team_sides: Mapping[str, str],
    kind: str,
    side_names: Mapping[str, str] | None = None,
) -> list[tuple]:
    """Bets of a title-identified market; ``team_sides`` = team_id → fx side.

    ``side_names`` = fx side → Optic competitor name (round of victory).
    Fight methods / rounds are 5-tuples (the outcome is Optic's
    grouping_key); exact scores are ``(type, None, W.LL, side)`` like
    Optic's correct-score rows.
    """
    if kind == "rov":
        return _rov_bets(market_type, market, team_sides, side_names or {})
    if kind == "rof":
        return _rof_bets(market)
    if kind in ("double_result", "hsq", "odd_even"):
        return _outcome_bets(market_type, market, team_sides, kind)
    if kind == "mov":
        mov = mov_outcome(market)
        side = team_sides.get(mov[0]) if mov else None
        return [(market_type, side, None, "yes", mov[1])] if mov and side else []
    if kind == "mof":
        method = mof_outcome(market)
        return [(market_type, None, None, "yes", method)] if method else []
    score = exact_score_outcome(
        market,
        first_half=kind == "exact_score_1h",
        by_abbreviation=kind != "tennis_exact_score",
    )
    if score is None:
        return []
    team_id, w, lo = score
    side = team_sides.get(team_id) if team_id else TIE_SIDE
    return [(market_type, None, correct_score_line(w, lo), side)] if side else []
