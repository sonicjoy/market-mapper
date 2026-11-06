import { cycleTheme, setTheme, useTheme, type ThemeMode } from "../lib/theme";

function ThemeIcon({ mode }: { mode: ThemeMode }) {
  switch (mode) {
    case "light":
      return (
        <svg
          viewBox="0 0 16 16"
          className="h-3.5 w-3.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          aria-hidden
        >
          <circle cx="8" cy="8" r="2.6" fill="currentColor" stroke="none" />
          <path d="M8 1.4v1.5M8 13.1v1.5M1.4 8h1.5M13.1 8h1.5M3.2 3.2l1.1 1.1M11.7 11.7l1.1 1.1M12.8 3.2l-1.1 1.1M4.3 11.7l-1.1 1.1" />
        </svg>
      );
    case "dark":
      return (
        <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden>
          <path
            fill="currentColor"
            d="M12.4 10.2A5.5 5.5 0 0 1 6.2 3.1 6.2 6.2 0 1 0 12.4 10.2z"
          />
        </svg>
      );
    case "auto":
      return (
        <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden>
          <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.4" />
          <path fill="currentColor" d="M8 2a6 6 0 0 1 0 12z" />
        </svg>
      );
    default: {
      const _exhaustive: never = mode;
      return _exhaustive;
    }
  }
}

const LABELS: Record<ThemeMode, string> = {
  auto: "Auto",
  light: "Light",
  dark: "Dark",
};

/** Cycles Auto → Light → Dark. Auto tracks the OS preference. */
export function ThemeToggle() {
  const mode = useTheme();
  const label = LABELS[mode];
  return (
    <button
      type="button"
      className="btn-ghost gap-1 px-2 text-xs"
      title={`Theme: ${label}. Click to cycle Auto / Light / Dark.`}
      aria-label={`Theme ${label}. Click to cycle Auto, Light, Dark.`}
      onClick={() => setTheme(cycleTheme(mode))}
    >
      <ThemeIcon mode={mode} />
      {label}
    </button>
  );
}
