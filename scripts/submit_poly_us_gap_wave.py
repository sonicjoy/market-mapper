#!/usr/bin/env python
"""Legacy tip/console tool (retiring): cover Polymarket US RFQ gaps with Review cards.

Enables / remaps ``polymarket_usa`` inners on tip leagues, onboards Optic-
confirmed leagues that were missing, and pins US team codes that diverge
from Optic abbreviations. Classify never reads ``US_CODE_OVERRIDES``.

    python scripts/submit_poly_us_gap_wave.py
    python scripts/submit_poly_us_gap_wave.py --submit --env both
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from google.cloud import bigquery

from fetch.polymarket_usa_gateway import lookup_markets
from mappers.alias_kinds import is_optic_id, optic_pin
from mappers.canonical_codes import fallback_code
from mappers.control_plane.bq_store import BigQueryStore
from mappers.control_plane.chat_profiles import all_platform_exchanges
from mappers.control_plane.gap_fix_poly_bq import us_events_from_symbols
from mappers.control_plane.models import (
    Actor,
    ActorRole,
    AliasPin,
    BatchChangesPayload,
    BatchEntryRequest,
    EntityAliasPayload,
    ExchangePin,
    MappingLeaguePayload,
)
from mappers.control_plane.service import ProposalService
from mappers.control_plane.store import LeagueRow
from mappers.seed.poly_usa_exchange import NO_OPTIC_US_INNERS, POLY_USA_BOOK, us_league_code
from scripts.submit_poly_us_cards import _league_payload

NOTE = (
    "2026-08-29 Poly US gap wave: pin live polymarketus inners (lexp/lpc/"
    "nor1/cdb/lpb/arg2/kbo/npb + new Optic leagues) and US team codes that "
    "diverge from Optic abbreviations."
)

ENABLE_US: dict[str, str] = {
    "mexico_liga_expansion": "lexp",
    "kbo": "kbo",
    "npb": "npb",
}
REMAP_US: dict[str, str] = {
    "costa_rica_primera_division": "lpc",
    "norway_1_divisjon": "nor1",
    "brazil_copa_do_brasil": "cdb",
    "bolivia_division_professional": "lpb",
    "argentina_primera_nacional": "arg2",
}
# slug, sport, optic_league_id, us_inner, clone_market_rules_from
NEW_LEAGUES: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "paraguay_division_intermedia", "soccer",
        "paraguay_-_division_intermedia", "par2", "colombia_primera_a",
    ),
    (
        "russia_premier_league", "soccer",
        "russia_-_premier_league", "rpl", "colombia_primera_a",
    ),
    (
        "guatemala_liga_nacional", "soccer",
        "guatemala_-_liga_nacional", "lng", "colombia_primera_a",
    ),
    (
        "finland_ykkosliiga", "soccer",
        "finland_-_ykkosliiga", "ykk", "colombia_primera_a",
    ),
    (
        "poland_ekstraklasa", "soccer",
        "poland_-_ekstraklasa", "ekst", "colombia_primera_a",
    ),
    (
        "czech_first_league", "soccer",
        "czech_republic_-_first_league", "flc", "colombia_primera_a",
    ),
    (
        "ireland_division_1", "soccer",
        "ireland_-_division_1", "irl1", "colombia_primera_a",
    ),
    (
        "switzerland_super_league", "soccer",
        "switzerland_-_super_league", "swsl", "colombia_primera_a",
    ),
    (
        "caribbean_premier_league", "cricket",
        "west_indies_-_caribbean_premier_league", "cplcr", "cricket_test",
    ),
)
SKIP_ALIAS_SPORTS = frozenset({
    "mma", "tennis", "esports", "hockey", "basketball",
})
SKIP_ALIAS_LEAGUES = frozenset({
    "mlb", "nfl", "nba", "wnba", "nhl",
})
# league, canonical_key, name, optic_id, usa_code
EXTRA_ALIASES: tuple[tuple[str, str, str, str, str], ...] = (
    ("kbo", "BEA", "Doosan Bears", "FC15A5D6EC84", "dbo"),
    ("kbo", "KIH", "Kiwoom Heroes", "DED507773550", "khi"),
    ("kbo", "EAG", "Hanwha Eagles", "77F58C044765", "hea"),
    ("kbo", "DIN", "NC Dinos", "3F12568FF716", "ndc"),
    ("kbo", "TIG", "Kia Tigers", "BAC3DC7D17FB", "kti"),
    ("kbo", "SSG", "SSG Landers", "D501DA4D1F71", "sls"),
    ("kbo", "WIZ", "KT Wiz", "ACAB6FF3F4BF", "kwt"),
    ("kbo", "GIA", "Lotte Giants", "C1C60C4D6B4F", "lgo"),
    ("kbo", "TWI", "LG Twins", "ACE74D46E7C9", "ltg"),
    ("kbo", "LIO", "Samsung Lions", "9FB2D676F219", "sla"),
    ("npb", "FUK", "Fukuoka Hawks", "B324B8602CBB", "fsh"),
    ("npb", "ORI", "Orix Buffaloes", "EBE0F6671AE2", "obr"),
    ("npb", "HIR", "Hiroshima Toyo Carp", "BA2F95B47D58", "hci"),
    ("npb", "HAN", "Hanshin Tigers", "DCACE8FF0F9D", "hta"),
    ("npb", "YOG", "Yomiuri Giants", "05C58E11EECD", "ygo"),
    ("npb", "TRG", "Tohoku Rakuten Golden Eagles", "D984BD6DAB37", "trge"),
    ("npb", "YDB", "Yokohama Dena Baystars", "C70D7886F576", "ybo"),
    ("npb", "CHU", "Chunichi Dragons", "8AE72B4F577B", "cdh"),
)
PARTICLES = frozenset({
    "de", "del", "la", "el", "los", "las", "fc", "cf", "cd", "sc", "club",
    "united", "city", "the", "of", "and", "y", "da", "do", "di", "a", "al",
    "csyd", "cs", "ud", "ac", "as", "fk", "if", "bk", "sk", "il", "ca",
})


def _words(name: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", name.casefold()) if w]


def _initials(words: list[str], *, drop_particles: bool) -> str:
    src = [w for w in words if w not in PARTICLES] if drop_particles else words
    return "".join(w[0] for w in src)


def _code_hits(code: str, abbr: str, name: str) -> int:
    c = code.casefold()
    a = (abbr or "").casefold()
    if not c:
        return 0
    if a and c == a:
        return 2
    words = _words(name)
    if not words:
        return 0
    if any(w.startswith(c) for w in words if len(c) >= 3):
        return 2
    if a and (a.startswith(c) or c.startswith(a)) and min(len(a), len(c)) >= 3:
        return 2
    for drop in (True, False):
        ini = _initials(words, drop_particles=drop)
        if ini == c:
            return 2
        if ini.startswith(c) or (c.startswith(ini) and len(ini) >= 3):
            return 1
    first = next((w for w in words if w not in PARTICLES), "")
    if first[:3] == c[:3] and len(c) >= 3:
        return 1
    return 0


def _shift(day: str, days: int) -> str:
    y, m, d = (int(p) for p in day.split("-"))
    return (date(y, m, d) + timedelta(days=days)).isoformat()


def _best_fixture(event: dict[str, Any], fixtures: list[dict[str, Any]]) -> dict[str, Any] | None:
    dates = {event["date"], _shift(event["date"], -1), _shift(event["date"], 1)}
    scored: list[tuple[int, dict[str, Any], str]] = []
    for fx in fixtures:
        if str(fx["d"]) not in dates:
            continue
        same = _code_hits(event["home"], str(fx["home_abbr"] or ""), str(fx["home_name"] or ""))
        same += _code_hits(event["away"], str(fx["away_abbr"] or ""), str(fx["away_name"] or ""))
        flip = _code_hits(event["home"], str(fx["away_abbr"] or ""), str(fx["away_name"] or ""))
        flip += _code_hits(event["away"], str(fx["home_abbr"] or ""), str(fx["home_name"] or ""))
        if same >= 3 and same >= flip:
            scored.append((same, fx, "same"))
        elif flip >= 3:
            scored.append((flip, fx, "flip"))
    if not scored:
        return None
    scored.sort(key=lambda item: -item[0])
    top = scored[0][0]
    tops = [item for item in scored if item[0] == top]
    if len(tops) != 1:
        return None
    score, fx, orient = tops[0]
    return {"score": score, "orient": orient, "fx": fx}


def _events(client: bigquery.Client) -> list[dict[str, Any]]:
    """Gap events from typed gateway fields; RFQ symbols are never split."""
    rows = client.query("""
