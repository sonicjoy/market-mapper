import { useState } from "react";

/** Page-header Refresh: disable + label while the query is in flight. */
export function RefreshButton({
  onClick,
  busy = false,
  disabled = false,
}: {
  onClick: () => void | Promise<unknown>;
  busy?: boolean;
  disabled?: boolean;
}) {
  const [localBusy, setLocalBusy] = useState(false);
  const refreshing = busy || localBusy;
  const blocked = refreshing || disabled;
  return (
    <button
      type="button"
      className="btn-ghost"
      disabled={blocked}
      aria-busy={refreshing}
      onClick={() => {
        if (blocked) {
          return;
        }
        setLocalBusy(true);
        void Promise.resolve(onClick()).finally(() => setLocalBusy(false));
      }}
    >
      {refreshing ? "Refreshing…" : "Refresh"}
    </button>
  );
}
