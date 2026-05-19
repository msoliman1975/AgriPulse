// FarmDefaultsTab — Subscriptions template authoring + Apply flow.
//
// PR-2 of the farm-block config rollout. Embedded as a section in
// FarmDrawer; gated server-side by FARM_CONFIG_TEMPLATE_ENABLED (a 404
// is treated as "feature off" and renders an inline notice).
//
// Two-step model:
// 1. "Save template" persists at FARM level only — no block change.
// 2. "Apply to blocks…" propagates the saved template to selected
//    blocks via a preview/confirm flow. The lock chip prevents blocks
//    from diverging from the saved farm template once locked.

import { useEffect, useState } from "react";

import {
  applyIrrigation,
  applyOrg,
  applySubscriptions,
  getIrrigationTemplate,
  getLocks,
  getOrgTemplate,
  getSubscriptionsTemplate,
  lockCategory,
  previewApplyIrrigation,
  previewApplyOrg,
  previewApplySubscriptions,
  putIrrigationTemplate,
  putOrgTemplate,
  replaceSubscriptionsTemplate,
  unlockCategory,
} from "@/api/farmConfig";
import type {
  ApplyPreview,
  ImageryTemplateRow,
  IrrigationTemplate,
  LockCategory,
  LockState,
  OrgTemplate,
  SimpleApplyPreview,
  SubscriptionsTemplate,
  WeatherTemplateRow,
} from "@/api/farmConfig";
import { getConfig } from "@/api/config";
import type { ImageryConfigEntry } from "@/api/config";
import { listWeatherProviders, type WeatherProvider } from "@/api/weather";
import type { IrrigationSource, IrrigationSystem } from "@/api/blocks";

const IRRIGATION_SYSTEMS: IrrigationSystem[] = [
  "drip",
  "micro_sprinkler",
  "pivot",
  "furrow",
  "flood",
  "surface",
  "none",
];
const IRRIGATION_SOURCES: IrrigationSource[] = ["well", "canal", "nile", "mixed"];

interface Props {
  farmId: string;
}

