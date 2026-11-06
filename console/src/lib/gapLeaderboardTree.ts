/** Pure helpers for the Gap leaderboard tree: client-side search and node ids. */

import type { GapFixture, GapLeague, GapPlatform } from "../gapLeaderboardApi";

function hit(needle: string, ...values: Array<string | null | undefined>): boolean {
  return values.some((v) => (v ?? "").toLowerCase().includes(needle));
}

function fixtureMatches(needle: string, league: GapLeague, fx: GapFixture): boolean {
  return (
    hit(needle, league.label, league.tip_league, league.hint, fx.name, fx.fixture_key) ||
    fx.markets.some((m) => hit(needle, m.market))
  );
}

/** Keep fixtures matching the search (league, fixture or market name); drop emptied leagues. */
export function searchPlatforms(platforms: GapPlatform[], q: string): GapPlatform[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return platforms;
  return platforms.map((p) => ({
    ...p,
    leagues: p.leagues
      .map((lg) => ({ ...lg, fixtures: lg.fixtures.filter((fx) => fixtureMatches(needle, lg, fx)) }))
      .filter((lg) => lg.fixtures.length > 0),
  }));
}

export function platformNodeId(platform: string): string {
  return `p:${platform}`;
}

export function leagueNodeId(platform: string, league: string): string {
  return `l:${platform}:${league}`;
}

export function fixtureNodeId(platform: string, league: string, fixture: string): string {
  return `f:${platform}:${league}:${fixture}`;
}
