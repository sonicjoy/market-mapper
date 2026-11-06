"""Underdog UDX team codes + venue display names for control-plane alias pins."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from mappers.canonical_codes import names_fit
from mappers.control_plane.rows import EntityRow

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DOC = _REPO_ROOT / "docs" / "adding-underdog.md"
_DEFAULT_GOLDEN = _REPO_ROOT / "docs" / "underdog" / "udx_markets_golden_2026-09-23.json"
_DEFAULT_TEAM_CSV = _REPO_ROOT / "docs" / "underdog" / "team_aliases_2026-09-23.csv"

_VENUE_LEAGUE_TO_SLUG = {
    "NFL": "nfl",
    "MLB": "mlb",
    "WNBA": "wnba",
    "NCAAMFB": "ncaaf",
    "NCAAF": "ncaaf",
}

_TABLE_ROW = re.compile(r"^\|\s*`([A-Z0-9]+)`\s*\|\s*(.+?)\s*\|\s*$")
_SECTION = re.compile(r"^###\s+(MLB|NFL|WNBA)\s+—", re.MULTILINE)
_WIN_DESC = re.compile(
    r"Resolves Yes if (?:the )?(.+?) wins?(?: the)?",
    re.IGNORECASE,
)

_INLINE_LEAGUE_SLUG = {
    "MLB": "mlb",
    "NFL": "nfl",
    "WNBA": "wnba",
}


def parse_appendix_team_tables(
    doc_path: Path | None = None,
) -> dict[str, dict[str, str]]:
    """Parse Appendix B inline tables (MLB, NFL, WNBA) from ``adding-underdog.md``."""
    path = doc_path or _DEFAULT_DOC
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    for match in _SECTION.finditer(text):
        league_key = match.group(1)
        slug = _INLINE_LEAGUE_SLUG.get(league_key)
        if slug is None:
            continue
        start = match.end()
        next_heading = text.find("\n### ", start)
        chunk = text[start : next_heading if next_heading >= 0 else None]
        codes: dict[str, str] = {}
        for line in chunk.splitlines():
            row = _TABLE_ROW.match(line.strip())
            if row is None:
                continue
            codes[row.group(1).upper()] = row.group(2).strip()
        if codes:
            out[slug] = codes
    return out


def ncaaf_codes_from_golden(golden_path: Path | None = None) -> dict[str, str]:
    """Learn NCAAF codes from ``UDXNCAAMFBGAMEWIN`` rows in the golden catalogue."""
    path = golden_path or _DEFAULT_GOLDEN
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, object]] = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key.startswith("_") or not isinstance(value, list):
                continue
            rows.extend(item for item in value if isinstance(item, dict))
    elif isinstance(raw, list):
        rows = [item for item in raw if isinstance(item, dict)]
    codes: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "")
        family = ticker.split("_", 1)[0] if ticker else ""
        if "NCAAMFB" not in family or "GAMEWIN" not in family:
            continue
        code = ticker.rsplit("_", 1)[-1].upper()
        if code in codes:
            continue
        desc = str(row.get("description") or "")
        hit = _WIN_DESC.search(desc)
        if hit:
            codes[code] = hit.group(1).strip()
    return codes


def resolve_team_entity(
    entities: list[EntityRow],
    code: str,
    venue_name: str,
) -> EntityRow | None:
    """Pick the tip entity that should own a Underdog ``code`` alias."""
    code_u = code.strip().upper()
    typed = [e for e in entities if e.enabled and not e.tombstone]
    for entity in typed:
        if str(entity.canonical_key or "").upper() == code_u:
            return entity
    for entity in typed:
        for alias in entity.aliases or []:
            if str(alias.get("alias_kind") or "") != "code":
                continue
            if str(alias.get("alias_value") or "").upper() == code_u:
                return entity
    for entity in typed:
        name = str(entity.canonical_name or "").strip()
        if name and names_fit(venue_name, name, player=False):
            return entity
    return None


def entity_has_underdog_code(entity: EntityRow, code: str) -> bool:
    code_u = code.strip().upper()
    for alias in getattr(entity, "aliases", None) or []:
        if str(alias.get("sportsbook") or "") != "underdog":
            continue
        if str(alias.get("alias_kind") or "") != "code":
            continue
        if str(alias.get("alias_value") or "").upper() == code_u:
            return True
    return False


def load_team_aliases_csv(csv_path: Path | None = None) -> dict[str, dict[str, str]]:
    """Optional full team table (NCAAF lives here when the CSV is populated)."""
    path = csv_path or _DEFAULT_TEAM_CSV
    if not path.is_file() or path.stat().st_size == 0:
        return {}
    out: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return {}
        fields = {name.strip().lower(): name for name in reader.fieldnames}
        code_key = fields.get("code") or fields.get("team_code") or fields.get("alias")
        name_key = fields.get("venue_name") or fields.get("name") or fields.get("team_name")
        league_key = fields.get("venue_league") or fields.get("league") or fields.get("sport")
        if not code_key or not name_key:
            return {}
        for row in reader:
            code = str(row.get(code_key) or "").strip().upper()
            name = str(row.get(name_key) or "").strip()
            if not code or not name:
                continue
            league_raw = str(row.get(league_key) or "").strip().upper() if league_key else ""
            slug = _VENUE_LEAGUE_TO_SLUG.get(league_raw)
            if slug is None:
                continue
            out.setdefault(slug, {})[code] = name
    return out


def team_catalog(
    *,
    doc_path: Path | None = None,
    golden_path: Path | None = None,
    csv_path: Path | None = None,
    include_ncaaf: bool = True,
) -> dict[str, dict[str, str]]:
    """League slug → {UDX code → venue display name}."""
    catalog = dict(parse_appendix_team_tables(doc_path))
    for slug, codes in load_team_aliases_csv(csv_path).items():
        catalog.setdefault(slug, {}).update(codes)
    if include_ncaaf:
        ncaaf = ncaaf_codes_from_golden(golden_path)
        bucket = catalog.setdefault("ncaaf", {})
        for code, name in ncaaf.items():
            bucket.setdefault(code, name)
    return catalog