export function FarmDefaultsTab({ farmId }: Props) {
  const [template, setTemplate] = useState<SubscriptionsTemplate | null>(null);
  const [products, setProducts] = useState<ImageryConfigEntry[]>([]);
  const [weatherProviders, setWeatherProviders] = useState<WeatherProvider[]>([]);
  const [featureOff, setFeatureOff] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ApplyPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [applyMessage, setApplyMessage] = useState<string | null>(null);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());

  // PR-3 additions: lock state + irrigation + org templates.
  const [locks, setLocks] = useState<LockState | null>(null);
  const [irrigation, setIrrigation] = useState<IrrigationTemplate | null>(null);
  const [orgTpl, setOrgTpl] = useState<OrgTemplate | null>(null);

  const reloadLocks = async () => {
    try {
      setLocks(await getLocks(farmId));
    } catch {
      // Ignore — leave previous state.
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [t, c, l, irr, org, wp] = await Promise.all([
          getSubscriptionsTemplate(farmId),
          getConfig(),
          getLocks(farmId),
          getIrrigationTemplate(farmId),
          getOrgTemplate(farmId),
          listWeatherProviders(),
        ]);
        if (cancelled) return;
        setTemplate(t);
        setProducts(c.products);
        setLocks(l);
        setIrrigation(irr);
        setOrgTpl(org);
        setWeatherProviders(wp);
      } catch (err) {
        if (cancelled) return;
        const status = (err as { response?: { status?: number } })?.response?.status;
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
        Farm subscription templates are not enabled in this environment. Ask the platform admin to
        flip the <code>farm_config_template_enabled</code>
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
    // Seed with the first not-already-picked provider, then fall back
    // to the first catalog entry, then empty. Empty would reject on
    // save server-side (provider_code is non-nullable + FK'd) so the
    // empty case is only reachable when the catalog is also empty.
    const remaining = weatherProviders.filter(
      (p) => !template.weather.some((r) => r.provider_code === p.code),
    );
    const seed = remaining[0]?.code ?? weatherProviders[0]?.code ?? "";
    setTemplate({
      ...template,
      weather: [...template.weather, { provider_code: seed, cadence_hours: 6, is_active: true }],
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

  const lockChip = (cat: LockCategory) => (
    <LockChip
      farmId={farmId}
      category={cat}
      locked={locks?.[cat] ?? false}
      onChange={reloadLocks}
    />
  );

  return (
    <div className="space-y-3">
      <p className="rounded bg-slate-50 px-2 py-1 text-[10px] text-slate-600">
        <strong>Save template</strong> persists at farm level only. <strong>Apply to blocks</strong>{" "}
        rolls the saved template to blocks with a preview / opt-out step. Locking after apply
        prevents blocks from diverging.
      </p>

      <div className="grid grid-cols-1 gap-x-6 gap-y-4 lg:grid-cols-3">
        {/* Column 1 — Imagery (subscriptions lock lives here; weather
            shares the same lock category, called out in col 2 below). */}
        <section>
          <div className="flex items-center justify-between">
            <h3 className="text-[12px] font-semibold text-slate-700">Imagery</h3>
            {lockChip("subscriptions")}
          </div>
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
                          onChange={(e) => updateImageryRow(i, { is_active: e.target.checked })}
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
        </section>

        {/* Column 2 — Weather (shares the subscriptions lock with Imagery). */}
        <section>
          <div className="flex items-center justify-between">
            <h3 className="text-[12px] font-semibold text-slate-700">Weather</h3>
            <span className="text-[10px] text-slate-500">(lock shared with Imagery)</span>
          </div>
          <div className="mt-2">
            <div className="flex items-center justify-between">
              <h4 className="text-[11px] font-semibold uppercase text-slate-600">Providers</h4>
              <button
                type="button"
                onClick={addWeatherRow}
                disabled={weatherProviders.length === 0}
                className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] hover:bg-slate-50 disabled:opacity-50"
              >
                + Add provider
              </button>
            </div>
            {weatherProviders.length === 0 ? (
              <p className="mt-1 text-[11px] text-amber-700">
                No active providers in the catalog. Ask platform admin to populate
                <code className="ms-1">public.weather_providers</code>.
              </p>
            ) : template.weather.length === 0 ? (
              <p className="mt-1 text-[11px] text-slate-500">
                No weather providers in the template yet.
              </p>
            ) : (
              <ul className="mt-1 divide-y divide-slate-100">
                {template.weather.map((row, i) => {
                  const inCatalog = weatherProviders.some((p) => p.code === row.provider_code);
                  return (
                    <li key={i} className="flex flex-wrap items-center gap-2 py-1.5 text-[11px]">
                      <select
                        value={row.provider_code}
                        onChange={(e) => updateWeatherRow(i, { provider_code: e.target.value })}
                        className="rounded border border-slate-300 px-1 py-0.5"
                      >
                        {/* Surface a stale provider_code as a one-off option
                            so the editor doesn't silently rewrite it to the
                            first catalog entry. */}
                        {!inCatalog && row.provider_code ? (
                          <option value={row.provider_code}>
                            {row.provider_code} (not in catalog)
                          </option>
                        ) : null}
                        {weatherProviders.map((p) => (
                          <option key={p.code} value={p.code}>
                            {p.name}
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
                          onChange={(e) => updateWeatherRow(i, { is_active: e.target.checked })}
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
                  );
                })}
              </ul>
            )}
          </div>
        </section>

        {/* Column 3 — Irrigation + Org tags */}
        <section className="space-y-3">
          <div>
            <div className="flex items-center justify-between">
              <h3 className="text-[12px] font-semibold text-slate-700">Irrigation</h3>
              {lockChip("irrigation")}
            </div>
            {irrigation && (
              <IrrigationSection farmId={farmId} value={irrigation} onChange={setIrrigation} />
            )}
          </div>
          <div className="border-t border-slate-200 pt-3">
            <div className="flex items-center justify-between">
              <h3 className="text-[12px] font-semibold text-slate-700">Tags</h3>
              {lockChip("org")}
            </div>
            {orgTpl && <OrgSection farmId={farmId} value={orgTpl} onChange={setOrgTpl} />}
          </div>
        </section>
      </div>

      {/* Subscriptions Save + Apply — spans Imagery + Weather since the
          subscriptions template is one bucket carrying both. */}
      <div className="flex flex-wrap items-center gap-2 border-t border-slate-200 pt-3">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="rounded border border-slate-300 px-2 py-1 text-[11px] hover:bg-slate-50 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save subscriptions template"}
        </button>
        <button
          type="button"
          onClick={openPreview}
          disabled={previewLoading}
          className="rounded border border-emerald-400 bg-emerald-50 px-2 py-1 text-[11px] text-emerald-800 hover:bg-emerald-100 disabled:opacity-50"
        >
          {previewLoading ? "Preview…" : "Apply subscriptions to blocks…"}
        </button>
        <span className="text-[10px] text-slate-500">covers Imagery + Weather</span>
        {saveError ? <span className="text-[11px] text-rose-700">{saveError}</span> : null}
        {applyMessage ? <span className="text-[11px] text-emerald-700">{applyMessage}</span> : null}
      </div>

      {/* Subscriptions Apply preview / confirm */}
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

// ---------- Lock chip ------------------------------------------------------

function LockChip({
  farmId,
  category,
  locked,
  onChange,
}: {
  farmId: string;
  category: LockCategory;
  locked: boolean;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState<{ diff: unknown } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggle = async (force: boolean) => {
    setBusy(true);
    setError(null);
    setConflict(null);
    try {
      if (locked) {
        await unlockCategory(farmId, category);
      } else {
        await lockCategory(farmId, category, force);
      }
      onChange();
    } catch (e) {
      const err = e as {
        response?: { status?: number; data?: { diff?: unknown; detail?: string } };
      };
      if (err.response?.status === 409 && err.response.data?.diff) {
        setConflict({ diff: err.response.data.diff });
      } else {
        setError(err.response?.data?.detail ?? "Toggle failed.");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => toggle(false)}
        disabled={busy}
        className={
          "rounded border px-1.5 py-0.5 text-[10px] " +
          (locked
            ? "border-rose-400 bg-rose-50 text-rose-800"
            : "border-emerald-400 bg-emerald-50 text-emerald-800")
        }
        title={locked ? "Locked — click to unlock" : "Unlocked — click to lock"}
      >
        {locked ? "🔒 locked" : "🔓 unlocked"}
      </button>
      {conflict ? (
        <span className="text-[10px] text-amber-800">
          divergent blocks —{" "}
          <button type="button" onClick={() => toggle(true)} disabled={busy} className="underline">
            Lock and overwrite
          </button>
        </span>
      ) : null}
      {error ? <span className="text-[10px] text-rose-700">{error}</span> : null}
    </div>
  );
}

// ---------- Irrigation section --------------------------------------------

function IrrigationSection({
  farmId,
  value,
  onChange,
}: {
  farmId: string;
  value: IrrigationTemplate;
  onChange: (next: IrrigationTemplate) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [preview, setPreview] = useState<SimpleApplyPreview | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const updated = await putIrrigationTemplate(farmId, value);
      onChange(updated);
      setMsg("Template saved.");
    } catch (e) {
      setMsg((e as Error).message ?? "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const openPreview = async () => {
    setMsg(null);
    try {
      setPreview(await previewApplyIrrigation(farmId, null));
    } catch (e) {
      setMsg((e as Error).message ?? "Preview failed.");
    }
  };

  const apply = async () => {
    if (!preview) return;
    setApplying(true);
    setMsg(null);
    try {
      const counts = await applyIrrigation(farmId, null);
      setMsg(`Applied to ${counts.blocks_touched} block(s).`);
      setPreview(null);
    } catch (e) {
      setMsg((e as Error).message ?? "Apply failed.");
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="mt-2 space-y-2 text-[11px]">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1">
          system
          <select
            value={value.irrigation_system ?? ""}
            onChange={(e) =>
              onChange({
                ...value,
                irrigation_system: e.target.value || null,
              })
            }
            className="rounded border border-slate-300 bg-white px-1 py-0.5"
          >
            <option value="">—</option>
            {IRRIGATION_SYSTEMS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          source
          <select
            value={value.irrigation_source ?? ""}
            onChange={(e) => onChange({ ...value, irrigation_source: e.target.value || null })}
            className="rounded border border-slate-300 bg-white px-1 py-0.5"
          >
            <option value="">—</option>
            {IRRIGATION_SOURCES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1">
          flow m³/h
          <input
            type="number"
            min={0}
            step={0.1}
            value={value.flow_rate_m3_per_hour ?? ""}
            onChange={(e) =>
              onChange({
                ...value,
                flow_rate_m3_per_hour: e.target.value === "" ? null : Number(e.target.value),
              })
            }
            className="w-20 rounded border border-slate-300 px-1 py-0.5"
          />
        </label>
      </div>
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
          className="rounded border border-emerald-400 bg-emerald-50 px-2 py-1 text-[11px] text-emerald-800 hover:bg-emerald-100"
        >
          Apply to blocks…
        </button>
        {msg ? <span className="text-[11px] text-slate-700">{msg}</span> : null}
      </div>
      {preview ? (
        <SimpleApplyPanel
          preview={preview}
          onApply={apply}
          onCancel={() => setPreview(null)}
          applying={applying}
        />
      ) : null}
    </div>
  );
}

// ---------- Org section ---------------------------------------------------

function OrgSection({
  farmId,
  value,
  onChange,
}: {
  farmId: string;
  value: OrgTemplate;
  onChange: (next: OrgTemplate) => void;
}) {
  const [raw, setRaw] = useState(value.default_tags.join(", "));
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [preview, setPreview] = useState<SimpleApplyPreview | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const tags = raw
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);
      const updated = await putOrgTemplate(farmId, { default_tags: tags });
      onChange(updated);
      setRaw(updated.default_tags.join(", "));
      setMsg("Template saved.");
    } catch (e) {
      setMsg((e as Error).message ?? "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const openPreview = async () => {
    setMsg(null);
    try {
      setPreview(await previewApplyOrg(farmId, null));
    } catch (e) {
      setMsg((e as Error).message ?? "Preview failed.");
    }
  };

  const apply = async () => {
    setApplying(true);
    setMsg(null);
    try {
      const counts = await applyOrg(farmId, null);
      setMsg(`Merged tags into ${counts.blocks_touched} block(s).`);
      setPreview(null);
    } catch (e) {
      setMsg((e as Error).message ?? "Apply failed.");
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="mt-2 space-y-2 text-[11px]">
      <p className="text-[10px] text-slate-500">
        Comma-separated tags. Apply is additive — block-local tags are never removed.
      </p>
      <input
        type="text"
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        placeholder="#cotton, #south"
        className="w-full rounded border border-slate-300 px-2 py-1"
      />
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-50 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save template"}
        </button>
        <button
          type="button"
          onClick={openPreview}
          className="rounded border border-emerald-400 bg-emerald-50 px-2 py-1 text-emerald-800 hover:bg-emerald-100"
        >
          Apply to blocks…
        </button>
        {msg ? <span className="text-slate-700">{msg}</span> : null}
      </div>
      {preview ? (
        <SimpleApplyPanel
          preview={preview}
          onApply={apply}
          onCancel={() => setPreview(null)}
          applying={applying}
        />
      ) : null}
    </div>
  );
}

// ---------- Simple apply preview (irrigation + org) ----------------------

function SimpleApplyPanel({
  preview,
  onApply,
  onCancel,
  applying,
}: {
  preview: SimpleApplyPreview;
  onApply: () => void;
  onCancel: () => void;
  applying: boolean;
}) {
  return (
    <div className="rounded border border-amber-300 bg-amber-50 p-2">
      <p className="text-[11px] font-semibold text-amber-900">
        Preview — {preview.matched_blocks} of {preview.total_blocks} blocks already match.
      </p>
      <ul className="mt-2 max-h-40 divide-y divide-amber-200 overflow-y-auto text-[11px]">
        {preview.blocks.map((d) => (
          <li key={d.block_id} className="flex items-center gap-2 py-1">
            <span className="flex-1 truncate font-mono text-[10px] text-slate-700">
              {d.block_id.slice(0, 8)}…
            </span>
            <span className={"text-[10px] " + (d.matches ? "text-emerald-700" : "text-amber-800")}>
              {d.matches ? "matches" : "will change"}
            </span>
          </li>
        ))}
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
        Apply preview — {preview.matched_blocks} of {preview.total_blocks} blocks already match.
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
