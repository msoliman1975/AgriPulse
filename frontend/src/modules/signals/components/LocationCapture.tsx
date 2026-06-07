import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Geopoint, LocationMode } from "../../../api/signals";

const inputCls =
  "w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary";

export interface LocationValue {
  location_mode: LocationMode;
  /** null for `entity` mode, or when the lat/lon pair is incomplete/invalid. */
  location_point: Geopoint | null;
}

export interface LocationCaptureProps {
  onChange: (value: LocationValue) => void;
  /**
   * Selected block. `point_in_entity` is disabled when null because the
   * server-side ST_Within trigger needs a block to validate the point
   * against. Single-shot entry (no block selector) always passes null.
   */
  blockId: string | null;
  /** Bump to reset the control back to `entity` (e.g. after a successful submit). */
  resetKey?: number;
}

const MODES: LocationMode[] = ["entity", "point_in_entity", "free_point"];

function parsePoint(latText: string, lonText: string): Geopoint | null {
  const lat = Number.parseFloat(latText);
  const lon = Number.parseFloat(lonText);
  if (Number.isNaN(lat) || Number.isNaN(lon)) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return { latitude: lat, longitude: lon };
}

/**
 * Capture an observation's location mode + (optionally) a precise point.
 *
 * Emits `{ location_mode, location_point }` on every change. `location_point`
 * is null for `entity` mode or while the lat/lon pair is incomplete/invalid,
 * so the parent can block submit on "mode needs a point but none given".
 */
export function LocationCapture({ onChange, blockId, resetKey }: LocationCaptureProps): ReactNode {
  const { t } = useTranslation("signals");
  const [mode, setMode] = useState<LocationMode>("entity");
  const [latText, setLatText] = useState("");
  const [lonText, setLonText] = useState("");
  const [geoError, setGeoError] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);

  // Keep the latest onChange without making the emit effects depend on it.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const emit = (nextMode: LocationMode, lat: string, lon: string) => {
    onChangeRef.current({
      location_mode: nextMode,
      location_point: nextMode === "entity" ? null : parsePoint(lat, lon),
    });
  };

  // Reset to default when the parent bumps resetKey (post-submit).
  useEffect(() => {
    if (resetKey === undefined) return;
    setMode("entity");
    setLatText("");
    setLonText("");
    setGeoError(null);
    emit("entity", "", "");
     
  }, [resetKey]);

  // If the block is cleared while pinning inside it, fall back to entity.
  useEffect(() => {
    if (blockId === null && mode === "point_in_entity") {
      setMode("entity");
      emit("entity", latText, lonText);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blockId]);

  const pickMode = (next: LocationMode) => {
    if (next === "point_in_entity" && blockId === null) return;
    setMode(next);
    emit(next, latText, lonText);
  };

  const changeLat = (v: string) => {
    setLatText(v);
    emit(mode, v, lonText);
  };
  const changeLon = (v: string) => {
    setLonText(v);
    emit(mode, latText, v);
  };

  const useCurrentLocation = () => {
    setGeoError(null);
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setGeoError(t("log.form.location.geoUnavailable"));
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const lat = pos.coords.latitude.toFixed(6);
        const lon = pos.coords.longitude.toFixed(6);
        setLatText(lat);
        setLonText(lon);
        setLocating(false);
        emit(mode, lat, lon);
      },
      () => {
        setLocating(false);
        setGeoError(t("log.form.location.geoDenied"));
      },
      { enableHighAccuracy: true, timeout: 10_000 },
    );
  };

  const showPoint = mode !== "entity";
  const pointInvalid = showPoint && (latText !== "" || lonText !== "") && parsePoint(latText, lonText) === null;

  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ap-muted">{t("log.form.location.label")}</span>
      <div
        role="radiogroup"
        aria-label={t("log.form.location.label")}
        className="flex overflow-hidden rounded-md border border-ap-line text-xs"
      >
        {MODES.map((m) => {
          const disabled = m === "point_in_entity" && blockId === null;
          const selected = mode === m;
          return (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              title={disabled ? t("log.form.location.needsBlock") : undefined}
              onClick={() => pickMode(m)}
              className={`flex-1 px-2 py-1 font-medium transition ${
                selected ? "bg-ap-primary text-white" : "bg-white text-ap-ink hover:bg-ap-line/40"
              } ${disabled ? "cursor-not-allowed opacity-40" : ""}`}
            >
              {t(`log.form.location.mode.${m}`)}
            </button>
          );
        })}
      </div>

      {showPoint ? (
        <div className="mt-1 flex flex-col gap-1">
          <div className="flex items-end gap-2">
            <label className="flex flex-1 flex-col gap-0.5">
              <span className="text-[11px] text-ap-muted">{t("log.form.location.lat")}</span>
              <input
                type="number"
                step="any"
                inputMode="decimal"
                value={latText}
                onChange={(e) => changeLat(e.target.value)}
                aria-label={t("log.form.location.lat")}
                className={inputCls}
              />
            </label>
            <label className="flex flex-1 flex-col gap-0.5">
              <span className="text-[11px] text-ap-muted">{t("log.form.location.lon")}</span>
              <input
                type="number"
                step="any"
                inputMode="decimal"
                value={lonText}
                onChange={(e) => changeLon(e.target.value)}
                aria-label={t("log.form.location.lon")}
                className={inputCls}
              />
            </label>
            <button
              type="button"
              onClick={useCurrentLocation}
              disabled={locating}
              className="flex-none rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
            >
              {locating ? t("log.form.location.gpsLocating") : t("log.form.location.gpsButton")}
            </button>
          </div>
          {pointInvalid ? (
            <span className="text-[11px] text-ap-crit">{t("log.form.location.invalidLatLon")}</span>
          ) : null}
          {geoError ? <span className="text-[11px] text-ap-crit">{geoError}</span> : null}
        </div>
      ) : null}
    </div>
  );
}
