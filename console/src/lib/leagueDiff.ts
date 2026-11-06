import type { LeagueDiff } from "../types";

export type LeagueDiffSection = {
  key: keyof LeagueDiff;
  label: string;
  items: string[];
};

export function leagueDiffSectionLabel(key: keyof LeagueDiff): string {
  switch (key) {
    case "enable":
      return "Adding";
    case "disable":
      return "Removing";
    case "change":
      return "Changing";
    case "already":
      return "Already live";
    case "other":
      return "Also";
    default: {
      const _exhaustive: never = key;
      return _exhaustive;
    }
  }
}

const DIFF_KEYS: (keyof LeagueDiff)[] = ["enable", "disable", "change", "already", "other"];

export function leagueDiffSections(diff: LeagueDiff | null | undefined): LeagueDiffSection[] {
  if (!diff) return [];
  return DIFF_KEYS.flatMap((key) => {
    const items = diff[key];
    if (!items.length) return [];
    return [{ key, label: leagueDiffSectionLabel(key), items }];
  });
}
