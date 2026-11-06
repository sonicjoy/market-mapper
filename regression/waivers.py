"""Load, validate, and apply waivers: reviewed excuses for gate deltas.

A waiver excuses a bounded, named region of expected difference when
gating a candidate against the blessed baseline (README: gate
policy).  This module enforces the mechanical half of the seven-rule
policy in HISTORY.md step 4:

- Predicates are narrow by construction: ``direction``, ``league``
  and ``sportsbook`` are required; a waiver that could blanket-match
  is a file error, not a style complaint (rule 4).
- ``max_rows`` bounds how much a waiver may excuse.  A waiver
  matching MORE deltas than its ceiling is BREACHED and excuses
  nothing — a regression inside excused territory must not hide
  under the excuse that let it in.
- ``expires`` bounds trust in time.  An expired waiver stops
  matching (its deltas return to UNEXPLAINED); it does not fail the
  file by itself, because its deltas may have meanwhile disappeared
  — then it is merely stale.  Expiry more than 90 days out is
  rejected at load: a far-future expiry is a politely deleted gate.
  (Monotone-safe: a file that loads today still loads tomorrow.)
- Unknown keys anywhere are rejected — a typo'd condition would
  otherwise silently WIDEN the waiver it meant to narrow.

Matching is purely mechanical field comparison (rule 2): a delta is
waived iff some active waiver's every condition holds.  When several
match, the first in file order takes it (deterministic attribution).
The lifecycle half of the policy (born in the MR it excuses, dies in
the re-bless commit, renewal-by-commit) is review discipline; git
history is its audit trail, not this module.

The validation and classification halves are schema-parameterized
(2026-08-14) so config_diff.py can enforce the same seven rules over
config-line deltas, whose predicates have different fields (kind /
league vs league / sportsbook) — the defaults preserve the original
engine-output behavior exactly.
"""
import datetime
from pathlib import Path

import tomllib

REQUIRED = ("id", "reason", "match", "max_rows", "expires")
REQUIRED_MATCH = ("direction", "league", "sportsbook")
# side_swap = true is the only way to excuse a SIDE SWAP delta (swaps.py):
# a contract moved to the opposite side is the costliest mapping error, so
# a waiver written for ordinary churn must never swallow one by accident.
OPTIONAL_MATCH = ("market_type", "market_type_prefix", "side_swap")
DIRECTIONS = ("added", "removed")
MAX_EXPIRY_DAYS = 90


class WaiverError(Exception):
    """waivers.toml is invalid; nothing was classified."""


def _validate_waiver(w, where, today, required_match, optional_match,
                     directions):
    """Check ONE waiver against the seven rules -> error strings.
    Duplicate-id detection stays with the caller (it needs the set
    of ids seen across the whole file)."""
    errors = []
    for f in REQUIRED:
        if f not in w:
            errors.append(f"{where}: missing required field {f!r}")
    for f in w:
        if f not in REQUIRED:
            errors.append(f"{where}: unknown field {f!r}")
    if not w.get("reason"):
        errors.append(f"{where}: reason must be a non-empty string "
                      f"citing a commit/ticket")
    m = w.get("match", {})
    for f in required_match:
        if f not in m:
            errors.append(f"{where}: match must include {f!r} — "
                          f"blanket waivers are rejected")
    for f in m:
        if f not in tuple(required_match) + tuple(optional_match):
            errors.append(f"{where}: unknown match key {f!r} — a "
                          f"typo here would widen the waiver")
    if m.get("direction") not in (None, *directions):
        errors.append(f"{where}: direction must be one of "
                      f"{directions}")
    if "side_swap" in m and m["side_swap"] is not True:
        errors.append(f"{where}: side_swap may only be true (omit it "
                      f"for an ordinary waiver)")
    if "max_rows" in w and (not isinstance(w["max_rows"], int)
                            or w["max_rows"] < 1):
        errors.append(f"{where}: max_rows must be a positive int")
    exp = w.get("expires")
    if exp is not None:
        if not isinstance(exp, datetime.date):
            errors.append(f"{where}: expires must be a TOML date")
        elif (exp - today).days > MAX_EXPIRY_DAYS:
            errors.append(
                f"{where}: expires {exp} is more than "
                f"{MAX_EXPIRY_DAYS} days out — a far-future expiry "
                f"is a politely deleted gate")
    return errors


def load_waivers(path, today, *, required_match=REQUIRED_MATCH,
                 optional_match=OPTIONAL_MATCH, directions=DIRECTIONS,
                 extra_top_level=()):
    """Parse and validate waivers.toml -> list of waiver dicts.
    Raises WaiverError listing EVERY problem (not just the first);
    an invalid file classifies nothing.  The keyword arguments let a
    different delta domain (config_diff.py) declare its own match
    schema while keeping every seven-rule check identical."""
    doc = tomllib.loads(Path(path).read_text())
    errors = []
    for key in doc:
        if key != "waiver" and key not in extra_top_level:
            errors.append(f"unknown top-level key {key!r}")
    waivers = doc.get("waiver", [])
    seen_ids = set()
    for i, w in enumerate(waivers):
        where = f"waiver[{i}]" + (f" ({w['id']!r})" if "id" in w else "")
        if "id" in w:
            if w["id"] in seen_ids:
                errors.append(f"{where}: duplicate id")
            seen_ids.add(w["id"])
        errors += _validate_waiver(w, where, today, required_match,
                                   optional_match, directions)
    if errors:
        raise WaiverError("invalid waivers file:\n  "
                          + "\n  ".join(errors))
    return waivers


def matches(waiver, delta):
    """Mechanical predicate: every condition must hold.  A delta is
    {"direction": added|removed, "rec": parsed canonical line}."""
    m = waiver["match"]
    rec = delta["rec"]
    k = rec["k"]  # [league, start, home, away, market_type, ...]
    if m["direction"] != delta["direction"]:
        return False
    if bool(delta.get("swap")) != bool(m.get("side_swap")):
        return False
    if m["league"] != k[0] or m["sportsbook"] != rec["sb"]:
        return False
    if "market_type" in m and m["market_type"] != k[4]:
        return False
    if "market_type_prefix" in m and \
            not k[4].startswith(m["market_type_prefix"]):
        return False
    return True


def classify(deltas, waivers, today, *, match=matches):
    """Attribute every delta to the first matching active waiver.

    Returns (waived, unexplained, notes):
      waived       {waiver id: [delta, ...]}  within ceiling
      unexplained  [delta, ...]  incl. all deltas of breached waivers
      notes        {"stale": [ids matching nothing],
                    "breached": {id: matched count > ceiling},
                    "expired": {id: count it would have covered}}

    match is injectable for other delta domains (config_diff.py);
    the default is this module's engine-output predicate.
    """
    active = [w for w in waivers if w["expires"] >= today]
    expired = [w for w in waivers if w["expires"] < today]
    claimed = {w["id"]: [] for w in waivers}
    unexplained = []
    for d in deltas:
        for w in active:
            if match(w, d):
                claimed[w["id"]].append(d)
                break
        else:
            unexplained.append(d)
    waived, breached = {}, {}
    for w in active:
        c = claimed[w["id"]]
        if len(c) > w["max_rows"]:
            breached[w["id"]] = len(c)
            unexplained.extend(c)
        elif c:
            waived[w["id"]] = c
    stale = [w["id"] for w in active if not claimed[w["id"]]]
    expired_cover = {
        w["id"]: sum(1 for d in unexplained if match(w, d))
        for w in expired}
    return waived, unexplained, {
        "stale": stale, "breached": breached, "expired": expired_cover}