select distinct lower(coalesce(
  json_value(l.platform_mapping, '$.ticker'),
  json_value(l.platform_mapping, '$.market_ticker'),
  json_value(l.platform_mapping, '$.symbol')
)) as symbol
from `rs-marketmaking.reporting_us.rfq_latest` as r, unnest(r.legs) as l
where lower(r.platform) like '%polymarket%us%'
  and r.first_publish_time > timestamp_sub(current_timestamp(), interval 14 day)
  and r.last_updated > timestamp_sub(current_timestamp(), interval 3 hour)
  and r.reason in ('MAPPING_FAILED', 'UNMAPPED')
  and (l.optic_fixture_id is null or l.market is null or l.selection is null)
""").result()
    symbols = [str(row["symbol"]) for row in rows if row["symbol"]]
    inners = {m["league"] for m in lookup_markets(symbols).values() if m["league"]}
    return us_events_from_symbols(symbols, inners)


def _optic(client: bigquery.Client) -> list[dict[str, Any]]:
    return [dict(r) for r in client.query("""
select
  league.id as optic_league_id,
  date(start_date) as d,
  game_id,
  home_team_display as home_name,
  away_team_display as away_name,
  json_value(to_json_string(home_competitors[safe_offset(0)]), '$.id') as home_id,
  json_value(to_json_string(away_competitors[safe_offset(0)]), '$.id') as away_id,
  json_value(to_json_string(home_competitors[safe_offset(0)]), '$.abbreviation') as home_abbr,
  json_value(to_json_string(away_competitors[safe_offset(0)]), '$.abbreviation') as away_abbr
