"""Harvest Underdog alias + market-rule gaps from fixture-matched UDX CSV rows."""

from __future__ import annotations

import csv
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from google.cloud import bigquery

from BigQuery.client import ro_query
from mappers.control_plane.gap_fix_underdog_leagues import UNDERDOG_BOOK
from mappers.control_plane.models import (
    AliasPin,
    BatchChangesPayload,
    EntityAliasPayload,
    MappingMarketRulesPayload,
    MarketRulePin,
)
from mappers.control_plane.rows import EntityRow, LeagueRow, MarketRuleRow
from mappers.control_plane.underdog_legacy_ticker import venue_token_from_body
from mappers.control_plane.underdog_legacy_vocab import (
    VENUE_TOKEN_TO_LEAGUE_SLUG,
    market_type_for_venue,
)
from mappers.control_plane.underdog_team_catalog import (
    entity_has_underdog_code,
    team_catalog,
)
from mappers.seed.underdog_market_rules import SOURCE_KEY_TYPE

_DEFAULT_CSV = Path.home() / "Downloads" / "udx-production-markets-optic-fixtures-2026-09-24.csv"

_FIXTURES_BY_ID_SQL = """
select
  coalesce(nullif(id, ''), game_id) as fixture_id,
  home_team_display as home,
  away_team_display as away,
  league.id as optic_league_id,
  json_value(to_json_string(home_competitors[safe_offset(0)]), '$.id') as home_id,
  json_value(to_json_string(away_competitors[safe_offset(0)]), '$.id') as away_id
from `{project}.opticodds_us.opticodds_fixtures`
where coalesce(nullif(id, ''), game_id) in unnest(@fixture_ids)
  and start_date >= timestamp('2025-01-01')
  and start_date < timestamp('2027-06-01')
"""

FixtureQueryFn = Callable[[Sequence[str]], dict[str, dict[str, Any]]]


@dataclass(frozen=True)
class CsvMarketRow:
    ticker: str
    fixture_id: str


@dataclass(frozen=True)
class ParsedHeader:
    venue: str
    product: str
    period: str
    selection: str
    raw: str


@dataclass
class ClassifiedAlias:
    league: str
    code: str
    entity_type: Literal["team", "player", "fighter"]
    status: Literal["propose", "already_pinned", "skip"]
    reason: str = ""
    canonical_key: str = ""
    canonical_name: str = ""
    evidence_ticker: str = ""
    fixture_id: str = ""


@dataclass
class ClassifiedMarketRule:
    league: str
    source_key: str
    status: Literal["propose", "already_ruled", "needs_code"]
    product: str = ""
    period: str = ""
    venue: str = ""


@dataclass
class ClassifiedLeague:
    league: str
    status: Literal["ok", "missing_slug", "underdog_off", "wrong_token"]
    expected_token: str = ""
    actual_token: str = ""


@dataclass
class HarvestEnvReport:
    environment: str
    rule_set_id: str
    aliases: list[ClassifiedAlias] = field(default_factory=list)
    market_rules: list[ClassifiedMarketRule] = field(default_factory=list)
    leagues: list[ClassifiedLeague] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "rule_set_id": self.rule_set_id,
            "aliases": _bucket_counts(self.aliases, "status"),
            "aliases_by_league": _counts_by_league(self.aliases, "status", "propose"),
            "market_rules": _bucket_counts(self.market_rules, "status"),
            "market_rules_by_league": _counts_by_league(
                self.market_rules, "status", "propose",
            ),
            "leagues": _bucket_counts(self.leagues, "status"),
            "samples": {
                "alias_propose": _sample(self.aliases, "propose", 5),
                "alias_skip": _sample(self.aliases, "skip", 5),
                "rule_propose": _sample(self.market_rules, "propose", 5),
                "rule_needs_code": _sample(self.market_rules, "needs_code", 5),
                "league_underdog_off": _sample(self.leagues, "underdog_off", 5),
            },
        }


def load_fixture_csv(path: Path | None = None) -> list[CsvMarketRow]:
    """Rows with a non-empty ``oo_fixture_id``."""
    csv_path = path or _DEFAULT_CSV
    out: list[CsvMarketRow] = []
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            fid = str(row.get("oo_fixture_id") or row.get("fixture_id") or "").strip()
            ticker = str(row.get("ticker") or "").strip()
            if not fid or not ticker:
                continue
            out.append(CsvMarketRow(ticker=ticker, fixture_id=fid))
    return out


def _period_of(token: str) -> tuple[str, str]:
    periods = ("1H", "2H", "1Q", "2Q", "3Q", "4Q")
    for period in periods:
        if token.endswith(period) and len(token) > len(period):
            return token[: -len(period)], period
    if token[-1:] in {"3", "5", "7"} and token[:-1].isalpha():
        return token[:-1], token[-1]
    return token, ""


