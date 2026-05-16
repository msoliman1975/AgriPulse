// FarmDefaultsTab — Subscriptions template authoring + Apply flow.
//
// PR-2 of the farm-block config rollout. Embedded as a section in
// FarmDrawer; gated server-side by FARM_CONFIG_TEMPLATE_ENABLED (a 404
// is treated as "feature off" and renders an inline notice).

import { useEffect, useState } from "react";

import {
  ApplyPreview,
  applySubscriptions,
  getSubscriptionsTemplate,
  ImageryTemplateRow,
  previewApplySubscriptions,
  replaceSubscriptionsTemplate,
  SubscriptionsTemplate,
  WeatherTemplateRow,
} from "@/api/farmConfig";
import { getConfig, ImageryConfigEntry } from "@/api/config";

interface Props {
  farmId: string;
}

export function FarmDefaultsTab({ farmId }: Props) {
  const [template, setTemplate] = useState<SubscriptionsTemplate | null>(null);
  const [products, setProducts] = useState<ImageryConfigEntry[]>([]);
  const [featureOff, setFeatureOff] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ApplyPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyMessage, setApplyMessage] = useState<string | null>(null);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [t, c] = await Promise.all([
          getSubscriptionsTemplate(farmId),
          getConfig(),
        ]);
        if (cancelled) return;
        setTemplate(t);
        setProducts(c.products);
      } catch (err) {
        if (cancelled) return;
        const status = (err as { response?: { status?: number } })?.response
          ?.status;
        if (status === 404) {
          setFeatureOff(true);
        } else {
          setLoadError((err as Error).message ?? "Failed to load template.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [farmId]);

  if (featureOff) {
    return (
      <p className="text-[11px] text-slate-500">
        Farm subscription templates are not enabled in this environment. Ask
        the platform admin to flip the <code>farm_config_template_enabled</code>
        flag.
      </p>
    );
  }
  if (loadError) {
    return <p className="text-[11px] text-rose-700">{loadError}</p>;
  }
  if (!template) {
    return <p className="text-[11px] text-slate-500">Loading template…</p>;
  }

  const productById = new Map(products.map((p) => [p.product_id, p]));

  const addImageryRow = () => {
    const remaining = products.filter(
      (p) => !template.imagery.some((r) => r.product_id === p.product_id),
    );
    if (remaining.length === 0) return;
    setTemplate({
      ...template,
      imagery: [
        ...template.imagery,
        {
          product_id: remaining[0].product_id,
          cadence_hours: 24,
          cloud_cover_max_pct: 30,
          is_active: true,
        },
      ],
    });
  };

  const updateImageryRow = (i: number, patch: Partial<ImageryTemplateRow>) => {
    setTemplate({
      ...template,
      imagery: template.imagery.map((r, idx) => (idx === i ? { ...r, ...patch } : r)),
    });
  };

  const removeImageryRow = (i: number) => {
    setTemplate({
      ...template,
      imagery: template.imagery.filter((_, idx) => idx !== i),
    });
  };

  const addWeatherRow = () => {
    setTemplate({
      ...template,
      weather: [
        ...template.weather,
        { provider_code: "", cadence_hours: 6, is_active: true },
      ],
    });
  };

  const updateWeatherRow = (i: number, patch: Partial<WeatherTemplateRow>) => {
    setTemplate({
      ...template,
      weather: template.weather.map((r, idx) => (idx === i ? { ...r, ...patch } : r)),
    });
  };

  const removeWeatherRow = (i: number) => {
    setTemplate({
      ...template,
      weather: template.weather.filter((_, idx) => idx !== i),
    });
  };

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await replaceSubscriptionsTemplate(farmId, template);
      setTemplate(updated);
      setPreview(null);
    } catch (err) {
      setSaveError((err as Error).message ?? "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const openPreview = async () => {
    setPreviewLoading(true);
    setApplyMessage(null);
    try {
      const p = await previewApplySubscriptions(farmId, null);
      setPreview(p);
      setExcluded(new Set());
    } catch (err) {
      setSaveError((err as Error).message ?? "Preview failed.");
    } finally {
      setPreviewLoading(false);
    }
  };

  const toggleExcluded = (blockId: string) => {
    const next = new Set(excluded);
    if (next.has(blockId)) {
      next.delete(blockId);
    } else {
      next.add(blockId);
    }
    setExcluded(next);
  };

  const apply = async () => {
    if (!preview) return;
    setApplying(true);
    setApplyMessage(null);
    try {
      const allIds = new Set<string>();
      for (const d of preview.imagery) allIds.add(d.block_id);
      for (const d of preview.weather) allIds.add(d.block_id);
      const blockIds = [...allIds].filter((id) => !excluded.has(id));
      const counts = await applySubscriptions(farmId, blockIds);
      setApplyMessage(
        `Applied to ${counts.blocks_touched} block(s) · ` +
          `imagery +${counts.imagery_added}/${counts.imagery_updated}/-${counts.imagery_deactivated} · ` +
          `weather +${counts.weather_added}/${counts.weather_updated}/-${counts.weather_deactivated}`,
      );
      setPreview(null);
    } catch (err) {
      setApplyMessage((err as Error).message ?? "Apply failed.");
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="space-y-3">
      {/* Imagery template */}
      <div>
        <div className="flex items-center justify-between">
          <h4 className="text-[11px] font-semibold uppercase text-slate-600">
            Imagery products
          </h4>
          <button
            type="button"
            onClick={addImageryRow}
            disabled={products.length === template.imagery.length}
            className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] hover:bg-slate-50 disabled:opacity-50"
          >
            + Add product
          </button>
        </div>
        {template.imagery.length === 0 ? (
          <p className="mt-1 text-[11px] text-slate-500">
            No imagery products in the template yet.
          </p>
        ) : (
          <ul className="mt-1 divide-y divide-slate-100">
            {template.imagery.map((row, i) => {
              const meta = productById.get(row.product_id);
              return (
                <li key={i} className="flex flex-wrap items-center gap-2 py-1.5 text-[11px]">
                  <select
                    value={row.product_id}
                    onChange={(e) => updateImageryRow(i, { product_id: e.target.value })}
                    className="rounded border border-slate-300 px-1 py-0.5"
                  >
                    {products.map((p) => (
                      <option key={p.product_id} value={p.product_id}>
                        {p.product_name}
                      </option>
                    ))}
                  </select>
                  <label className="flex items-center gap-1">
                    cadence
                    <input
                      type="number"
                      min={1}
                      value={row.cadence_hours}
                      onChange={(e) =>
                        updateImageryRow(i, {
                          cadence_hours: Math.max(1, Number(e.target.value)),
                        })
                      }
                      className="w-14 rounded border border-slate-300 px-1 py-0.5"
                    />
                    h
                  </label>
                  <label className="flex items-center gap-1">
                    cloud ≤
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={row.cloud_cover_max_pct ?? ""}
                      onChange={(e) =>
                        updateImageryRow(i, {
                          cloud_cover_max_pct:
                            e.target.value === "" ? null : Number(e.target.value),
                        })
                      }
                      className="w-14 rounded border border-slate-300 px-1 py-0.5"
                    />
                    %
                  </label>
                  <label className="flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={row.is_active}
                      onChange={(e) =>
                        updateImageryRow(i, { is_active: e.target.checked })
                      }
                    />
                    active
                  </label>
                  <button
                    type="button"
                    onClick={() => removeImageryRow(i)}
                    className="ms-auto rounded border border-slate-300 px-1.5 py-0.5 text-[10px] text-rose-700 hover:bg-rose-50"
                  >
                    Remove
                  </button>
                  {!meta ? (
                    <span className="basis-full text-[10px] text-amber-700">
                      Product not in catalog.
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* Weather template */}
      <div>
        <div className="flex items-center justify-between">
          <h4 className="text-[11px] font-semibold uppercase text-slate-600">
            Weather providers
          </h4>
          <button
            type="button"
            onClick={addWeatherRow}
            className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] hover:bg-slate-50"
          >
            + Add provider
          </button>
        </div>
        {template.weather.length === 0 ? (
          <p className="mt-1 text-[11px] text-slate-500">
            No weather providers in the template yet.
          </p>
        ) : (
          <ul className="mt-1 divide-y divide-slate-100">
            {template.weather.map((row, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2 py-1.5 text-[11px]">
                <input
                  type="text"
                  value={row.provider_code}
                  placeholder="provider code"
                  onChange={(e) =>
                    updateWeatherRow(i, { provider_code: e.target.value })
                  }
                  className="w-32 rounded border border-slate-300 px-1 py-0.5"
                />
                <label className="flex items-center gap-1">
                  cadence
                  <input
                    type="number"
                    min={1}
                    value={row.cadence_hours}
                    onChange={(e) =>
                      updateWeatherRow(i, {
                        cadence_hours: Math.max(1, Number(e.target.value)),
                      })
                    }
                    className="w-14 rounded border border-slate-300 px-1 py-0.5"
                  />
                  h
                </label>
                <label className="flex items-center gap-1">
                  <input
                    type="checkbox"
                    checked={row.is_active}
                    onChange={(e) =>
                      updateWeatherRow(i, { is_active: e.target.checked })
                    }
                  />
                  active
                </label>
                <button
                  type="button"
                  onClick={() => removeWeatherRow(i)}
                  className="ms-auto rounded border border-slate-300 px-1.5 py-0.5 text-[10px] text-rose-700 hover:bg-rose-50"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Save + Apply */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="rounded border border-slate-300 px-2 py-1 text-[11px] hover:bg-slate-50 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save template"}
        </button>
        <button
          type="button"
          onClick={openPreview}
          disabled={previewLoading}
          className="rounded border border-emerald-400 bg-emerald-50 px-2 py-1 text-[11px] text-emerald-800 hover:bg-emerald-100 disabled:opacity-50"
        >
          {previewLoading ? "Preview…" : "Apply to blocks…"}
        </button>
        {saveError ? (
          <span className="text-[11px] text-rose-700">{saveError}</span>
        ) : null}
        {applyMessage ? (
          <span className="text-[11px] text-emerald-700">{applyMessage}</span>
        ) : null}
      </div>

      {/* Preview / Apply confirm */}
      {preview ? (
        <ApplyPreviewPanel
          preview={preview}
          excluded={excluded}
          onToggle={toggleExcluded}
          onApply={apply}
          onCancel={() => setPreview(null)}
          applying={applying}
        />
      ) : null}
    </div>
  );
}

function ApplyPreviewPanel({
  preview,
  excluded,
  onToggle,
  onApply,
  onCancel,
  applying,
}: {
  preview: ApplyPreview;
  excluded: Set<string>;
  onToggle: (id: string) => void;
  onApply: () => void;
  onCancel: () => void;
  applying: boolean;
}) {
  const imageryById = new Map(preview.imagery.map((d) => [d.block_id, d]));
  const weatherById = new Map(preview.weather.map((d) => [d.block_id, d]));
  const allIds = new Set<string>();
  for (const d of preview.imagery) allIds.add(d.block_id);
  for (const d of preview.weather) allIds.add(d.block_id);

  return (
    <div className="rounded border border-amber-300 bg-amber-50 p-2">
      <p className="text-[11px] font-semibold text-amber-900">
        Apply preview — {preview.matched_blocks} of {preview.total_blocks} blocks
        already match.
      </p>
      <ul className="mt-2 max-h-56 divide-y divide-amber-200 overflow-y-auto text-[11px]">
        {[...allIds].map((blockId) => {
          const i = imageryById.get(blockId);
          const w = weatherById.get(blockId);
          const matches = (i?.matches ?? true) && (w?.matches ?? true);
          const counts = [
            (i?.will_add.length ?? 0) + (w?.will_add.length ?? 0),
            (i?.will_update.length ?? 0) + (w?.will_update.length ?? 0),
            (i?.will_deactivate.length ?? 0) + (w?.will_deactivate.length ?? 0),
          ];
          return (
            <li key={blockId} className="flex items-center gap-2 py-1.5">
              <input
                type="checkbox"
                checked={!excluded.has(blockId)}
                onChange={() => onToggle(blockId)}
                disabled={matches}
              />
              <span className="flex-1 truncate font-mono text-[10px] text-slate-700">
                {blockId.slice(0, 8)}…
              </span>
              {matches ? (
                <span className="text-[10px] text-emerald-700">matches</span>
              ) : (
                <span className="text-[10px] text-amber-800">
                  +{counts[0]} / ~{counts[1]} / -{counts[2]}
                </span>
              )}
            </li>
          );
        })}
      </ul>
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          onClick={onApply}
          disabled={applying}
          className="rounded border border-emerald-500 bg-emerald-100 px-2 py-1 text-[11px] text-emerald-900 hover:bg-emerald-200 disabled:opacity-50"
        >
          {applying ? "Applying…" : "Confirm apply"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={applying}
          className="rounded border border-slate-300 px-2 py-1 text-[11px] hover:bg-slate-50 disabled:opacity-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
