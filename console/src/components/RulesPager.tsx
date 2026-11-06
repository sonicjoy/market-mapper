import { pagerPageItems } from "../lib/pagerPages";
import { PAGE_SIZE_OPTIONS, parseLimit, type PageSize } from "../lib/rulesQuery";

export function RulesPager({
  count,
  page,
  pageSize,
  onPage,
  onPageSize,
}: {
  count: number;
  page: number;
  pageSize: number;
  onPage: (p: number) => void;
  onPageSize: (size: PageSize) => void;
}) {
  if (count === 0) return null;
  const from = page * pageSize + 1;
  const to = Math.min(count, (page + 1) * pageSize);
  const lastPage = Math.max(0, Math.ceil(count / pageSize) - 1);
  const pageItems = pagerPageItems(page, lastPage);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-3 py-2 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-300">
      <span>
        Showing {from}-{to} of {count}
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="input w-auto py-1"
          value={pageSize}
          aria-label="Rows per page"
          title="Rows per page"
          onChange={(e) => onPageSize(parseLimit(e.target.value))}
        >
          {PAGE_SIZE_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn-ghost"
          disabled={page <= 0}
          onClick={() => onPage(page - 1)}
        >
          Previous
        </button>
        <nav className="flex items-center gap-0.5" aria-label="Pagination">
          {pageItems.map((item, idx) =>
            item === "ellipsis" ? (
              <span
                key={`ellipsis-${idx}`}
                className="px-1 text-slate-400 dark:text-slate-500"
                aria-hidden
              >
                …
              </span>
            ) : (
              <button
                key={item}
                type="button"
                className={
                  item === page
                    ? "min-w-[2rem] rounded px-2 py-1 text-sm font-medium bg-brand-100 text-brand-900 dark:bg-brand-950 dark:text-brand-100"
                    : "btn-ghost min-w-[2rem] px-2 py-1"
                }
                aria-current={item === page ? "page" : undefined}
                onClick={() => onPage(item)}
              >
                {item + 1}
              </button>
            ),
          )}
        </nav>
        <button
          type="button"
          className="btn-ghost"
          disabled={page >= lastPage}
          onClick={() => onPage(page + 1)}
        >
          Next
        </button>
      </div>
    </div>
  );
}
