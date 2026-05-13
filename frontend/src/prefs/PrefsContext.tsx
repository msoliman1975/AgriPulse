/* eslint-disable react-refresh/only-export-components */
// This file deliberately co-locates the context value, the provider
// component, and the consumer hook. Splitting them across files would
// hurt readability for a small preference store.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type AreaUnit = "feddan" | "acre" | "hectare";

export const SUPPORTED_AREA_UNITS: readonly AreaUnit[] = ["feddan", "acre", "hectare"];

export type WeatherUnitSystem = "metric" | "imperial";

export const SUPPORTED_WEATHER_UNIT_SYSTEMS: readonly WeatherUnitSystem[] = [
  "metric",
  "imperial",
];

interface PrefsState {
  unit: AreaUnit;
  setUnit: (unit: AreaUnit) => void;
  weatherUnit: WeatherUnitSystem;
  setWeatherUnit: (unit: WeatherUnitSystem) => void;
}

const AREA_STORAGE_KEY = "agripulse.prefs.unit";
const WEATHER_STORAGE_KEY = "agripulse.prefs.weatherUnit";

function readStoredUnit(): AreaUnit {
  if (typeof window === "undefined") return "feddan";
  const stored = window.localStorage.getItem(AREA_STORAGE_KEY);
  return SUPPORTED_AREA_UNITS.includes(stored as AreaUnit) ? (stored as AreaUnit) : "feddan";
}

function readStoredWeatherUnit(): WeatherUnitSystem {
  if (typeof window === "undefined") return "metric";
  const stored = window.localStorage.getItem(WEATHER_STORAGE_KEY);
  return SUPPORTED_WEATHER_UNIT_SYSTEMS.includes(stored as WeatherUnitSystem)
    ? (stored as WeatherUnitSystem)
    : "metric";
}

const PrefsContext = createContext<PrefsState | null>(null);

interface Props {
  children: ReactNode;
}

export function PrefsProvider({ children }: Props): ReactNode {
  const [unit, setUnitState] = useState<AreaUnit>(readStoredUnit);
  const [weatherUnit, setWeatherUnitState] = useState<WeatherUnitSystem>(readStoredWeatherUnit);

  useEffect(() => {
    window.localStorage.setItem(AREA_STORAGE_KEY, unit);
  }, [unit]);

  useEffect(() => {
    window.localStorage.setItem(WEATHER_STORAGE_KEY, weatherUnit);
  }, [weatherUnit]);

  const setUnit = useCallback((next: AreaUnit) => setUnitState(next), []);
  const setWeatherUnit = useCallback((next: WeatherUnitSystem) => setWeatherUnitState(next), []);

  const value = useMemo(
    () => ({ unit, setUnit, weatherUnit, setWeatherUnit }),
    [unit, setUnit, weatherUnit, setWeatherUnit],
  );
  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs(): PrefsState {
  const value = useContext(PrefsContext);
  if (!value) throw new Error("usePrefs must be used inside <PrefsProvider>");
  return value;
}
