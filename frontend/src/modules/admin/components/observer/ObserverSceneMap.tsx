import maplibregl from "maplibre-gl";
import { useEffect, useRef, type ReactNode } from "react";
import type { Feature, FeatureCollection, Geometry, Polygon } from "geojson";

import type { CellFeature, PixelFeature } from "@/api/observer";
import { centerOfBbox } from "@/lib/geometry";

/**
 * The scene's ground truth, drawn: satellite base, the block outlined, every
 * pixel as its real footprint coloured by value, and the grid cells over the
 * top in a second colour.
 *
 * Same Esri World Imagery base as the farm-management map, so an operator
 * moving between the two is looking at the same ground.
 *
 * Pixels are drawn as actual polygons rather than a raster overlay because
 * the point of this view is that a pixel is a *thing* with an extent and a
 * value — you can click one and be told what it contributed. A rendered
 * raster hides exactly that.
 */

// Esri has no imagery above z19 over Egypt; asking for more buys blank tiles.
const SATELLITE_MAXZOOM = 19;

function satelliteTileSize(): number {
  const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
  return dpr >= 1.5 ? 128 : 256;
}

function buildStyle(): maplibregl.StyleSpecification {
  return {
    version: 8,
    sources: {
      satellite: {
        type: "raster",
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: satelliteTileSize(),
        attribution:
          "Tiles © Esri — Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, " +
          "Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
        maxzoom: SATELLITE_MAXZOOM,
      },
    },
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#b5ad8e" } },
      {
        id: "satellite",
        type: "raster",
        source: "satellite",
        paint: { "raster-opacity": 1, "raster-resampling": "linear" },
      },
    ],
  };
}

interface Props {
  boundary: Geometry;
  pixels: PixelFeature[];
  cells: CellFeature[];
  selectedCellId: string | null;
  onSelectCell: (cellId: string | null) => void;
  onPickPixel: (point: { lon: number; lat: number }) => void;
  /** Value range for the pixel ramp; defaults to the index's usual window. */
  rescale: [number, number];
  className?: string;
}

function pixelCollection(pixels: PixelFeature[]): FeatureCollection<Polygon> {
  return {
    type: "FeatureCollection",
    features: pixels.map(
      (p): Feature<Polygon> => ({
        type: "Feature",
        geometry: p.geometry as unknown as Polygon,
        properties: {
          row: p.row,
          col: p.col,
          // MapLibre expressions cannot branch on null, so carry a separate
          // flag and keep `value` numeric.
          value: p.value ?? 0,
          hasValue: p.value === null ? 0 : 1,
          masked: p.masked ? 1 : 0,
        },
      }),
    ),
  };
}

function cellCollection(
  cells: CellFeature[],
  selectedId: string | null,
): FeatureCollection<Polygon> {
  return {
    type: "FeatureCollection",
    features: cells.map(
      (c): Feature<Polygon> => ({
        type: "Feature",
        id: c.cell_id,
        geometry: c.geometry as unknown as Polygon,
        properties: {
          cell_id: c.cell_id,
          label: `R${c.row_idx}C${c.col_idx}`,
          selected: c.cell_id === selectedId ? 1 : 0,
          hasMean: c.mean === null ? 0 : 1,
        },
      }),
    ),
  };
}

