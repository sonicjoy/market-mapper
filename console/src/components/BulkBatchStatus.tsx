import { useQuery } from "@tanstack/react-query";

import { TERMINAL_JOB_STATUSES, getBulkBatch } from "../bulkOverrideApi";

/** Per-pair propagation status for one published batch; polls until every job is terminal. */
export function BulkBatchStatus({ batchId }: { batchId: string }) {
  const batch = useQuery({
    queryKey: ["bulk-override-batch", batchId],
    queryFn: () => getBulkBatch(batchId),
    refetchInterval: (query) => {
      const jobs = query.state.data?.jobs ?? [];
      return jobs.length && jobs.every((job) => TERMINAL_JOB_STATUSES.has(job.status)) ? false : 2000;
    },
  });
  if (batch.isError) return <p className="notice-red text-xs">Could not read the batch: {batch.error.message}</p>;
  if (!batch.data) return <p className="text-xs text-slate-500">Publishing…</p>;
  const counts = Object.entries(batch.data.counts)
    .map(([status, n]) => `${n} ${status.replaceAll("_", " ")}`)
    .join(" · ");
  return (
    <div className="card space-y-2">
      <p className="text-sm font-medium">
        Batch <span className="font-mono text-xs">{batch.data.batch_id.slice(0, 8)}</span>: {counts}
      </p>
      <p className="text-[11px] text-slate-500">
        Each override is read back from opticodds_mapping after one shared merge + fold+rank. "Accepted not
        materialised" means the row landed but is not yet the RFQ winner; check it on the Catalog page.
      </p>
      <table className="w-full text-left text-xs">
        <tbody>
          {batch.data.jobs.map((job) => (
            <tr key={job.job_id} className="border-t border-slate-100 dark:border-slate-800">
              <td className="py-1 pr-3 font-mono text-[11px]">
                {job.source_market_id} {job.source_selection_id}
              </td>
              <td className="py-1 pr-3 font-medium">{job.status}</td>
              <td className="py-1 text-slate-500">{job.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