from `rs-marketmaking.opticodds_us.opticodds_fixtures`
where start_date between timestamp('2026-08-24') and timestamp('2026-09-04')
""").result()]


def _target_inners() -> dict[str, str]:
    out = dict(ENABLE_US)
    out.update(REMAP_US)
    for slug, _sport, _optic, inner, _clone in NEW_LEAGUES:
        out[slug] = inner
    return out


def _inner_to_slug() -> dict[str, str]:
    return {inner: slug for slug, inner in _target_inners().items()}


def _usa_code(row: LeagueRow) -> str:
    return us_league_code(row)


def _needs_us_update(row: LeagueRow) -> str | None:
    slug = str(row.league)
    target = ENABLE_US.get(slug) or REMAP_US.get(slug)
    if not target:
        return None
    if _usa_code(row) == target:
        return None
    return target


def _new_league_payload(item: tuple[str, str, str, str, str]) -> MappingLeaguePayload:
    slug, sport, optic, inner, clone = item
    raw = all_platform_exchanges(
        optic_league_id=optic,
        evidence_books=["optic", "polymarket_usa"],
    )
    pins: list[ExchangePin] = []
    for ex in raw:
        book = str(ex["sportsbook"])
        source = ex.get("source_league_id")
        settings = dict(ex.get("settings") or {})
        if book == POLY_USA_BOOK:
            source = inner
            settings["slug_prefix"] = inner
        pins.append(
            ExchangePin(
                sportsbook=book,
                enabled=bool(ex.get("enabled")),
                parser_profile=str(ex.get("parser_profile") or ""),
                source_league_id=source,
                settings=settings,
            ),
        )
    return MappingLeaguePayload(
        league=slug,
        sport=sport,
        optic_league_id=optic,
        fixture_source="api",
        fixture_horizon_hours=168.0,
        enabled=True,
        exchanges=pins,
        clone_market_rules_from=clone,
        notes=NOTE,
        evidence_refs=[
            f"gap:usa-inner:{slug}:{inner}",
            f"optic:league:{optic}",
            "docs/polymarket-mapping-gaps.md",
        ],
    )


def build_leagues(rows: list[LeagueRow]) -> list[MappingLeaguePayload]:
    by_slug = {r.league: r for r in rows}
    leagues: list[MappingLeaguePayload] = []
    for row in sorted(rows, key=lambda item: item.league):
        target = _needs_us_update(row)
        if target is None:
            continue
        payload = _league_payload(row, us_code=target)
        payload.notes = NOTE
        payload.evidence_refs = [
            f"gap:usa-inner:{row.league}:{target}",
            f"optic:league:{row.optic_league_id}",
            "docs/polymarket-mapping-gaps.md",
        ]
        leagues.append(payload)
    existing = {r.league for r in rows}
    for item in NEW_LEAGUES:
        if item[0] in existing:
            row = by_slug[item[0]]
            if _usa_code(row) != item[3]:
                payload = _league_payload(row, us_code=item[3])
                payload.notes = NOTE
                leagues.append(payload)
            continue
        leagues.append(_new_league_payload(item))
    if not leagues:
        raise RuntimeError("no league updates needed")
    return leagues


def _optic_owner(entities: list[Any], league: str, oid: str) -> Any | None:
    for ent in entities:
        if ent.league != league or ent.tombstone:
            continue
        if any(is_optic_id(alias, oid) for alias in ent.aliases):
            return ent
    return None


def _usa_owners(entities: list[Any], league: str, code: str) -> list[str]:
    wanted = code.casefold()
    hits: list[str] = []
    for ent in entities:
        if ent.league != league or ent.tombstone:
            continue
        for alias in ent.aliases:
            if str(alias.get("sportsbook") or "").lower() != "polymarket_usa":
                continue
            if str(alias.get("alias_kind") or "") != "code":
                continue
            if str(alias.get("alias_value") or "").casefold() == wanted:
                hits.append(ent.canonical_key)
                break
    return hits


def build_aliases(
    store: Any,
    client: bigquery.Client,
    rows: list[LeagueRow],
) -> list[EntityAliasPayload]:
    entities = store.entities_for(store.current_rule_set_id)
    inner_map: dict[str, str] = {}
    sport_by_league = {r.league: r.sport for r in rows}
    optic_by_league = {r.optic_league_id: r.league for r in rows}
    for row in rows:
        code = _usa_code(row)
        if code:
            inner_map[code] = row.league
    for slug, inner in _target_inners().items():
        inner_map[inner] = slug
        sport_by_league.setdefault(slug, "soccer")
    for slug, sport, optic, _inner, _clone in NEW_LEAGUES:
        optic_by_league[optic] = slug
        sport_by_league[slug] = sport
    events = _events(client)
    optic_rows = _optic(client)
    by_optic: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fx in optic_rows:
        by_optic[str(fx["optic_league_id"] or "")].append(fx)

    used_keys: dict[str, set[str]] = defaultdict(set)
    for ent in entities:
        if not ent.tombstone:
            used_keys[ent.league].add(ent.canonical_key)
    seen: set[tuple[str, str, str]] = set()
    aliases: list[EntityAliasPayload] = []
    claimed_usa: dict[tuple[str, str], str] = {}

    for event in events:
        inner = event["inner"]
        if inner in NO_OPTIC_US_INNERS:
            continue
        league = inner_map.get(inner)
        if not league:
            continue
        if sport_by_league.get(league) in SKIP_ALIAS_SPORTS:
            continue
        if league in SKIP_ALIAS_LEAGUES:
            continue
        optic_id = next(
            (oid for oid, slug in optic_by_league.items() if slug == league),
            "",
        )
        if not optic_id:
            continue
        hit = _best_fixture(event, by_optic.get(optic_id, []))
        if hit is None:
            continue
        fx = hit["fx"]
        if hit["orient"] == "same":
            pairs = (
                (event["home"], fx["home_abbr"], fx["home_id"], fx["home_name"]),
                (event["away"], fx["away_abbr"], fx["away_id"], fx["away_name"]),
            )
        else:
            pairs = (
                (event["home"], fx["away_abbr"], fx["away_id"], fx["away_name"]),
                (event["away"], fx["home_abbr"], fx["home_id"], fx["home_name"]),
            )
        for usa, abbr, oid, name in pairs:
            if not oid or not usa:
                continue
            if usa.casefold() == str(abbr or "").casefold():
                continue
            key = (league, str(oid), usa.casefold())
            if key in seen:
                continue
            seen.add(key)
            owner = _optic_owner(entities, league, str(oid))
            if owner is not None:
                canonical = owner.canonical_key
                entity_type = str(owner.entity_type or "team") or "team"
                display = owner.canonical_name or name
            else:
                canonical = str(abbr or "").strip()
                if not canonical or not re.match(r"^[A-Za-z0-9_-]+$", canonical):
                    canonical = fallback_code(str(name or usa), used_keys[league], str(oid))
                used_keys[league].add(canonical)
                entity_type = "team"
                display = name
            if entity_type not in ("team", "player", "fighter"):
                entity_type = "team"
            owners = _usa_owners(entities, league, usa)
            if owners and canonical not in owners:
                continue
            claimed = claimed_usa.get((league, usa.casefold()))
            if claimed and claimed != canonical:
                continue
            claimed_usa[(league, usa.casefold())] = canonical
            aliases.append(
                EntityAliasPayload(
                    league=league,
                    canonical_key=canonical,
                    entity_type=entity_type,  # type: ignore[arg-type]
                    canonical_name=str(display or name),
                    aliases=[
                        AliasPin.model_validate(optic_pin(str(oid))),
                        AliasPin(
                            sportsbook="polymarket_usa",
                            alias_kind="code",
                            alias_value=usa,
                        ),
                    ],
                ),
            )
    for league, canonical, name, oid, usa in EXTRA_ALIASES:
        key = (league, oid, usa.casefold())
        if key in seen:
            continue
        seen.add(key)
        owner = _optic_owner(entities, league, oid)
        if owner is not None:
            canonical = owner.canonical_key
            entity_type = str(owner.entity_type or "team") or "team"
            display = owner.canonical_name or name
        else:
            entity_type = "team"
            display = name
            used_keys[league].add(canonical)
        if entity_type not in ("team", "player", "fighter"):
            entity_type = "team"
        owners = _usa_owners(entities, league, usa)
        if owners and canonical not in owners:
            continue
        claimed = claimed_usa.get((league, usa.casefold()))
        if claimed and claimed != canonical:
            continue
        claimed_usa[(league, usa.casefold())] = canonical
        aliases.append(
            EntityAliasPayload(
                league=league,
                canonical_key=canonical,
                entity_type=entity_type,  # type: ignore[arg-type]
                canonical_name=str(display or name),
                aliases=[
                    AliasPin.model_validate(optic_pin(oid)),
                    AliasPin(
                        sportsbook="polymarket_usa",
                        alias_kind="code",
                        alias_value=usa,
                    ),
                ],
            ),
        )
    return aliases


def build_payload(store: Any, client: bigquery.Client) -> BatchChangesPayload:
    tip = store.current_rule_set_id
    if tip is None:
        raise RuntimeError("no tip")
    rows = store.leagues_for(tip)
    return BatchChangesPayload(
        leagues=build_leagues(rows),
        entity_aliases=build_aliases(store, client, rows),
    )


def _console_base(project: str) -> str:
    if project == "marketmaking-test":
        return "https://mapping.mm-test.whiteswandata.com"
    return "https://mapping.mm.whiteswandata.com"


def _evidence_note(payload: BatchChangesPayload) -> str:
    refs = [NOTE]
    for lg in payload.leagues:
        refs.append(f"league:{lg.league}")
    refs.append(f"aliases:{len(payload.entity_aliases)}")
    refs.append("docs/polymarket-mapping-gaps.md")
    return " ".join(refs)


def submit_env(project: str) -> dict[str, Any]:
    os.environ["GCP_PROJECT"] = project
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    payload = build_payload(store, client)
    svc = ProposalService(store, require_maker_checker=False)
    actor = Actor(subject="scripts/submit_poly_us_gap_wave", role=ActorRole.PROPOSER)
    body = BatchEntryRequest(
        leagues=payload.leagues,
        entity_aliases=payload.entity_aliases,
        acknowledge_shadow=True,
        note=_evidence_note(payload),
    )
    verified = svc.entry_batch_verify(body)
    if not verified.get("ok"):
        raise RuntimeError(f"{project}: verify blocked: {verified.get('blockers')}")
    card = svc.entry_batch_submit(str(verified["preview_token"]), actor)
    ref = str(card.get("ref") or card.get("proposal_id") or "")
    return {
        "project": project,
        "rule_set_id": store.current_rule_set_id,
        "league_count": len(payload.leagues),
        "leagues": [lg.league for lg in payload.leagues],
        "alias_count": len(payload.entity_aliases),
        "ref": ref,
        "review_url": f"{_console_base(project)}/review/{ref}" if ref else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--env", choices=("test", "prod", "both"), default="both")
    args = parser.parse_args(argv)
    if args.submit:
        projects: list[str] = []
        if args.env in ("test", "both"):
            projects.append("marketmaking-test")
        if args.env in ("prod", "both"):
            projects.append("rs-marketmaking")
        out = []
        for project in projects:
            print(f"submitting {project}...", file=sys.stderr)
            out.append(submit_env(project))
        print(json.dumps(out, indent=2, default=str))
        return 0
    os.environ.setdefault("GCP_PROJECT", "rs-marketmaking")
    project = os.environ["GCP_PROJECT"]
    environment = "test" if project == "marketmaking-test" else "prod"
    client = bigquery.Client(project=project)
    store = BigQueryStore(client, environment=environment, allow_activate=False)
    payload = build_payload(store, client)
    summary = {
        "leagues": [
            {
                "league": lg.league,
                "optic": lg.optic_league_id,
                "new": lg.clone_market_rules_from is not None,
                "usa": next(
                    (
                        str(ex.source_league_id or "")
                        for ex in lg.exchanges
                        if ex.sportsbook == POLY_USA_BOOK
                    ),
                    "",
                ),
            }
            for lg in payload.leagues
        ],
        "alias_count": len(payload.entity_aliases),
        "alias_leagues": sorted({a.league for a in payload.entity_aliases}),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
