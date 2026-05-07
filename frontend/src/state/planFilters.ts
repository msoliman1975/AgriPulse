import { create } from "zustand";

import type { ActivityType } from "@/api/plans";

const DEFAULT_TYPES: readonly ActivityType[] = [
  "planting",
  "fertilizing",
  "spraying",
  "pruning",
  "harvesting",
  "irrigation",
];

interface PlanFiltersState {
  activeTypes: Set<ActivityType>;
  draftsOnly: boolean;
  toggleType: (t: ActivityType) => void;
  setDraftsOnly: (v: boolean) => void;
  reset: () => void;
}

export const usePlanFilters = create<PlanFiltersState>((set) => ({
  activeTypes: new Set<ActivityType>(DEFAULT_TYPES),
  draftsOnly: false,
  toggleType: (t) =>
    set((s) => {
      const next = new Set(s.activeTypes);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return { activeTypes: next };
    }),
  setDraftsOnly: (v) => set({ draftsOnly: v }),
  reset: () =>
    set({
      activeTypes: new Set<ActivityType>(DEFAULT_TYPES),
      draftsOnly: false,
    }),
}));
