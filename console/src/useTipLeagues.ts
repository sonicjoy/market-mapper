import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { searchRules } from "./api";
import type { LeagueRuleRow } from "./types";

/** Tip league slugs + rows for Mapper dropdowns and Editor inherit. */
export function useTipLeagues() {
  const query = useQuery({
    queryKey: ["tip-leagues-full"],
    queryFn: () => searchRules("", "leagues", { limit: 500, offset: 0 }),
    staleTime: 5 * 60 * 1000,
  });
  const bySlug = useMemo(() => {
    const out: Record<string, LeagueRuleRow> = {};
    for (const row of query.data?.leagues ?? []) {
      const slug = row.league?.trim();
      if (slug) out[slug] = row;
    }
    return out;
  }, [query.data]);
  const slugs = useMemo(
    () => Object.keys(bySlug).sort((a, b) => a.localeCompare(b)),
    [bySlug],
  );
  return { ...query, data: slugs, bySlug };
}
