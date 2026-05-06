import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { Geometry } from "geojson";

import { isApiError } from "@/api/errors";
import { listScenes, triggerRefresh, type IngestionJob } from "@/api/imagery";
import { useOptionalConfig } from "@/config/ConfigContext";
import { useCapability } from "@/rbac/useCapability";
import { Legend } from "./Legend";
import { NDVIMap } from "./NDVIMap";
import { buildTileUrlTemplate, indexAssetKey, visualizationDefaults } from "./tileUrl";

interface Props {
  blockId: string;
  farmId: string;
  /** AOI polygon for the underlying map. */
  geometry: Geometry | null | undefined;
  /** SHA-256 of the block's UTM polygon — drives asset-key construction. */
  aoiHash: string | undefined;
}

/**
 * Imagery card for `BlockDetailPage`. Lists ingested scenes, lets the
 * user pick one, renders the NDVI overlay on a deck.gl tile layer over
 * the existing MapLibre base, and exposes a Refresh button gated by
 * `imagery.refresh`.
 */
export function ImageryPanel({ blockId, farmId, geometry, aoiHash }: Props): JSX.Element {
  const { t } = useTranslation("imagery");
  const { config, loading: configLoading, error: configError } = useOptionalConfig();
  const canRefresh = useCapability("imagery.refresh", { farmId });

  const [scenes, setScenes] = useState<IngestionJob[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);

  // Load scenes on mount and after a refresh fires.
  const loadScenes = async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const page = await listScenes(blockId, { limit: 50 });
      // Only `succeeded` scenes are renderable as imagery.
      const ready = page.items.filter((s) => s.status === "succeeded");
      setScenes(ready);
      setSelectedJobId((curr) => curr ?? ready[0]?.id ?? null);
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadScenes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blockId]);

  const selected = useMemo<IngestionJob | null>(
    () => scenes.find((s) => s.id === selectedJobId) ?? null,
    [scenes, selectedJobId],
  );

  const tileUrlTemplate = useMemo<string | null>(() => {
    if (config === null) return null;
    if (selected === null || aoiHash === undefined) return null;
    if (selected.stac_item_id === null) return null;
    // stac_item_id format: provider/product/scene/aoi (PR-B/C). Parse
    // it for provider + product so the URL is independent of /api/v1/config
    // ordering. We still validate the prefix to fail closed.
    const [providerCode, productCode, sceneId] = selected.stac_item_id.split("/");
    if (!providerCode || !productCode || !sceneId) return null;
    const indexCode = "ndvi" as const;
    const defaults = visualizationDefaults(indexCode);
    return buildTileUrlTemplate({
      tileServerBaseUrl: config.tile_server_base_url,
      s3Bucket: config.s3_bucket,
      assetKey: indexAssetKey({
        providerCode,
        productCode,
        sceneId,
        aoiHash,
        indexCode,
      }),
      rescaleMin: defaults.rescaleMin,
      rescaleMax: defaults.rescaleMax,
      colormap: defaults.colormap,
    });
  }, [selected, aoiHash, config]);

  const handleRefresh = async (): Promise<void> => {
    setRefreshBusy(true);
    setRefreshMessage(null);
    try {
      const resp = await triggerRefresh(blockId);
      const queued = resp.queued_subscription_ids.length;
      setRefreshMessage(
        queued === 0 ? t("refresh.noActive") : t("refresh.queued", { count: queued }),
      );
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setRefreshBusy(false);
    }
  };

  const dateFmt = useMemo(() => new Intl.DateTimeFormat("en-US", { dateStyle: "medium" }), []);

  // Config still loading or failed — render the shell so the rest of
  // the page (the map vector AOI, etc.) doesn't disappear behind a
  // thrown error from useConfig.
  if (config === null) {
    return (
      <section className="card space-y-3" aria-label={t("panel.heading")}>
        <h2 className="text-lg font-semibold text-slate-800">{t("panel.heading")}</h2>
        {configError ? (
          <p role="alert" className="text-sm text-red-700">
            {t("panel.error", { message: configError })}
          </p>
        ) : configLoading ? (
          <p role="status">{t("panel.loading")}</p>
        ) : (
          <p className="text-sm text-slate-600">{t("panel.noConfig")}</p>
        )}
      </section>
    );
  }

  return (
    <section className="card space-y-3" aria-label={t("panel.heading")}>
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-800">{t("panel.heading")}</h2>
          <p className="text-sm text-slate-600">{t("panel.description")}</p>
        </div>
        {canRefresh ? (
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() => void handleRefresh()}
            disabled={refreshBusy}
          >
            {refreshBusy ? t("refresh.busy") : t("refresh.button")}
          </button>
        ) : null}
      </header>

      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {t("panel.error", { message: error })}
        </p>
      ) : null}
      {refreshMessage ? (
        <p role="status" className="text-sm text-slate-600">
          {refreshMessage}
        </p>
      ) : null}

      {loading ? (
        <p role="status">{t("panel.loading")}</p>
      ) : scenes.length === 0 ? (
        <p className="text-sm text-slate-600">{t("panel.empty")}</p>
      ) : (
        <>
          <div>
            <label className="label" htmlFor={`scene-picker-${blockId}`}>
              {t("scenePicker.label")}
            </label>
            <select
              id={`scene-picker-${blockId}`}
              className="input"
              value={selectedJobId ?? ""}
              onChange={(e) => setSelectedJobId(e.target.value || null)}
            >
              {scenes.map((s) => (
                <option key={s.id} value={s.id}>
                  {dateFmt.format(new Date(s.scene_datetime))}
                  {s.cloud_cover_pct !== null
                    ? ` · ${t("scenePicker.cloudCover", { value: Number(s.cloud_cover_pct).toFixed(0) })}`
                    : ""}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1fr_220px]">
            <NDVIMap geometry={geometry} tileUrlTemplate={tileUrlTemplate} />
            <Legend min={-0.2} max={0.9} />
          </div>
        </>
      )}
    </section>
  );
}
