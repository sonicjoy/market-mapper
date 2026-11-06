import type { ReactNode } from "react";

// The one page header for every content page: title (+ optional description) on the LEFT, optional
// actions (Refresh / Verify / Submit …) on the RIGHT. Keeps every page's masthead identical — don't
// hand-roll a header `<div>`; use this. Same shape as mm-trading-dash's PageHeader.
export function PageHeader({
  title,
  description,
  children,
}: {
  title: string;
  description?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="mb-4 flex items-start justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        {/* 12.5px at slate-600, not 12px at slate-500: the estate scored that pair at 3.8:1 and called
            it unreadable. Matches mm-trading-dash. */}
        {description && (
          <p className="text-[12.5px] leading-snug text-slate-600 dark:text-slate-300">{description}</p>
        )}
      </div>
      {children && <div className="flex shrink-0 items-center gap-2">{children}</div>}
    </div>
  );
}
