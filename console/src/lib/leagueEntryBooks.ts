/** Normalize league exchange pins for Editor display and submit. */

import { defaultParserProfile } from "../entryEnums";
import { SPORTSBOOKS } from "../entryEnums";

export type BookPinState = {
  enabled: boolean;
  source_league_id: string;
  parser_profile: string;
  settings: Record<string, unknown>;
};

const CRYPTO_GROUPING: Record<string, string> = {
  soccer: "SOCCER",
  tennis: "TENNIS",
  esports: "ESPORT",
  mma: "MMA",
  boxing: "MMA",
};

function cryptoSportGrouping(sport: string, metaLeague: string): string {
  const sportKey = sport.trim().toLowerCase();
  const meta = metaLeague.trim().toUpperCase();
  if (sportKey === "football" && (meta === "NFL" || meta === "CFB")) return meta;
  if (sportKey === "basketball" && (meta === "NBA" || meta === "WNBA" || meta === "CBB")) {
    return meta;
  }
  return CRYPTO_GROUPING[sportKey] ?? meta;
}

export function emptyBooks(): Record<string, BookPinState> {
  const out: Record<string, BookPinState> = {};
  for (const book of SPORTSBOOKS) {
    out[book] = {
      enabled: false,
      source_league_id: "",
      parser_profile: defaultParserProfile(book),
      settings: {},
    };
  }
  return out;
}

function settingsOf(raw: Record<string, unknown>): Record<string, unknown> {
  const settings = raw.settings;
  return settings && typeof settings === "object" && !Array.isArray(settings)
    ? { ...(settings as Record<string, unknown>) }
    : {};
}

/** Read the source id the operator sees (some books keep it in settings). */
export function exchangeSourceId(book: string, raw: Record<string, unknown>): string {
  const direct = String(raw.source_league_id ?? "").trim();
  if (direct) return direct;
  const settings = settingsOf(raw);
  if (book === "polymarket" || book === "polymarket_usa") {
    return String(settings.slug_prefix ?? "").trim();
  }
  if (book === "novig") return String(settings.league ?? "").trim();
  if (book === "underdog" || book === "dkex") return String(settings.league ?? "").trim();
  if (book === "crypto.com") return String(settings.league ?? "").trim();
  if (book === "px") {
    const tid = settings.tournament_id;
    return tid != null && String(tid).trim() ? String(tid).trim() : "";
  }
  return "";
}

export function booksFromExchanges(
  exchanges?: Record<string, unknown>[],
): Record<string, BookPinState> {
  const out = emptyBooks();
  for (const raw of exchanges ?? []) {
    const sportsbook = String(raw.sportsbook ?? "").trim();
    if (!sportsbook) continue;
    if (!out[sportsbook]) {
      out[sportsbook] = {
        enabled: false,
        source_league_id: "",
        parser_profile: defaultParserProfile(sportsbook),
        settings: {},
      };
    }
    out[sportsbook] = {
      enabled: raw.enabled !== false,
      source_league_id: exchangeSourceId(sportsbook, raw),
      parser_profile: String(raw.parser_profile ?? defaultParserProfile(sportsbook)),
      settings: settingsOf(raw),
    };
  }
  return out;
}

/** Mirror source_league_id into settings keys classify reads. */
export function leagueMetaFromExchanges(
  exchanges?: Record<string, unknown>[],
): {
  entity_type: string;
  alias_enforcement: string;
  runshop_enabled: boolean;
} {
  const optic = (exchanges ?? []).find(
    (row) => String(row.sportsbook ?? "").trim() === "optic",
  );
  const settings = optic ? settingsOf(optic) : {};
  return {
    entity_type: String(settings.entity_type ?? "").trim(),
    alias_enforcement: String(settings.alias_enforcement ?? "raise").trim() || "raise",
    runshop_enabled: Boolean(settings.runshop_enabled),
  };
}

export function exchangePayload(
  sportsbook: string,
  pin: BookPinState,
  opts?: { sport?: string },
): Record<string, unknown> {
  const settings = { ...(pin.settings ?? {}) };
  const raw = pin.source_league_id.trim();
  const source =
    sportsbook === "underdog" || sportsbook === "dkex" ? raw.toUpperCase() : raw;
  if (sportsbook === "polymarket" || sportsbook === "polymarket_usa") {
    if (source) settings.slug_prefix = source;
    else delete settings.slug_prefix;
  }
  if (sportsbook === "novig") {
    if (source) settings.league = source;
    else delete settings.league;
  }
  if (sportsbook === "underdog" || sportsbook === "dkex") {
    if (source) settings.league = source.toUpperCase();
    else delete settings.league;
  }
  if (sportsbook === "crypto.com") {
    if (source) {
      settings.league = source;
      if (!settings.sport_grouping && opts?.sport) {
        settings.sport_grouping = cryptoSportGrouping(opts.sport, source);
      }
    } else {
      delete settings.league;
    }
  }
  if (sportsbook === "px") {
    if (source) {
      const tid = Number(source);
      if (!Number.isNaN(tid)) settings.tournament_id = tid;
    } else {
      delete settings.tournament_id;
    }
  }
  return {
    sportsbook,
    enabled: true,
    parser_profile: pin.parser_profile || defaultParserProfile(sportsbook),
    source_league_id: source || null,
    settings,
  };
}

