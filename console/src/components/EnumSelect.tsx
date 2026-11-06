type Option = { value: string; label?: string };

function normalize(options: readonly string[] | Option[]): Option[] {
  return options.map((o) => (typeof o === "string" ? { value: o, label: o } : o));
}

/** Select for a closed set; keeps an unknown current value as a selectable option. */
export function EnumSelect({
  id,
  value,
  onChange,
  options,
  allowEmpty,
  emptyLabel = "Select...",
}: {
  id: string;
  value: string;
  onChange: (next: string) => void;
  options: readonly string[] | Option[];
  allowEmpty?: boolean;
  emptyLabel?: string;
}) {
  const opts = normalize(options);
  if (value && !opts.some((o) => o.value === value)) {
    opts.unshift({ value, label: `${value} (current)` });
  }
  return (
    <select
      id={id}
      className="input"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      {allowEmpty ? <option value="">{emptyLabel}</option> : null}
      {opts.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label ?? o.value}
        </option>
      ))}
    </select>
  );
}
