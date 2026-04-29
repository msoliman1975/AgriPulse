/* eslint-disable react-refresh/only-export-components */
// This file deliberately co-locates the context value, the provider
// component, and the consumer hook. Splitting them across files would
// hurt readability for a small preference store.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type AreaUnit = "feddan" | "acre" | "hectare";

export const SUPPORTED_AREA_UNITS: readonly AreaUnit[] = ["feddan", "acre", "hectare"];

interface PrefsState {
  unit: AreaUnit;
  setUnit: (unit: AreaUnit) => void;
}

const STORAGE_KEY = "missionagre.prefs.unit";

function readStoredUnit(): AreaUnit {
  if (typeof window === "undefined") return "feddan";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  return SUPPORTED_AREA_UNITS.includes(stored as AreaUnit) ? (stored as AreaUnit) : "feddan";
}

const PrefsContext = createContext<PrefsState | null>(null);

interface Props {
  children: ReactNode;
}

export function PrefsProvider({ children }: Props): ReactNode {
  const [unit, setUnitState] = useState<AreaUnit>(readStoredUnit);

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, unit);
  }, [unit]);

  const setUnit = useCallback((next: AreaUnit) => setUnitState(next), []);

  const value = useMemo(() => ({ unit, setUnit }), [unit, setUnit]);
  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs(): PrefsState {
  const value = useContext(PrefsContext);
  if (!value) throw new Error("usePrefs must be used inside <PrefsProvider>");
  return value;
}
