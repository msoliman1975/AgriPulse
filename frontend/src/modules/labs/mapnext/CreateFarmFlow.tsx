// Create-farm flow for the Farm Console (/labs/map?create=farm).
//
// Farm creation used to leave the console for the legacy /farms/new form and
// then land on /farms/:id — a page that is no longer in the navigation. This
// keeps the whole thing on the console map with the same grammar as Add block
// / Add pivot: draw (or upload) the boundary, name it, land in the console.
//
// Unlike the rest of the console this view is NOT farm-scoped: a brand-new
// tenant has no farm at all, so it renders with or without a farm in context
// (the context farm, when there is one, is drawn as the starting view).
// See docs/proposals/farm-creation-in-console.md.
import { useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { FeatureCollection, MultiPolygon, Polygon } from "geojson";

import { listCountries } from "@/api/countries";
import { createFarm, getFarm, type FarmCreatePayload } from "@/api/farms";
import { parseAoiFile, pickPolygonalFeatures, singleBoundary, AoiParseError } from "@/lib/aoi";
import {
  ensureValidMultiPolygon,
  geometryAreaM2,
  polygonToMultiPolygon,
  GeometryValidationError,
} from "@/lib/geometry";
import { isApiError } from "@/api/errors";
import { useCapability } from "@/rbac/useCapability";
import { MapCanvas, type DrawProgress } from "../map/MapCanvas";
import type { UnitFeatureProps } from "../map/types";
import { CreateFarmPanel, FarmBoundaryBar, type FarmDraft } from "./createFlows";
import { LAST_FARM_KEY } from "./constants";
import { ghostBtn } from "./ui";

// The console map always wants a units FeatureCollection; a farm being created
// has no units yet. Module-level so the reference stays stable across renders.
const NO_UNITS: FeatureCollection<Polygon, UnitFeatureProps> = {
  type: "FeatureCollection",
  features: [],
};

export function CreateFarmFlow({ contextFarmId }: { contextFarmId?: string }): ReactNode {
  const { t } = useTranslation("farmConsole");
  const { t: tf } = useTranslation("farms");
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const qc = useQueryClient();
  const [search, setSearch] = useSearchParams();
  const canCreate = useCapability("farm.create");

  const [drawing, setDrawing] = useState(false);
  const [drawProgress, setDrawProgress] = useState<DrawProgress | null>(null);
  // The captured boundary, from either capture mode. `source` drives the map:
  // a drawn polygon is already painted by the draw control, an uploaded one
  // has to be handed to the map as an AOI so the operator can see it.
  const [boundary, setBoundary] = useState<{
    geometry: Polygon | MultiPolygon;
    source: "draw" | "upload";
  } | null>(null);
  const [parsing, setParsing] = useState(false);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Bumped on every upload so the map refits to the newly loaded boundary.
  const uploadSeq = useRef(0);

  // Context farm (when entering from a farm) — gives the map a sensible
  // starting view instead of the world. Same query key as the settings
  // drawer's farm tab, so this is usually already cached.
  const contextFarmQ = useQuery({
    queryKey: ["labs/mapnext/farm", contextFarmId],
    queryFn: () => getFarm(contextFarmId as string),
    enabled: Boolean(contextFarmId),
    staleTime: 30_000,
  });
  const countriesQ = useQuery({
    queryKey: ["countries", "list"],
    queryFn: () => listCountries(),
    staleTime: 5 * 60_000,
  });

  const areaM2 = useMemo(() => (boundary ? geometryAreaM2(boundary.geometry) : 0), [boundary]);

  // What the map shows as the AOI layer: the uploaded boundary once we have
  // one (so it is visible and gets fitted), else the context farm for
  // orientation. A drawn boundary is left to the draw control.
  const aoi: MultiPolygon | null = useMemo(() => {
    if (boundary?.source === "upload") {
      return boundary.geometry.type === "Polygon"
        ? polygonToMultiPolygon(boundary.geometry)
        : boundary.geometry;
    }
    return contextFarmQ.data?.boundary ?? null;
  }, [boundary, contextFarmQ.data]);

  // Land back on the console this flow was opened from. Two consoles render
  // this component — /labs/map-v2, which the nav points at, and the delisted
  // /labs/map — so a hard-coded path would drop a v2 user into the other one
  // right after they created their farm.
  const consoleBase = pathname.startsWith("/labs/map-v2") ? "/labs/map-v2" : "/labs/map";

  const exit = (): void => {
    const next = new URLSearchParams(search);
    next.delete("create");
    setSearch(next, { replace: true });
  };

  const startDraw = (): void => {
    setBoundary(null);
    setCaptureError(null);
    setSubmitError(null);
    setDrawing(true);
  };

  const handleFile = async (file: File): Promise<void> => {
    setParsing(true);
    setCaptureError(null);
    setSubmitError(null);
    setDrawing(false);
    try {
      const parsed = await parseAoiFile(file);
      const polys = pickPolygonalFeatures(parsed.collection);
      const geometry = singleBoundary(polys);
      if (!geometry) {
        setCaptureError(tf("aoi.empty"));
        return;
      }
      uploadSeq.current += 1;
      setBoundary({ geometry, source: "upload" });
    } catch (err) {
      if (err instanceof AoiParseError) {
        if (err.code === "too_large") setCaptureError(tf("aoi.tooLarge"));
        else if (err.code === "unsupported_extension") setCaptureError(tf("aoi.unsupported"));
        else if (err.code === "empty") setCaptureError(tf("aoi.empty"));
        else setCaptureError(tf("aoi.invalid"));
      } else {
        setCaptureError(tf("aoi.invalid"));
      }
    } finally {
      setParsing(false);
    }
  };

  const createMut = useMutation({
    mutationFn: (payload: FarmCreatePayload) => createFarm(payload),
    onSuccess: (farm) => {
      // Refresh both farm lists (console rail + shell switcher) and remember
      // the new farm so the console lands on it.
      void qc.invalidateQueries({ queryKey: ["labs/mapnext/farmsList"] });
      void qc.invalidateQueries({ queryKey: ["farms", "list", "switcher"] });
      if (typeof window !== "undefined") window.localStorage.setItem(LAST_FARM_KEY, farm.id);
      navigate(`${consoleBase}/${farm.id}`, { replace: true });
    },
    onError: (err) => {
      setSubmitError(
        isApiError(err) ? (err.problem.detail ?? err.problem.title) : t("create.createFailed"),
      );
    },
  });

  const submit = (draft: FarmDraft): void => {
    if (!boundary) return;
    setSubmitError(null);
    // Same geometry contract as the legacy farm form: a valid, non
    // self-intersecting MultiPolygon inside the supported bbox.
    let validated: MultiPolygon;
    try {
      validated = ensureValidMultiPolygon(
        boundary.geometry.type === "Polygon"
          ? polygonToMultiPolygon(boundary.geometry)
          : boundary.geometry,
      );
    } catch (err) {
      const code = err instanceof GeometryValidationError ? err.code : null;
      if (code === "self_intersect") setSubmitError(tf("form.errors.boundarySelfIntersect"));
      else setSubmitError(tf("form.errors.boundaryInvalid"));
      return;
    }
    createMut.mutate({ ...draft, boundary: validated });
  };

  if (!canCreate) {
    return (
      <div className="grid h-full place-items-center gap-3 p-6 text-center text-sm text-ap-muted">
        <p>{t("create.noPermission")}</p>
        <button type="button" onClick={exit} className={ghostBtn}>
          {t("manage.cancel")}
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="relative z-30 flex h-12 flex-none items-center gap-2.5 border-b border-ap-line bg-ap-panel px-3.5">
        <span className="text-base">🌾</span>
        {/* The console is a bleed canvas with no <PageHeader>, so this bar
            title is the route's only level-1 heading — it stays an <h1>. */}
        <h1 className="text-sm font-bold text-ap-ink">{t("create.farmTitle")}</h1>
        <span className="text-xs text-ap-muted">
          {boundary ? t("create.stepDetails") : t("create.stepBoundary")}
        </span>
        <div className="flex-1" />
        <button type="button" onClick={exit} className={ghostBtn}>
          {t("manage.cancel")}
        </button>
      </header>

      <main className="relative min-w-0 flex-1">
        <MapCanvas
          geojson={NO_UNITS}
          farmBoundary={aoi}
          selectedId={null}
          onSelect={() => {
            /* nothing to select while creating */
          }}
          // Refit when the AOI we show changes: the context farm on entry,
          // then each uploaded boundary. A drawn polygon must NOT refit —
          // that would yank the map while the operator is still working.
          fitBoundsKey={
            boundary?.source === "upload"
              ? `upload:${uploadSeq.current}`
              : (contextFarmId ?? "no-farm")
          }
          showAoi
          showBlocks={false}
          drawEnabled={drawing}
          drawTarget="farm_aoi"
          onDrawProgress={setDrawProgress}
          onPolygonDrawn={(poly, drawnAreaM2, target) => {
            if (target !== "farm_aoi") return;
            setDrawProgress(null);
            setDrawing(false);
            setBoundary({ geometry: poly, source: "draw" });
            // areaM2 is recomputed from the geometry; drawnAreaM2 is the
            // draw control's own estimate and only used for the live readout.
            void drawnAreaM2;
          }}
        />

        {boundary ? (
          <CreateFarmPanel
            areaM2={areaM2}
            countries={countriesQ.data ?? []}
            submitting={createMut.isPending}
            error={submitError}
            onSubmit={submit}
            onBack={startDraw}
            onCancel={exit}
          />
        ) : (
          <FarmBoundaryBar
            drawing={drawing}
            vertices={drawProgress?.vertices}
            areaM2={drawProgress?.areaM2}
            parsing={parsing}
            error={captureError}
            onStartDraw={startDraw}
            onFile={(f) => void handleFile(f)}
            onCancel={exit}
          />
        )}
      </main>
    </div>
  );
}
