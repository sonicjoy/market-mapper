/** Inherit Editor league fields from a tip row when the slug already exists. */

import { DEFAULT_FIXTURE_HORIZON_HOURS } from "../entryEnums";
import type { LeagueRuleRow } from "../types";

export type LeagueFormPrefill = {
  sport?: string;
  opticLeagueId?: string;
  fixtureHorizonHours?: number;
  exchanges?: Record<string, unknown>[];
};

function tipForSlug(slug: string, tip?: LeagueRuleRow): LeagueRuleRow | undefined {
  const key = slug.trim();
  if (!key || !tip) return undefined;
  return tip.league.trim() === key ? tip : undefined;
}

/** Location-state fields win; otherwise copy the matching tip row. */
export function leagueFormPrefill(args: {
  slug: string;
  tip?: LeagueRuleRow;
  explicitSport?: string;
  explicitOptic?: string;
  explicitHorizon?: number;
  explicitExchanges?: Record<string, unknown>[];
}): LeagueFormPrefill {
  const tip = tipForSlug(args.slug, args.tip);
  const lockedSport = (args.explicitSport ?? "").trim();
  const lockedOptic = (args.explicitOptic ?? "").trim();
  const out: LeagueFormPrefill = {};
  if (lockedSport) out.sport = lockedSport;
  else if (tip?.sport?.trim()) out.sport = tip.sport.trim();
  if (lockedOptic) out.opticLeagueId = lockedOptic;
  else if (tip?.optic_league_id?.trim()) out.opticLeagueId = tip.optic_league_id.trim();
  if (
    args.explicitHorizon != null &&
    Number.isFinite(args.explicitHorizon) &&
    args.explicitHorizon > 0
  ) {
    out.fixtureHorizonHours = args.explicitHorizon;
  } else if (tip != null) {
    const hours = tip.fixture_horizon_hours;
    out.fixtureHorizonHours =
      typeof hours === "number" && Number.isFinite(hours) && hours > 0
        ? hours
        : DEFAULT_FIXTURE_HORIZON_HOURS;
  }
  if (args.explicitExchanges) out.exchanges = args.explicitExchanges;
  else if (tip?.exchanges) out.exchanges = tip.exchanges as Record<string, unknown>[];
  return out;
}