export function ObserverSceneMap({
  boundary,
  pixels,
  cells,
  selectedCellId,
  onSelectCell,
  onPickPixel,
  rescale,
  className,
}: Props): ReactNode {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const readyRef = useRef(false);
  // Handlers live in refs so the map is built once and never torn down just
  // because the parent re-rendered with new callback identities.
  const cbRef = useRef({ onSelectCell, onPickPixel });
  cbRef.current = { onSelectCell, onPickPixel };

  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: buildStyle(),
      center: centerOfBbox(boundary),
      zoom: 16,
      maxZoom: 22,
    });
    mapRef.current = map;

    map.on("load", () => {
      map.addSource("pixels", { type: "geojson", data: pixelCollection([]) });
      map.addSource("cells", { type: "geojson", data: cellCollection([], null) });
      map.addSource("aoi", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry: boundary },
      });

      // Pixels: light fill ramped by value, so the field's variation reads at
      // a glance without hiding the satellite underneath.
      map.addLayer({
        id: "pixel-fill",
        type: "fill",
        source: "pixels",
        paint: {
          "fill-color": [
            "case",
            ["==", ["get", "hasValue"], 0],
            "#9ca3af",
            [
              "interpolate",
              ["linear"],
              ["get", "value"],
              rescale[0],
              "#f7f7f2",
              (rescale[0] + rescale[1]) / 2,
              "#9ec78a",
              rescale[1],
              "#2f6b2c",
            ],
          ],
          "fill-opacity": ["case", ["==", ["get", "masked"], 1], 0.35, 0.62],
        },
      });
      map.addLayer({
        id: "pixel-line",
        type: "line",
        source: "pixels",
        paint: { "line-color": "#ffffff", "line-width": 0.4, "line-opacity": 0.55 },
      });

      // Cells: outline only, in a colour that cannot be confused with the
      // pixel ramp, and thicker so the two grids are distinguishable at any
      // zoom. A cell with no stored aggregate is dashed — it exists but the
      // zonal pass wrote nothing for it.
      map.addLayer({
        id: "cell-line",
        type: "line",
        source: "cells",
        paint: {
          "line-color": ["case", ["==", ["get", "selected"], 1], "#f59e0b", "#1f6f9a"],
          "line-width": ["case", ["==", ["get", "selected"], 1], 3.5, 1.6],
          "line-opacity": 0.95,
          "line-dasharray": [
            "case",
            ["==", ["get", "hasMean"], 0],
            ["literal", [2, 2]],
            ["literal", [1, 0]],
          ],
        },
      });
      map.addLayer({
        id: "cell-hit",
        type: "fill",
        source: "cells",
        paint: {
          "fill-color": "#f59e0b",
          "fill-opacity": ["case", ["==", ["get", "selected"], 1], 0.18, 0],
        },
      });

      // Block boundary on top of everything — it is the frame of reference.
      map.addLayer({
        id: "aoi-line",
        type: "line",
        source: "aoi",
        paint: { "line-color": "#f43f5e", "line-width": 2.5 },
      });

      readyRef.current = true;
      map.fire("observer:ready");
    });

    // A click on a cell selects it; a click anywhere else drops the selection
    // and inspects the pixel under the cursor.
    map.on("click", (e) => {
      if (!map.getLayer("cell-hit")) return;
      const hits = map.queryRenderedFeatures(e.point, { layers: ["cell-hit"] });
      if (hits.length > 0) {
        const id = hits[0].properties?.cell_id as string | undefined;
        if (id) {
          cbRef.current.onSelectCell(id);
          return;
        }
      }
      cbRef.current.onPickPixel({ lon: e.lngLat.lng, lat: e.lngLat.lat });
    });
    map.getCanvas().style.cursor = "crosshair";

    return () => {
      readyRef.current = false;
      mapRef.current = null;
      map.remove();
    };
    // Rebuilding on a new boundary is right — that is a different block.
  }, [boundary, rescale]);

  // Data updates never remount the map, so a pan/zoom survives a cell click.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = (): void => {
      // Generic form rather than a cast: eslint strips a redundant-looking
      // `as GeoJSONSource` that tsc actually needs, and the two then fight.
      const px = map.getSource<maplibregl.GeoJSONSource>("pixels");
      const cl = map.getSource<maplibregl.GeoJSONSource>("cells");
      px?.setData(pixelCollection(pixels));
      cl?.setData(cellCollection(cells, selectedCellId));
    };
    if (readyRef.current) apply();
    else map.once("observer:ready", apply);
  }, [pixels, cells, selectedCellId]);

  return <div ref={containerRef} className={className ?? "h-[28rem] w-full rounded"} />;
}
