import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import type { Geometry } from "geojson";

import { SatelliteBasemapControl, satelliteStyle, useFarmLatestPhoto } from "@/lib/basemap";
import { centerOfBbox } from "@/lib/geometry";

interface Props {
  geometry: Geometry | null | undefined;
  className?: string;
  /** The farm shown, for its latest satellite photo. */
  farmId?: string | null;
}

/** Read-only preview map that renders a single geometry. */
export function MapPreview({ geometry, className, farmId }: Props): JSX.Element {
  const ref = useRef<HTMLDivElement | null>(null);
  const [map, setMap] = useState<maplibregl.Map | null>(null);
  const photo = useFarmLatestPhoto(farmId);

  useEffect(() => {
    if (!ref.current || !geometry) return;
    const center = centerOfBbox(geometry);
    const map = new maplibregl.Map({
      container: ref.current,
      style: satelliteStyle(),
      center,
      zoom: 12,
      interactive: false,
    });
    map.on("load", () => {
      map.addSource("aoi", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry },
      });
      map.addLayer({
        id: "aoi-fill",
        type: "fill",
        source: "aoi",
        paint: { "fill-color": "#16a34a", "fill-opacity": 0.25 },
      });
      map.addLayer({
        id: "aoi-line",
        type: "line",
        source: "aoi",
        paint: { "line-color": "#16a34a", "line-width": 2 },
      });
    });
    setMap(map);
    return () => {
      setMap(null);
      map.remove();
    };
  }, [geometry]);

  return (
    <div className="relative">
      <div
        ref={ref}
        data-testid="map-preview"
        className={className ?? "h-64 w-full overflow-hidden rounded-md border border-ap-line"}
      />
      <SatelliteBasemapControl map={map} photo={photo} />
    </div>
  );
}
