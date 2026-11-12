import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Map as MapLibreMap } from "maplibre-gl";

import { makeDateLabelFmt } from "@/lib/chartFormat";

import { applyLatestPhoto } from "./latestPhoto";
import { useBaseCaptureDate, type LatestPhoto } from "./useBasemap";

export type BasemapChoice = "latest" | "highres";

// v2: the default flipped from "latest" to "highres". A new key so nobody
// keeps the old default only because the page once wrote it.
const STORAGE_KEY = "agripulse.basemap.v2";

/**
 * The sharp base by default. The latest photo is 10 m per pixel against the
 * base's ~0.5 m: current, but blurred at farm zoom, and laid over the base it
 * reads as an index layer to anyone who switched the index off to see the
 * ground. It is one click away, and its date is shown either way.
 */
function readChoice(): BasemapChoice {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "latest" ? "latest" : "highres";
  } catch {
    return "highres";
  }
}

function writeChoice(choice: BasemapChoice): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    /* private window: the choice lasts for this page only */
  }
}

/** Parse `YYYY-MM-DD` or an ISO instant as a calendar day, not shifted by TZ. */
function dayOf(value: string): Date {
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d, 12));
}

interface Props {
  map: MapLibreMap | null;
  /** The farm's latest clear Sentinel-2 photo, or null when there is none. */
  photo: LatestPhoto | null;
  className?: string;
}

/**
 * Says how old the satellite picture is, and lays our latest photo over it.
 *
 * With a photo: a two-way switch between "Latest" (the newest clear pass over
 * the farm, 10 m, laid over the farm only) and "High-res" (the vendor mosaic
 * alone, sharper but often years old). Either way both dates are on screen.
 * Without one: just the base layer's capture date. Place inside a
 * `position: relative` wrapper around the map.
 */
export function SatelliteBasemapControl({ map, photo, className }: Props): JSX.Element | null {
  const { t, i18n } = useTranslation("imagery");
  const [choice, setChoice] = useState<BasemapChoice>(readChoice);
  const baseDate = useBaseCaptureDate(map);
  const fmt = useMemo(() => makeDateLabelFmt(i18n.language), [i18n.language]);

  const tileUrl = photo?.tile_url ?? null;
  const bounds = photo?.bounds ?? null;
  const boundsKey = bounds?.join(",") ?? "";
  useEffect(() => {
    if (!map) return;
    applyLatestPhoto(map, tileUrl, choice === "latest", bounds);
    // `bounds` is read through its key so a new array of the same box does
    // not re-run this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, tileUrl, choice, boundsKey]);

  if (!photo && !baseDate) return null;

  const pick = (next: BasemapChoice): void => {
    setChoice(next);
    writeChoice(next);
  };
  const photoLabel = photo ? fmt.format(dayOf(photo.scene_datetime)) : null;
  const baseLabel = baseDate ? fmt.format(dayOf(baseDate)) : null;

  return (
    <div
      className={`pointer-events-auto absolute bottom-8 start-2 z-10 max-w-[calc(100%-1rem)] rounded-md bg-ap-panel/90 px-2 py-1.5 text-xs text-ap-ink shadow-card ${className ?? ""}`}
      data-testid="basemap-control"
    >
      {photo ? (
        <div role="radiogroup" aria-label={t("basemap.label")} className="flex gap-1">
          {(["highres", "latest"] as const).map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={choice === option}
              onClick={() => pick(option)}
              className={`rounded px-2 py-0.5 ${
                choice === option ? "bg-ap-primary text-white" : "bg-ap-bg hover:bg-ap-line"
              }`}
            >
              {t(option === "latest" ? "basemap.latest" : "basemap.highres")}
            </button>
          ))}
        </div>
      ) : null}
      <div className="mt-1 space-y-0.5 leading-tight">
        {photo && choice === "latest" ? (
          <>
            <div>{t("basemap.photoDate", { date: photoLabel })}</div>
            {baseLabel ? (
              <div className="text-ap-muted">{t("basemap.aroundDate", { date: baseLabel })}</div>
            ) : null}
          </>
        ) : (
          <>
            {baseLabel ? <div>{t("basemap.baseDate", { date: baseLabel })}</div> : null}
            {photo ? (
              <div className="text-ap-muted">{t("basemap.newerPhoto", { date: photoLabel })}</div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}
