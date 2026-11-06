type Props = {
  mapped: number;
  expected: number;
};

export function CoverageChip({ mapped, expected }: Props) {
  const ratio = expected > 0 ? `${mapped}/${expected}` : mapped > 0 ? `${mapped}` : "0";
  const complete = expected > 0 && mapped >= expected;
  return (
    <span
      className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
        complete
          ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
          : mapped > 0
            ? "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200"
            : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
      }`}
    >
      {ratio}
    </span>
  );
}
