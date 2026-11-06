import { useEffect, useMemo, useRef } from "react";
import { useSearchParams, type SetURLSearchParams } from "react-router-dom";

import {
  hydratePageFilters,
  readPageFilters,
  writePageFilters,
  type FilterPage,
} from "./lib/pageFilters";

/** URL is live/shareable; sessionStorage restores a bare dock path once per mount. */
export function usePageFilters(page: FilterPage): [URLSearchParams, SetURLSearchParams] {
  const [params, setParams] = useSearchParams();
  const hydrated = useRef(false);
  const saved = useMemo(() => readPageFilters(page), [page]);
  const effective = useMemo(() => {
    if (hydrated.current) return params;
    return hydratePageFilters(params, saved) ?? params;
  }, [params, saved]);

  useEffect(() => {
    if (hydrated.current) return;
    const patched = hydratePageFilters(params, saved);
    if (patched) {
      setParams(patched, { replace: true });
      return;
    }
    hydrated.current = true;
  }, [params, saved, setParams]);

  useEffect(() => {
    writePageFilters(page, effective);
  }, [page, effective]);

  return [effective, setParams];
}
