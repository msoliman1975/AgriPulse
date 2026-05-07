import { create } from "zustand";

interface PlanSelectionState {
  laneId: string | null;
  activityId: string | null;
  setLane: (id: string | null) => void;
  setActivity: (id: string | null) => void;
  setBoth: (laneId: string | null, activityId: string | null) => void;
  clear: () => void;
}

/**
 * Plan-view selection. URL is the source of truth (see useUrlSelection);
 * this store is the synchronous mirror so deep components don't all
 * subscribe to URLSearchParams.
 */
export const usePlanSelection = create<PlanSelectionState>((set) => ({
  laneId: null,
  activityId: null,
  setLane: (laneId) => set({ laneId }),
  setActivity: (activityId) => set({ activityId }),
  setBoth: (laneId, activityId) => set({ laneId, activityId }),
  clear: () => set({ laneId: null, activityId: null }),
}));
