/** URL state for Venue gaps (platform + phase + search + unmapped-only + sort + window + markets). */

import {
  DEFAULT_FIXTURE_PHASE,
  parseFixturePhase,
  type FixturePhase,
} from "../components/FixturePhaseTabs";

export const VENUE_GAP_PLATFORMS = [{ value: "crypto", label: "crypto.com" }] as const;
export const DEFAULT_VENUE_GAP_PLATFORM = "crypto";

export const VENUE_GAP_SORTS = [
  { value: "unmapped", label: "Unmapped count" },
  { value: "demand", label: "Failed RFQs (48h)" },
  { value: "start", label: "Kick-off" },
] as const;

export type VenueGapSort = (typeof VENUE_GAP_SORTS)[number]["value"];
export const DEFAULT_VENUE_GAP_SORT: VenueGapSort = "unmapped";

export type VenueGapsQueryState = {
  platform: string;
  phase: FixturePhase;
  q: string;
  unmappedOnly: boolean;
  sort: VenueGapSort;
  /** Market names (catalogue contract_type); empty means all. */
  markets: string[];
  /** Kickoff window bounds, UTC wall time as `YYYY-MM-DDTHH:MM` (datetime-local shape). */
  kickoffFrom: string;
  kickoffTo: string;
};

function parseSort(raw: string | null): VenueGapSort {
  return VENUE_GAP_SORTS.find((row) => row.value === raw)?.value ?? DEFAULT_VENUE_GAP_SORT;
}

export function readVenueGapsQuery(params: URLSearchParams): VenueGapsQueryState {
  return {
    platform: params.get("platform") || DEFAULT_VENUE_GAP_PLATFORM,
    phase: parseFixturePhase(params.get("phase")),
    q: params.get("q") ?? "",
    unmappedOnly: params.get("all") !== "1",
    sort: parseSort(params.get("sort")),
    markets: params
      .getAll("market")
      .map((v) => v.trim())
      .filter(Boolean),
    kickoffFrom: params.get("from") ?? "",
    kickoffTo: params.get("to") ?? "",
  };
}

export function writeVenueGapsQuery(
  current: URLSearchParams,
  patch: Partial<VenueGapsQueryState>,
): URLSearchParams {
  const next = { ...readVenueGapsQuery(current), ...patch };
  const params = new URLSearchParams();
  if (next.platform !== DEFAULT_VENUE_GAP_PLATFORM) params.set("platform", next.platform);
  if (next.phase !== DEFAULT_FIXTURE_PHASE) params.set("phase", next.phase);
  if (next.q) params.set("q", next.q);
  if (!next.unmappedOnly) params.set("all", "1");
  if (next.sort !== DEFAULT_VENUE_GAP_SORT) params.set("sort", next.sort);
  for (const value of next.markets) params.append("market", value);
  if (next.kickoffFrom) params.set("from", next.kickoffFrom);
  if (next.kickoffTo) params.set("to", next.kickoffTo);
  return params;
}
