import type { SortDir } from "../lib/rulesQuery";

/** Clickable table header that toggles column sort. */
export function SortTh({
  column,
  label,
  sort,
  dir,
  onSort,
}: {
  column: string;
  label: string;
  sort: string;
  dir: SortDir;
  onSort: (column: string) => void;
}) {
  const active = sort === column;
  const indicator = !active ? "" : dir === "desc" ? " ↓" : " ↑";
  return (
    <th className="px-3 py-2">
      <button
        type="button"
        className={`inline-flex items-center uppercase ${active ? "text-slate-800 dark:text-slate-100" : ""}`}
        onClick={() => onSort(column)}
      >
        {label}
        {indicator}
      </button>
    </th>
  );
}
