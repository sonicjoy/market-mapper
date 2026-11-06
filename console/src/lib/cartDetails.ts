/** Cart-row detail lines from staged alias / league payloads. */

function asText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (value == null) return "";
  return String(value).trim();
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

type ExchangeLine = {
  sportsbook: string;
  enabled: boolean;
  parser_profile: string;
  source_league_id: string;
};

function exchangesFrom(payload: Record<string, unknown>): ExchangeLine[] {
  const raw = payload.exchanges;
  if (!Array.isArray(raw)) return [];
  const out: ExchangeLine[] = [];
  for (const row of raw) {
    const rec = asRecord(row);
    if (!rec) continue;
    const sportsbook = asText(rec.sportsbook);
    if (!sportsbook) continue;
    out.push({
      sportsbook,
      enabled: rec.enabled !== false,
      parser_profile: asText(rec.parser_profile),
      source_league_id: asText(rec.source_league_id),
    });
  }
  return out;
}

function formatOnBook(ex: ExchangeLine): string {
  const bits = [ex.parser_profile, ex.source_league_id].filter(Boolean);
  return bits.length ? `${ex.sportsbook} (${bits.join(" · ")})` : ex.sportsbook;
}

export function leagueCartLines(payload: Record<string, unknown>): string[] {
  const sport = asText(payload.sport);
  const optic = asText(payload.optic_league_id);
  const fixture = asText(payload.fixture_source);
  const meta = [
    sport && `sport ${sport}`,
    optic && `optic ${optic}`,
    fixture && `fixture ${fixture}`,
  ].filter(Boolean);
  const lines: string[] = [];
  if (meta.length) lines.push(meta.join(" · "));
  if (payload.enabled === false) lines.push("league disabled");
  const books = exchangesFrom(payload);
  const on = books.filter((ex) => ex.enabled);
  const off = books.filter((ex) => !ex.enabled);
  if (on.length) lines.push(`on  ${on.map(formatOnBook).join(", ")}`);
  if (off.length) lines.push(`off ${off.map((ex) => ex.sportsbook).join(", ")}`);
  const clone = asText(payload.clone_market_rules_from);
  if (clone) lines.push(`clone markets from ${clone}`);
  return lines;
}

export function aliasCartLines(payload: Record<string, unknown>): string[] {
  const league = asText(payload.league);
  const name = asText(payload.canonical_name) || asText(payload.canonical_key);
  const entity = asText(payload.entity_type) || "team";
  const target = [entity, name].filter(Boolean).join(" ");
  const suffix = league ? ` (${league})` : "";
  const raw = payload.aliases;
  if (!Array.isArray(raw) || raw.length === 0) {
    return target ? [`${target}${suffix}`] : [];
  }
  const lines: string[] = [];
  for (const row of raw) {
    const rec = asRecord(row);
    if (!rec) continue;
    const book = asText(rec.sportsbook) || "unknown";
    const kind = asText(rec.alias_kind);
    const value = asText(rec.alias_value) || "?";
    const left = [book, kind, value].filter(Boolean).join(" ");
    if (rec.remove === true) {
      lines.push(`remove ${left} from ${target}${suffix}`);
      continue;
    }
    lines.push(`${left} → ${target}${suffix}`);
  }
  if (payload.reassign === true) lines.push("reassign if already pinned");
  return lines;
}
