"""Human-readable Optic evidence refs for review cards."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

AliasOwner = tuple[set[str], str]


def optic_fixture_ref(row: Mapping[str, Any] | None) -> str:
    """optic:fixture:{id}:{home} vs {away} ({date}) when sides are known."""
    if not row:
        return ""
    fxid = str(row.get("fixture_id") or row.get("id") or "").strip()
    if not fxid:
        return ""
    label = _label(row)
    return f"optic:fixture:{fxid}:{label}" if label else f"optic:fixture:{fxid}"


def optic_competitor_ref(oid: str, name: str = "") -> str:
    """optic:competitor:{id}:{name} so Review can see who a hex id is."""
    cid = str(oid or "").strip()
    if not cid:
        return ""
    shown = str(name or "").strip()
    return f"optic:competitor:{cid}:{shown}" if shown else f"optic:competitor:{cid}"


def optic_identity_refs(row: Mapping[str, Any] | None) -> list[str]:
    """Fixture matchup plus named competitors for a harvest/probe optic dict."""
    if not row:
        return []
    refs: list[str] = []
    fx = optic_fixture_ref(row)
    if fx:
        refs.append(fx)
    refs.extend(_competitor_refs(row))
    return refs


def optic_refs_from_pins(pins: Sequence[tuple[str, str, str]]) -> list[str]:
    """Named competitor refs from (sportsbook, alias_value, canonical_name)."""
    refs: list[str] = []
    seen: set[str] = set()
    for book, oid, name in pins:
        if str(book).strip().lower() != "optic":
            continue
        ref = optic_competitor_ref(oid, name)
        if ref and ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs


def usa_alias_refs(
    league: str,
    usa: str,
    event: Mapping[str, Any] | None,
    oid: str,
    name: str,
    fx: Mapping[str, Any] | None,
) -> list[str]:
    """Polymarket US ticker/code plus named Optic competitor and fixture."""
    refs = [
        f"polymarket_usa:code:{usa}",
        *_usa_name_refs(event, usa),
        *_usa_event_refs(event),
        f"gap:usa-inner:{league}:{usa}",
        optic_competitor_ref(str(oid), str(name)),
        optic_match_fixture_ref(fx),
    ]
    return [ref for ref in refs if ref]


def optic_match_fixture_ref(fx: Mapping[str, Any] | None) -> str:
    """Fixture ref from harvest matcher shape (home_name / d / fixture_id)."""
    if not fx:
        return ""
    fxid = str(fx.get("fixture_id") or fx.get("id") or fx.get("game_id") or "").strip()
    if not fxid:
        fxid = f"{fx.get('d') or ''}|{fx.get('home_id') or ''}|{fx.get('away_id') or ''}"
    if not fxid.strip("|"):
        return ""
    return optic_fixture_ref({
        "fixture_id": fxid,
        "home": str(fx.get("home_name") or fx.get("home") or ""),
        "away": str(fx.get("away_name") or fx.get("away") or ""),
        "start_date": str(fx.get("start_date") or fx.get("d") or "")[:10],
    })


def _usa_name_refs(event: Mapping[str, Any] | None, usa: str) -> list[str]:
    """Gateway display name for this code, then the event title."""
    if not event:
        return []
    refs: list[str] = []
    names = event.get("team_names")
    shown = ""
    if isinstance(names, dict):
        shown = str(names.get(str(usa).casefold()) or "").strip()
    if shown:
        refs.append(f"polymarket_usa:name:{shown}")
    title = str(event.get("title") or "").strip()
    if title:
        refs.append(f"polymarket_usa:title:{title}")
    return refs


def _usa_event_refs(event: Mapping[str, Any] | None) -> list[str]:
    """Ticker, sides, date, and inner code from a US harvest event."""
    if not event:
        return []
    refs: list[str] = []
    ticker = str(event.get("ticker") or "").strip()
    if ticker:
        refs.append(f"polymarket_usa:ticker:{ticker}")
    home = str(event.get("home") or "").strip()
    away = str(event.get("away") or "").strip()
    day = str(event.get("date") or "").strip()[:10]
    if home and away:
        match = f"{home} vs {away}"
        refs.append(f"polymarket_usa:match:{match} ({day})" if day else f"polymarket_usa:match:{match}")
    inner = str(event.get("inner") or "").strip()
    if inner:
        refs.append(f"polymarket_usa:inner:{inner}")
    return refs


def _competitor_refs(row: Mapping[str, Any]) -> list[str]:
    """Deduped named competitor refs from home/away fields or competitor lists."""
    refs: list[str] = []
    seen: set[str] = set()
    for oid, name in _competitors(row):
        ref = optic_competitor_ref(oid, name)
        if ref and ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs


def _competitors(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(id, name) for Optic home then away."""
    pairs = [
        (str(row.get("home_id") or ""), _side(row, "home", "home_competitors")),
        (str(row.get("away_id") or ""), _side(row, "away", "away_competitors")),
    ]
    out = [(oid.strip(), name) for oid, name in pairs if oid.strip()]
    return out or _competitors_from_lists(row)