def parse_udx_header(ticker: str) -> ParsedHeader | None:
    raw = ticker.strip()
    if not raw.startswith("UDX"):
        return None
    body = raw[3:]
    venue = venue_token_from_body(body)
    if not venue:
        return None
    rest = body[len(venue):]
    if "_" not in rest:
        return None
    product_token, _, tail = rest.partition("_")
    if "_" not in tail:
        return None
    event, selection = tail.rsplit("_", 1)
    if not event or not selection:
        return None
    product, period = _period_of(product_token)
    if not product.isalpha():
        return None
    return ParsedHeader(
        venue=venue,
        product=product,
        period=period,
        selection=selection,
        raw=raw,
    )


def fetch_fixtures_by_ids(
    fixture_ids: Sequence[str],
    *,
    project: str | None = None,
    chunk_size: int = 2000,
) -> dict[str, dict[str, Any]]:
    """Load Optic fixture rows from BigQuery (no horizon filter)."""
    ids = sorted({fid.strip() for fid in fixture_ids if fid and fid.strip()})
    if not ids:
        return {}
    bq_project = project or os.environ.get("GCP_PROJECT") or "marketmaking-test"
    client = bigquery.Client(project=bq_project)
    out: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), chunk_size):
        chunk = ids[start : start + chunk_size]
        job = ro_query(
            client,
            _FIXTURES_BY_ID_SQL.format(project=bq_project),  # nosec B608
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("fixture_ids", "STRING", chunk),
                ],
            ),
        )
        for row in job:
            hit = dict(row)
            fid = str(hit.get("fixture_id") or "").strip()
            if fid:
                out[fid] = hit
    return out


def _classify_row(
    store: Any,
    row: CsvMarketRow,
    fixtures: Mapping[str, dict[str, Any]],
    catalog: dict[str, dict[str, str]],
    entities_by_league: dict[str, list[EntityRow]],
    tip_rules: list[MarketRuleRow],
    league_rows: dict[str, LeagueRow],
    alias_keys: dict[tuple[str, str], ClassifiedAlias],
    rule_keys: dict[tuple[str, str], ClassifiedMarketRule],
    league_keys: dict[str, ClassifiedLeague],
) -> None:
    # classify imports this module; import it here to avoid a cycle.
    from mappers.control_plane.underdog_fixture_classify import (
        _touch_league,
        _touch_market_rule,
    )

    header = parse_udx_header(row.ticker)
    if header is None:
        return
    slug = VENUE_TOKEN_TO_LEAGUE_SLUG.get(header.venue)
    if slug is None:
        return
    _touch_league(slug, header.venue, league_rows, league_keys)
    _touch_market_rule(slug, header, tip_rules, rule_keys)
    decided = _alias_for_row(store, row, header, slug, fixtures, catalog, entities_by_league)
    if decided is None:
        return
    key = (slug, decided.code)
    if key not in alias_keys or alias_keys[key].status == "skip":
        alias_keys[key] = decided


def _alias_for_row(
    store: Any,
    row: CsvMarketRow,
    header: ParsedHeader,
    slug: str,
    fixtures: Mapping[str, dict[str, Any]],
    catalog: dict[str, dict[str, str]],
    entities_by_league: dict[str, list[EntityRow]],
) -> ClassifiedAlias | None:
    from mappers.control_plane.underdog_fixture_classify import (
        _alias_target,
        _resolve_code_entity,
    )

    alias_code, entity_type, player_token = _alias_target(store, header, slug, catalog)
    if not alias_code:
        return None
    entity = _resolve_code_entity(
        slug, alias_code, entity_type, entities_by_league.get(slug, []),
        fixtures.get(row.fixture_id), player_token=player_token,
        venue_name=(catalog.get(slug) or {}).get(alias_code, ""),
    )
    return _alias_status(
        slug, alias_code, entity_type, entity, entities_by_league.get(slug, []),
        row.ticker, row.fixture_id,
    )


def _alias_status(
    slug: str,
    code: str,
    entity_type: Literal["team", "player", "fighter"],
    entity: EntityRow | None,
    league_entities: list[EntityRow],
    ticker: str,
    fixture_id: str,
) -> ClassifiedAlias:
    from mappers.control_plane.underdog_fixture_classify import _underdog_code_owner

    if entity is None:
        status, reason = "skip", "unresolvable entity"
    elif _underdog_code_owner(league_entities, code, entity) is not None:
        status, reason, entity = "skip", "code owned elsewhere", None
    elif entity_has_underdog_code(entity, code):
        status, reason = "already_pinned", ""
    else:
        status, reason = "propose", ""
    return ClassifiedAlias(
        league=slug, code=code, entity_type=entity_type, status=status, reason=reason,
        canonical_key=str(entity.canonical_key) if entity else "",
        canonical_name=str(entity.canonical_name or "") if entity else "",
        evidence_ticker=ticker, fixture_id=fixture_id,
    )


