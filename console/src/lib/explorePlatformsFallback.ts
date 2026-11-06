/** Fallback when /meta predates explore_platforms (restart API after deploy). */

import type { ExplorePlatform } from "../types";

export const EXPLORE_PLATFORMS_FALLBACK: ExplorePlatform[] = [
  { id: "kalshi", label: "Kalshi", sportsbook: "Kalshi", unmapped_inventory: true, missing_catalogue: false },
  { id: "crypto", label: "crypto.com", sportsbook: "crypto.com", unmapped_inventory: true, missing_catalogue: true },
  { id: "polymarket", label: "Polymarket", sportsbook: "Polymarket", unmapped_inventory: true, missing_catalogue: false },
  { id: "polymarket_usa", label: "Polymarket US", sportsbook: "Polymarket (USA)", unmapped_inventory: false, missing_catalogue: false },
  { id: "px", label: "ProphetX", sportsbook: "Prophet X", unmapped_inventory: false, missing_catalogue: false },
  { id: "novig", label: "Novig", sportsbook: "Novig", unmapped_inventory: false, missing_catalogue: false },
  { id: "underdog", label: "Underdog", sportsbook: "Underdog", unmapped_inventory: true, missing_catalogue: false },
  { id: "dkex", label: "DraftKings Exchange", sportsbook: "DKEX", unmapped_inventory: true, missing_catalogue: false },
  { id: "sxbet", label: "SX Bet", sportsbook: "SX Bet", unmapped_inventory: true, missing_catalogue: false },
  { id: "optic", label: "Optic", sportsbook: "optic", unmapped_inventory: false, missing_catalogue: false },
  { id: "txodds", label: "TxODDS", sportsbook: "txodds", unmapped_inventory: false, missing_catalogue: true },
];