def _competitors_from_lists(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Ids from home_competitors / away_competitors when home_id is absent."""
    out: list[tuple[str, str]] = []
    for key in ("home_competitors", "away_competitors"):
        people = row.get(key) or []
        if not isinstance(people, list):
            continue
        for person in people:
            if not isinstance(person, dict):
                continue
            oid = str(person.get("id") or "").strip()
            if oid:
                out.append((oid, str(person.get("name") or "").strip()))
    return out


def _label(row: Mapping[str, Any]) -> str:
    """Matchup and calendar date from a game or probe optic dict."""
    home = _side(row, "home", "home_competitors")
    away = _side(row, "away", "away_competitors")
    matchup = f"{home} vs {away}" if home and away else home or away
    day = str(row.get("start_date") or "").strip()[:10]
    if matchup and day:
        return f"{matchup} ({day})"
    return matchup or day


def cluster_alias_refs(owners: Sequence[AliasOwner], refs: Sequence[str]) -> list[str]:
    """Keep each alias's competitor and matching fixture consecutive."""
    refs = _collapse_same_matchup(refs)
    if len(owners) < 2:
        return list(refs)
    buckets: list[list[str]] = [[] for _ in owners]
    shared: list[str] = []
    notes: list[str] = []
    current: int | None = None
    for ref in refs:
        hits = [i for i, owner in enumerate(owners) if _owned_by(owner, ref)]
        if hits:
            for idx in hits:
                buckets[idx].append(ref)
            current = hits[0]
            continue
        if current is not None and _follows_owner(ref):
            buckets[current].append(ref)
            continue
        if _is_shared_ref(ref):
            shared.append(ref)
        else:
            notes.append(ref)
    ordered = list(shared)
    for bucket in buckets:
        ordered.extend(_order_bucket(bucket))
    ordered.extend(notes)
    return ordered


def _collapse_same_matchup(refs: Sequence[str]) -> list[str]:
    """Keep one optic:fixture per matchup; prefer Optic hex ids over harvest ids."""
    best: dict[str, tuple[int, int]] = {}
    drop: set[int] = set()
    items = list(refs)
    for i, ref in enumerate(items):
        if not ref.startswith("optic:fixture:"):
            continue
        label = _fixture_matchup(ref).casefold()
        if " vs " not in label:
            continue
        score = _optic_fixture_id_score(ref)
        prev = best.get(label)
        if prev is None:
            best[label] = (score, i)
            continue
        prev_score, prev_i = prev
        if score > prev_score:
            drop.add(prev_i)
            best[label] = (score, i)
        else:
            drop.add(i)
    return [ref for i, ref in enumerate(items) if i not in drop]


def _optic_fixture_id_score(ref: str) -> int:
    """Hex Optic fixture ids outrank harvest composite ids."""
    fid = ref.split(":", 2)[-1].split(":", 1)[0].strip()
    if len(fid) == 16 and all(ch in "0123456789abcdefABCDEF" for ch in fid):
        return 2
    return 0


def _order_bucket(refs: list[str]) -> list[str]:
    """Competitor then matching fixture so Review sticky grouping cannot rotate."""
    comps = [ref for ref in refs if ref.startswith("optic:competitor:")]
    fixtures = [ref for ref in refs if ref.startswith("optic:fixture:")]
    rest = [ref for ref in refs if ref not in comps and ref not in fixtures]
    return [*rest, *comps, *fixtures]


def _owned_by(owner: AliasOwner, ref: str) -> bool:
    """True when this alias's ids or names uniquely claim the ref."""
    ids, name = owner
    if ref.startswith("optic:fixture:"):
        label = _fixture_matchup(ref).casefold()
        return any(needle.casefold() in label for needle in _name_needles(name) if len(needle) >= 3)
    if ref.startswith((
        "kalshi:title:",
        "kalshi:market:",
        "kalshi:market_title:",
        "kalshi:yes_sub_title:",
        "kalshi:rules_primary:",
    )):
        return _kalshi_owned(ids, name, ref)
    if _is_kalshi_gap(ref):
        return _ticker_owned(ids, ref)
    token = _ref_token(ref)
    if token and token in ids:
        return True
    if not _is_name_ref(ref):
        return False
    shown = ref.rsplit(":", 1)[-1].strip().casefold()
    return any(needle.casefold() == shown for needle in _name_needles(name))


def _name_needles(name: str) -> list[str]:
    """Full display name plus stripped BAR / BAI5-style key, not the first word."""
    shown = name.strip()
    if not shown:
        return []
    bits = shown.split(None, 1)
    if len(bits) != 2:
        return [shown]
    key, rest = bits
    if _looks_like_key(key) and len(rest) >= 3:
        return [shown, rest]
    return [shown]


def _looks_like_key(token: str) -> bool:
    """True for BAR / MUN / BAI5, not Manchester or United."""
    if len(token) < 2 or len(token) > 6:
        return False
    return token[0].isalpha() and token.isalnum() and token == token.upper()


def _fixture_matchup(ref: str) -> str:
    """Home vs Away (date) from optic:fixture, with or without an id prefix."""
    rest = ref.split(":", 2)[-1] if ref.count(":") >= 2 else ""
    cut = rest.find(":")
    after = rest[cut + 1 :].strip() if cut > 0 else ""
    if " vs " in after:
        return after
    return rest if " vs " in rest else after


def _ref_token(ref: str) -> str:
    """Sportsbook id/code used to attach a ref to an alias pin."""
    parts = ref.split(":")
    head = (parts[0] or "").lower()
    mid = (parts[1] or "").lower() if len(parts) > 1 else ""
    if head == "optic" and mid == "competitor" and len(parts) > 2:
        return parts[2].strip().lower()
    if head == "crypto" and mid == "symbol" and len(parts) > 3:
        return parts[2].strip().lower()
    if head == "gap" and mid == "usa-inner" and len(parts) > 2:
        return parts[-1].strip().lower()
    if head in {"polymarket_usa", "kalshi"} and mid == "code" and len(parts) > 2:
        return parts[2].strip().lower()
    if head == "crypto_id" and len(parts) > 1:
        return ref.split(":", 1)[-1].strip().lower()
    return ""


def _follows_owner(ref: str) -> bool:
    """Unlabeled fixture or US/name extras stick to the current alias cluster."""
    if ref.startswith("optic:fixture:"):
        return " vs " not in ref
    head, _, rest = ref.partition(":")
    mid = rest.split(":", 1)[0].lower() if rest else ""
    if head.lower() == "polymarket_usa" and mid != "code":
        return True
    return head.lower() in {"optic", "crypto"} and mid in {
        "name", "symbol", "tip", "title",
    }


def _kalshi_owned(ids: set[str], name: str, ref: str) -> bool:
    """True when the Kalshi ticker or title names this alias."""
    rest = ref.split(":", 2)[-1].casefold()
    return _ticker_owned(ids, rest) or _text_owned(name, rest)


def _ticker_owned(ids: set[str], hay: str) -> bool:
    """True when a Kalshi/Optic code of length 3+ appears in the ticker."""
    text = hay.casefold()
    return any(len(code) >= 3 and code.casefold() in text for code in ids)


def _text_owned(name: str, label: str) -> bool:
    """True when the alias full name is in the title."""
    needles = [n.casefold() for n in _name_needles(name) if len(n) >= 3]
    return any(needle in label for needle in needles)


def _is_kalshi_gap(ref: str) -> bool:
    """True for gap:KX… event tickers, not Polymarket slugs or usa-inner."""
    if not ref.startswith("gap:") or ref.startswith("gap:usa-inner:"):
        return False
    return ref.split(":", 1)[-1].upper().startswith("KX")


def _is_shared_ref(ref: str) -> bool:
    """Source/Polymarket/non-Kalshi gap refs that belong on every alias card."""
    head, _, rest = ref.partition(":")
    mid = rest.split(":", 1)[0].lower() if rest else ""
    if head.lower() == "source":
        return True
    if head.lower() == "gap" and mid != "usa-inner" and not _is_kalshi_gap(ref):
        return True
    if head.lower() == "optic" and mid == "league":
        return True
    return head.lower() == "polymarket" and mid in {
        "question", "description", "market", "slug", "outcome",
    }


def _is_name_ref(ref: str) -> bool:
    """optic:name or crypto:name identity line."""
    parts = ref.split(":")
    return len(parts) > 2 and parts[0].lower() in {"optic", "crypto"} and parts[1].lower() == "name"


def _side(row: Mapping[str, Any], key: str, competitors: str) -> str:
    """Probe `home`/`away` string, else first competitor name."""
    direct = str(row.get(key) or "").strip()
    if direct:
        return direct
    people = row.get(competitors) or []
    if not isinstance(people, list) or not people:
        return ""
    first = people[0] if isinstance(people[0], dict) else {}
    return str(first.get("name") or "").strip()
