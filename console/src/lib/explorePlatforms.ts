/** Explore platform ids from GET /meta (console_platforms.py). */

import { useQuery } from "@tanstack/react-query";

import { getMeta } from "../api";
import type { ExplorePlatform } from "../types";

import { EXPLORE_PLATFORMS_FALLBACK } from "./explorePlatformsFallback";

export function useExplorePlatforms(): ExplorePlatform[] {
  const { data } = useQuery({ queryKey: ["meta"], queryFn: getMeta });
  const fromMeta = data?.explore_platforms;
  return fromMeta && fromMeta.length > 0 ? fromMeta : EXPLORE_PLATFORMS_FALLBACK;
}

export function platformLabel(platforms: ExplorePlatform[], id: string): string {
  const row = platforms.find((p) => p.id === id);
  return row?.label ?? id;
}

export function platformsForUnmapped(platforms: ExplorePlatform[]): ExplorePlatform[] {
  const wired = platforms.filter((p) => p.unmapped_inventory);
  return wired.length > 0 ? wired : platforms;
}

export function platformsForMissing(platforms: ExplorePlatform[]): ExplorePlatform[] {
  return platforms.length > 0 ? platforms : [];
}
