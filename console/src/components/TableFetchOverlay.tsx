/** Spinner overlay while react-query refetches (pagination, filters, refresh). */

export function TableFetchOverlay({
  active,
  label = "Loading…",
}: {
  active: boolean;
  label?: string;
}) {
  if (!active) return null;
  return (
    <div
      className="absolute inset-0 z-10 flex items-center justify-center bg-white/65 dark:bg-slate-950/65"
      role="status"
      aria-live="polite"
      aria-label={label}
    >
      <div className="flex flex-col items-center gap-2">
        <span
          className="inline-block h-8 w-8 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600 dark:border-slate-600 dark:border-t-brand-400"
          aria-hidden
        />
        <span className="text-xs font-medium text-slate-600 dark:text-slate-300">{label}</span>
      </div>
    </div>
  );
}
