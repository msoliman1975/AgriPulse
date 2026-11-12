import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Map as MapLibreMap } from "maplibre-gl";

import { apiClient } from "@/api/client";

import { CAPTURE_DATE_MIN_ZOOM, esriCaptureDateUrl, parseEsriCaptureDate } from "./esri";

/** What a map needs to draw the latest photo and say when it was taken. */
export interface LatestPhoto {
  scene_datetime: string;
  tile_url: string;
  /** `[west, south, east, north]` of the farm; absent from older apis. */
  bounds?: [number, number, number, number] | null;
}

interface LatestPhotoResponse {
  photo: LatestPhoto | null;
}

// A new pass lands every few days; an hour of staleness costs nothing.
const PHOTO_STALE_MS = 60 * 60 * 1000;

async function fetchPhoto(path: string): Promise<LatestPhoto | null> {
  try {
    const { data } = await apiClient.get<LatestPhotoResponse>(path);
    return data.photo ?? null;
  } catch {
    // The photo is decoration over a map that works without it. An api that
    // predates the route, or a role without imagery access, gets the base.
    return null;
  }
}

/** The newest clear Sentinel-2 photo of a farm, for staff maps. */
export function useFarmLatestPhoto(farmId: string | null | undefined): LatestPhoto | null {
  const q = useQuery({
    queryKey: ["basemap", "farm-latest-photo", farmId],
    queryFn: () => fetchPhoto(`/v1/farms/${farmId}/latest-photo`),
    enabled: Boolean(farmId),
    staleTime: PHOTO_STALE_MS,
  });
  return q.data ?? null;
}

/** The same photo for an investor, through the investor-scoped route. */
export function useHoldingLatestPhoto(holdingId: string | null | undefined): LatestPhoto | null {
  const q = useQuery({
    queryKey: ["basemap", "holding-latest-photo", holdingId],
    queryFn: () => fetchPhoto(`/v1/investor/holdings/${holdingId}/latest-photo`),
    enabled: Boolean(holdingId),
    staleTime: PHOTO_STALE_MS,
  });
  return q.data ?? null;
}

// One answer per capture area is plenty; panning inside a farm repeats it.
const captureDateCache = new Map<string, string | null>();

/**
 * When the satellite base under the middle of the view was captured, as
 * `YYYY-MM-DD`, re-read after each pan or zoom. Null while zoomed out too far
 * for one date to mean anything, or when the service does not answer.
 */
export function useBaseCaptureDate(map: MapLibreMap | null): string | null {
  const [date, setDate] = useState<string | null>(null);
  useEffect(() => {
    if (!map) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let aborter: AbortController | undefined;
    const read = (): void => {
      if (map.getZoom() < CAPTURE_DATE_MIN_ZOOM) {
        setDate(null);
        return;
      }
      const c = map.getCenter();
      // ~100 m cells: close enough that one answer covers the farm.
      const key = `${c.lng.toFixed(3)},${c.lat.toFixed(3)}`;
      const hit = captureDateCache.get(key);
      if (hit !== undefined) {
        setDate(hit);
        return;
      }
      const b = map.getBounds();
      const canvas = map.getCanvas();
      aborter?.abort();
      aborter = new AbortController();
      fetch(
        esriCaptureDateUrl({
          center: [c.lng, c.lat],
          bounds: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()],
          size: [canvas.clientWidth || 800, canvas.clientHeight || 600],
        }),
        { signal: aborter.signal },
      )
        .then((r) => (r.ok ? r.json() : null))
        .then((body: unknown) => {
          const found = parseEsriCaptureDate(body);
          captureDateCache.set(key, found);
          setDate(found);
        })
        .catch(() => {
          /* aborted or offline: keep the last answer */
        });
    };
    const schedule = (): void => {
      clearTimeout(timer);
      timer = setTimeout(read, 400);
    };
    map.on("moveend", schedule);
    if (map.loaded()) schedule();
    else map.once("load", schedule);
    return () => {
      clearTimeout(timer);
      aborter?.abort();
      map.off("moveend", schedule);
      map.off("load", schedule);
    };
  }, [map]);
  return date;
}
