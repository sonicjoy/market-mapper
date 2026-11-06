import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { flagMapping, resolveMappingFlag, type MappingRiskRow } from "../mappingRiskApi";

/** Flag a mapping as an error, or resolve an open flag. Never un-maps: that goes through Proposed. */
export function MappingRiskFlagCell({ row }: { row: MappingRiskRow }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const open = row.flag?.status === "open";
  const mutation = useMutation({
    mutationFn: () => (open ? resolveMappingFlag(row.fingerprint, note) : flagMapping(row, note)),
    onSuccess: () => {
      setEditing(false);
      setNote("");
      void queryClient.invalidateQueries({ queryKey: ["mapping-risk"] });
    },
  });

  if (!editing) {
    return (
      <div className="space-y-1">
        {row.flag ? (
          <p className={open ? "notice-red text-[11px]" : "text-[11px] text-slate-500"}>
            {open ? "Flagged" : "Resolved"} by {open ? row.flag.flagged_by : row.flag.resolved_by}:{" "}
            {open ? row.flag.note : row.flag.resolution}
          </p>
        ) : null}
        <button type="button" className="btn-ghost text-xs" onClick={() => setEditing(true)}>
          {open ? "Resolve" : row.flag ? "Flag again" : "Flag as error"}
        </button>
      </div>
    );
  }
  return (
    <form
      className="space-y-1"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate();
      }}
    >
      <textarea
        className="input h-16 w-full text-xs"
        placeholder={open ? "How was it settled? (fixed via Proposed P-..., false alarm, ...)" : "Why is this mapping wrong?"}
        aria-label={open ? "Resolution" : "Why this mapping is wrong"}
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="flex gap-1">
        <button type="submit" className="btn-primary text-xs" disabled={mutation.isPending || !note.trim()}>
          {mutation.isPending ? "Saving…" : open ? "Resolve flag" : "Flag"}
        </button>
        <button type="button" className="btn-ghost text-xs" onClick={() => setEditing(false)}>
          Cancel
        </button>
      </div>
      {mutation.isError ? <p className="notice-red text-[11px]">{mutation.error.message}</p> : null}
    </form>
  );
}