def harvest_for_store(
    store: Any,
    csv_rows: Sequence[CsvMarketRow],
    *,
    environment: str,
    fixtures_by_id: Mapping[str, dict[str, Any]] | None = None,
    fixture_query_fn: FixtureQueryFn | None = None,
) -> HarvestEnvReport:
    """Classify alias, market-rule, and league gaps for one activated tip."""
    rid = store.current_rule_set_id
    if not rid:
        raise RuntimeError(f"{environment}: no current rule set")
    fixtures = dict(fixtures_by_id or {})
    missing_ids = sorted({r.fixture_id for r in csv_rows if r.fixture_id not in fixtures})
    if missing_ids:
        query = fixture_query_fn or (
            lambda ids: fetch_fixtures_by_ids(ids, project=os.environ.get("GCP_PROJECT"))
        )
        fixtures.update(query(missing_ids))

    catalog = team_catalog()
    entities = store.entities_for(rid)
    entities_by_league = _index_entities(entities)
    tip_rules = store.market_rules_for(rid)
    league_rows = {row.league: row for row in store.leagues_for(rid)}

    alias_keys: dict[tuple[str, str], ClassifiedAlias] = {}
    rule_keys: dict[tuple[str, str], ClassifiedMarketRule] = {}
    league_keys: dict[str, ClassifiedLeague] = {}

    for row in csv_rows:
        _classify_row(
            store, row, fixtures, catalog, entities_by_league, tip_rules,
            league_rows, alias_keys, rule_keys, league_keys,
        )

    return HarvestEnvReport(
        environment=environment,
        rule_set_id=rid,
        aliases=sorted(alias_keys.values(), key=lambda a: (a.league, a.code)),
        market_rules=sorted(rule_keys.values(), key=lambda r: (r.league, r.source_key)),
        leagues=sorted(league_keys.values(), key=lambda item: item.league),
    )


def build_alias_payloads(
    report: HarvestEnvReport,
    *,
    leagues: Sequence[str] | None = None,
) -> list[EntityAliasPayload]:
    """``entity_alias`` payloads for the propose bucket."""
    allowed = set(leagues) if leagues else None
    out: list[EntityAliasPayload] = []
    for item in report.aliases:
        if item.status != "propose":
            continue
        if allowed is not None and item.league not in allowed:
            continue
        out.append(
            EntityAliasPayload(
                league=item.league,
                canonical_key=item.canonical_key,
                entity_type=item.entity_type,
                canonical_name=item.canonical_name or None,
                aliases=[
                    AliasPin(
                        sportsbook=UNDERDOG_BOOK,
                        alias_kind="code",
                        alias_value=item.code,
                    ),
                ],
                evidence_refs=[
                    f"gap:udx:{item.evidence_ticker}",
                    f"optic:fixture:{item.fixture_id}",
                ],
            ),
        )
    return out


def build_market_rule_payloads(
    report: HarvestEnvReport,
    *,
    leagues: Sequence[str] | None = None,
) -> BatchChangesPayload:
    """``mapping_market_rules`` batch for observed propose rules."""
    allowed = set(leagues) if leagues else None
    pins: list[MarketRulePin] = []
    for item in report.market_rules:
        if item.status != "propose":
            continue
        if allowed is not None and item.league not in allowed:
            continue
        mt = market_type_for_venue(item.venue, item.product, item.period)
        if mt is None:
            continue
        pins.append(
            MarketRulePin(
                league=item.league,
                sportsbook=UNDERDOG_BOOK,
                rule_kind="taxonomy",
                source_key_type=SOURCE_KEY_TYPE,
                source_key=item.source_key,
                action="map",
                canonical_market_type=mt.value,
                priority=100,
                enabled=True,
                confidence="id_verified",
                match_operator="exact",
                notes="Underdog UDX fixture CSV harvest",
            ),
        )
    if not pins:
        return BatchChangesPayload()
    groups = [
        MappingMarketRulesPayload(
            league=league,
            rules=[pin for pin in pins if pin.league == league],
            evidence_refs=[f"gap:udx:fixture_csv:{league}"],
        )
        for league in sorted({lg for pin in pins for lg in (pin.league,) if lg})
    ]
    return BatchChangesPayload(market_rules=groups)



















def _index_entities(entities: Sequence[EntityRow]) -> dict[str, list[EntityRow]]:
    out: dict[str, list[EntityRow]] = {}
    for ent in entities:
        out.setdefault(str(ent.league), []).append(ent)
    return out


def _bucket_counts(rows: Sequence[Any], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(getattr(row, field))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _counts_by_league(
    rows: Sequence[Any],
    status_field: str,
    want: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if getattr(row, status_field) != want:
            continue
        league = str(row.league)
        counts[league] = counts.get(league, 0) + 1
    return counts


def _sample(rows: Sequence[Any], status: str, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.status != status:
            continue
        out.append({k: v for k, v in row.__dict__.items() if v})
        if len(out) >= limit:
            break
    return out
