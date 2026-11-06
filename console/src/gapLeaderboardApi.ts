/** Explore -> Gap leaderboard: every venue's mapping gaps, ranked. */

import { api } from "./api";

type Counts = {
  /** Distinct failed RFQs in the window (a sum of children when `demand_is_sum`). */
  demand: number;
  /** Distinct failed legs (selections) in the window. */
  legs: number;
  /** Unmapped selections: catalogue-unmapped where a catalogue is wired, else failed legs. */
  unmapped: number;
};

export type GapMarket = Counts & {
  market: string;
  catalogue_total: number | null;
  last_seen: string | null;
  fix_link: string | null;
};

export type GapFixture = Counts & {
  fixture_key: string;
  name: string;
  start_date: string | null;
  ttko_hours: number | null;
  kickoff_date_only: boolean;
  catalogue_total: number | null;
  last_seen: string | null;
  fix_link: string | null;
  demand_is_sum?: boolean;
  markets: GapMarket[];
};

export type GapLeague = Counts & {
  key: string;
  label: string;
  tip_league: string | null;
  sport: string | null;
  in_tip: boolean;
  hint: string;
  fixtures: GapFixture[];
};

export type GapPlatform = Counts & {
  id: string;
  label: string;
  demand_is_sum: boolean;
  leagues_not_in_tip: number;
  leagues: GapLeague[];
};

export type GapMarketOption = { name: string; demand: number; unmapped: number; fixtures: number };

export type GapLeaderboardResponse = {
  hours: number;
  sort: string;
  platforms: GapPlatform[];
  market_options: GapMarketOption[];
  /** When the server's cached BigQuery result was fetched (1h cache). */
  cached_at?: string | null;
  error: string | null;
};

export function listGapLeaderboard(opts: {
  hours: number;
  platforms?: string[];
  markets?: string[];
  kickoffFrom?: string;
  kickoffTo?: string;
  sort?: string;
  refresh?: boolean;
}) {
  const params = new URLSearchParams({ hours: String(opts.hours) });
  for (const value of opts.platforms ?? []) params.append("platform", value);
  for (const value of opts.markets ?? []) params.append("market", value);
  if (opts.kickoffFrom) params.set("kickoff_from", opts.kickoffFrom);
  if (opts.kickoffTo) params.set("kickoff_to", opts.kickoffTo);
  if (opts.sort) params.set("sort", opts.sort);
  if (opts.refresh) params.set("refresh", "true");
  return api<GapLeaderboardResponse>(`/console/gap-leaderboard?${params.toString()}`);
}
