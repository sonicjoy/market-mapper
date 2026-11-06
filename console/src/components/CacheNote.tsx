import { formatFixtureStart } from "../lib/coverageList";

/** States how old a cached BigQuery snapshot is and that Refresh forces a new (billed) scan. */
export function CacheNote({ cachedAt, scanCost }: { cachedAt?: string | null; scanCost: string }) {
  const when = cachedAt ? formatFixtureStart(cachedAt) : null;
  return (
    <p className="mb-2 text-xs text-slate-500" role="note">
      {when ? `Data from a BigQuery snapshot taken ${when}. ` : ""}
      Snapshots are cached for 1 hour because each scan costs {scanCost}; Refresh forces a new scan now.
    </p>
  );
}
