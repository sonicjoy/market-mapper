import type { ReactNode } from "react";

type Props = {
  pills?: { id: string; label: string }[];
  activePill?: string;
  onPill?: (id: string) => void;
  list: ReactNode;
  listFooter?: ReactNode;
  detail: ReactNode;
};

export function ExplorerShell({
  pills = [],
  activePill,
  onPill,
  list,
  listFooter,
  detail,
}: Props) {
  return (
    <div className="grid min-h-[32rem] grid-cols-1 gap-4 lg:grid-cols-[18rem_1fr]">
      <div className="card flex flex-col overflow-hidden p-0">
        {pills.length > 0 && onPill ? (
          <div
            role="tablist"
            className="flex flex-wrap gap-0 border-b border-slate-200 dark:border-slate-700"
          >
            {pills.map((pill) => (
              <button
                key={pill.id}
                type="button"
                role="tab"
                aria-selected={pill.id === activePill}
                className={`-mb-px border-b-2 px-3 py-2 text-xs font-medium ${
                  pill.id === activePill
                    ? "border-brand-600 text-brand-800 dark:border-brand-400 dark:text-brand-200"
                    : "border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200"
                }`}
                onClick={() => onPill(pill.id)}
              >
                {pill.label}
              </button>
            ))}
          </div>
        ) : null}
        <div className="min-h-0 flex-1 overflow-auto p-2">{list}</div>
        {listFooter}
      </div>
      <div className="card min-h-0 overflow-auto p-4">{detail}</div>
    </div>
  );
}
