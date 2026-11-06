export type FixturePhase = "live" | "pre";

export const DEFAULT_FIXTURE_PHASE: FixturePhase = "live";

export function parseFixturePhase(raw: string | null | undefined): FixturePhase {
  return raw === "pre" ? "pre" : "live";
}

type FixturePhaseTabsProps = {
  phase: FixturePhase;
  onChange: (phase: FixturePhase) => void;
};

export function FixturePhaseTabs({ phase, onChange }: FixturePhaseTabsProps) {
  const tabs: { id: FixturePhase; label: string }[] = [
    { id: "live", label: "Live" },
    { id: "pre", label: "Pre" },
  ];
  return (
    <div className="mb-2 flex gap-1 border-b border-slate-200 dark:border-slate-700">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          className={`px-3 py-1.5 text-xs ${
            phase === tab.id
              ? "border-b-2 border-brand-600 font-medium text-brand-800 dark:text-brand-200"
              : "text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
          }`}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
