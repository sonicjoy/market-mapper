import { useEffect, useRef, useState } from "react";

type Option = { value: string; label?: string };

function normalize(options: readonly string[] | Option[]): Option[] {
  return options.map((o) => (typeof o === "string" ? { value: o, label: o } : o));
}

/** Checkbox dropdown; empty selection means "all". */
export function MultiSelect({
  id,
  label,
  values,
  onChange,
  options,
  emptyLabel = "All",
  searchable = false,
}: {
  id: string;
  label: string;
  values: string[];
  onChange: (next: string[]) => void;
  options: readonly string[] | Option[];
  emptyLabel?: string;
  /** Adds a filter box and a Clear action above the list (long option sets). */
  searchable?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [needle, setNeedle] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const allOpts = normalize(options);
  const want = needle.trim().toLowerCase();
  const opts = want
    ? allOpts.filter((o) => `${o.value} ${o.label ?? ""}`.toLowerCase().includes(want))
    : allOpts;
  const summary = values.length ? `${label} (${values.length})` : `${label}: ${emptyLabel}`;

  useEffect(() => {
    function onDoc(event: MouseEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function toggle(value: string, checked: boolean) {
    onChange(checked ? [...values, value] : values.filter((v) => v !== value));
  }

  return (
    <div ref={root} className="relative min-w-[16rem] flex-[1_1_16rem]">
      <button
        id={id}
        type="button"
        className="input text-left"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={summary}
        onClick={() => setOpen((v) => !v)}
      >
        {summary}
      </button>
      {open ? (
        <div
          role="listbox"
          aria-multiselectable="true"
          className="absolute z-20 mt-1 max-h-64 w-full overflow-auto rounded-md border border-slate-200 bg-white py-1 shadow-lg dark:border-slate-700 dark:bg-slate-900"
        >
          {searchable ? (
            <div className="sticky top-0 flex items-center gap-1 border-b border-slate-100 bg-white px-2 py-1 dark:border-slate-800 dark:bg-slate-900">
              <input
                className="input h-7 flex-1 text-xs"
                placeholder="Filter…"
                aria-label={`Filter ${label}`}
                value={needle}
                onChange={(e) => setNeedle(e.target.value)}
              />
              {values.length ? (
                <button type="button" className="btn-ghost text-xs" onClick={() => onChange([])}>
                  Clear
                </button>
              ) : null}
            </div>
          ) : null}
          {searchable && opts.length === 0 ? (
            <p className="px-2 py-1 text-xs text-slate-500">No matches</p>
          ) : null}
          {opts.map((opt) => (
            <label
              key={opt.value}
              className="flex cursor-pointer items-center gap-2 px-2 py-1 text-sm hover:bg-slate-50 dark:hover:bg-slate-800"
            >
              <input
                type="checkbox"
                checked={values.includes(opt.value)}
                onChange={(e) => toggle(opt.value, e.target.checked)}
              />
              <span>{opt.label ?? opt.value}</span>
            </label>
          ))}
        </div>
      ) : null}
    </div>
  );
}
