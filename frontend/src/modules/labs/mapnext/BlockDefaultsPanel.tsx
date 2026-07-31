// BlockDefaultsPanel — themed rewrite of the legacy FarmDefaultsTab for the
// Farm Console settings drawer. Same data model and farmConfig API calls
// (imagery + weather subscriptions template, irrigation, tags, category
// locks, save + apply-to-blocks), restyled to the ap-* design system and
// the app type scale, laid out as stacked cards instead of a cramped
// 3-column grid. The legacy FarmDefaultsTab is left untouched for the old
// /labs/map-legacy drawer.
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "@/api/errors";
import {
  applyGrid,
  applyIrrigation,
  applyOrg,
  applySubscriptions,
  getGridTemplate,
  getIrrigationTemplate,
  getLocks,
  getOrgTemplate,
  getSubscriptionsTemplate,
  lockCategory,
  previewApplyGrid,
  previewApplyIrrigation,
  previewApplyOrg,
  previewApplySubscriptions,
  putGridTemplate,
  putIrrigationTemplate,
  putOrgTemplate,
  replaceSubscriptionsTemplate,
  unlockCategory,
} from "@/api/farmConfig";
import type {
  ApplyPreview,
  GridApplyPreview,
  GridTemplate,
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

const IRRIGATION_SYSTEMS: IrrigationSystem[] = ["drip", "micro_sprinkler", "pivot", "furrow", "flood", "surface", "none"];
const IRRIGATION_SOURCES: IrrigationSource[] = ["well", "canal", "nile", "mixed"];

const input = "rounded-lg border border-ap-line bg-ap-panel px-2.5 py-1.5 text-sm text-ap-ink focus:border-ap-primary focus:outline-none";
const primaryBtn = "h-9 rounded-lg bg-ap-primary px-4 text-sm font-semibold text-white hover:bg-ap-primary/90 disabled:opacity-50";
const ghostBtn = "h-9 rounded-lg border border-ap-line bg-ap-panel px-3 text-sm font-semibold text-ap-ink hover:bg-ap-primary-soft disabled:opacity-50";
const applyBtn = "h-9 rounded-lg border border-ap-primary bg-ap-primary-soft px-3 text-sm font-semibold text-ap-primary hover:bg-ap-primary/15 disabled:opacity-50";

function Card({ title, lock, children }: { title: string; lock?: ReactNode; children: ReactNode }): ReactNode {
  return (
    <section className="rounded-xl border border-ap-line bg-ap-bg/40 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-bold text-ap-ink">{title}</h3>
        {lock}
      </div>
      {children}
    </section>
  );
}

interface Props {
  farmId: string;
}

// Apply reconciles blocks against the template *stored on the server*, not
// whatever is on screen. So an unsaved edit makes Apply a silent no-op that
// still reports success. Comparing a normalized snapshot lets us block that
// instead of letting the user believe it worked. Key order is normalized
// explicitly because the server and the row editors build these objects
// independently, and JSON.stringify is order-sensitive.
function normalizeTemplate(tpl: SubscriptionsTemplate): string {
  const imagery = [...tpl.imagery]
    .map((r) => ({
      product_id: r.product_id,
      cadence_hours: r.cadence_hours,
      cloud_cover_max_pct: r.cloud_cover_max_pct ?? null,
      is_active: r.is_active,
    }))
    .sort((a, b) => a.product_id.localeCompare(b.product_id));
  const weather = [...tpl.weather]
    .map((r) => ({
      provider_code: r.provider_code,
      cadence_hours: r.cadence_hours,
      is_active: r.is_active,
    }))
    .sort((a, b) => a.provider_code.localeCompare(b.provider_code));
  return JSON.stringify({ imagery, weather });
}

export function BlockDefaultsPanel({ farmId }: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [template, setTemplate] = useState<SubscriptionsTemplate | null>(null);
  // Last known server state, used only for the dirty check.
  const [savedTemplate, setSavedTemplate] = useState<string | null>(null);
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
  // A zero-effect apply is not a success — style the message accordingly.
  const [applyKind, setApplyKind] = useState<"ok" | "warn">("ok");
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [locks, setLocks] = useState<LockState | null>(null);
  const [irrigation, setIrrigation] = useState<IrrigationTemplate | null>(null);
  const [orgTpl, setOrgTpl] = useState<OrgTemplate | null>(null);
  const [gridTpl, setGridTpl] = useState<GridTemplate | null>(null);

  const reloadLocks = async () => {
    try {
      setLocks(await getLocks(farmId));
    } catch {
      /* leave previous */
    }
  };

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [tpl, c, l, irr, org, wp, grid] = await Promise.all([
          getSubscriptionsTemplate(farmId),
          getConfig(),
          getLocks(farmId),
          getIrrigationTemplate(farmId),
          getOrgTemplate(farmId),
          listWeatherProviders(),
          getGridTemplate(farmId),
        ]);
        if (cancelled) return;
        setTemplate(tpl);
        setSavedTemplate(normalizeTemplate(tpl));
        setProducts(c.products);
        setLocks(l);
        setIrrigation(irr);
        setOrgTpl(org);
        setWeatherProviders(wp);
        setGridTpl(grid);
      } catch (err) {
        if (cancelled) return;
        const status = isApiError(err) ? err.status : (err as { response?: { status?: number } })?.response?.status;
        if (status === 404) setFeatureOff(true);
        else setLoadError((err as Error).message ?? t("blockDefaults.loadError"));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [farmId, t]);

  if (featureOff) return <p className="text-sm text-ap-muted">{t("blockDefaults.featureOff")}</p>;
  if (loadError) return <p className="text-sm text-ap-crit">{loadError}</p>;
  if (!template) return <p className="text-sm text-ap-muted">{t("blockDefaults.loading")}</p>;

  const productById = new Map(products.map((p) => [p.product_id, p]));
  const dirty = savedTemplate !== null && normalizeTemplate(template) !== savedTemplate;
  // An empty *saved* template makes Apply a no-op unless blocks have rows to
  // deactivate; the preview's matched/total tells us which case we're in.
  const savedIsEmpty = savedTemplate === normalizeTemplate({ imagery: [], weather: [] });

  const addImageryRow = () => {
    const remaining = products.filter((p) => !template.imagery.some((r) => r.product_id === p.product_id));
    if (remaining.length === 0) return;
    setTemplate({
      ...template,
      imagery: [...template.imagery, { product_id: remaining[0].product_id, cadence_hours: 24, cloud_cover_max_pct: 30, is_active: true }],
    });
  };
  const updateImageryRow = (i: number, patch: Partial<ImageryTemplateRow>) =>
    setTemplate({ ...template, imagery: template.imagery.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) });
  const removeImageryRow = (i: number) => setTemplate({ ...template, imagery: template.imagery.filter((_, idx) => idx !== i) });

  const addWeatherRow = () => {
    const remaining = weatherProviders.filter((p) => !template.weather.some((r) => r.provider_code === p.code));
    const seed = remaining[0]?.code ?? weatherProviders[0]?.code ?? "";
    setTemplate({ ...template, weather: [...template.weather, { provider_code: seed, cadence_hours: 6, is_active: true }] });
  };
  const updateWeatherRow = (i: number, patch: Partial<WeatherTemplateRow>) =>
    setTemplate({ ...template, weather: template.weather.map((r, idx) => (idx === i ? { ...r, ...patch } : r)) });
  const removeWeatherRow = (i: number) => setTemplate({ ...template, weather: template.weather.filter((_, idx) => idx !== i) });

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await replaceSubscriptionsTemplate(farmId, template);
      setTemplate(updated);
      setSavedTemplate(normalizeTemplate(updated));
      setPreview(null);
    } catch (err) {
      setSaveError((err as Error).message ?? t("blockDefaults.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const openPreview = async () => {
    // Refuse rather than preview a template the server has never seen —
    // the diff would be computed against the stored rows and silently
    // ignore everything the user just typed.
    if (dirty) {
      setApplyKind("warn");
      setApplyMessage(t("blockDefaults.unsavedFirst"));
      return;
    }
    setPreviewLoading(true);
    setApplyMessage(null);
    try {
      setPreview(await previewApplySubscriptions(farmId, null));
      setExcluded(new Set());
    } catch (err) {
      setSaveError((err as Error).message ?? t("blockDefaults.previewFailed"));
    } finally {
      setPreviewLoading(false);
    }
  };

  const toggleExcluded = (blockId: string) => {
    const next = new Set(excluded);
    if (next.has(blockId)) next.delete(blockId);
    else next.add(blockId);
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
      const changed =
        counts.imagery_added +
        counts.imagery_updated +
        counts.imagery_deactivated +
        counts.weather_added +
        counts.weather_updated +
        counts.weather_deactivated;
      // "Applied to 0 blocks" in green reads as success while nothing
      // happened — the original symptom of this bug. Say so plainly.
      setApplyKind(changed === 0 ? "warn" : "ok");
      setApplyMessage(
        changed === 0
          ? t("blockDefaults.appliedNothing")
          : t("blockDefaults.applied", {
              blocks: counts.blocks_touched,
              imagery: `+${counts.imagery_added}/${counts.imagery_updated}/-${counts.imagery_deactivated}`,
              weather: `+${counts.weather_added}/${counts.weather_updated}/-${counts.weather_deactivated}`,
            }),
      );
      setPreview(null);
    } catch (err) {
      setApplyKind("warn");
      setApplyMessage((err as Error).message ?? t("blockDefaults.applyFailed"));
    } finally {
      setApplying(false);
    }
  };

  const lockChip = (cat: LockCategory) => <LockChip farmId={farmId} category={cat} locked={locks?.[cat] ?? false} onChange={reloadLocks} />;

  return (
    <div className="space-y-4">
      <p className="rounded-lg bg-ap-primary-soft px-3 py-2 text-xs text-ap-ink">{t("blockDefaults.intro")}</p>

      <Card title={t("blockDefaults.imagery")} lock={lockChip("subscriptions")}>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-ap-muted">{t("blockDefaults.products")}</span>
          <button type="button" onClick={addImageryRow} disabled={products.length === template.imagery.length} className={ghostBtn + " h-7 px-2 text-xs"}>
            + {t("blockDefaults.addProduct")}
          </button>
        </div>
        {template.imagery.length === 0 ? (
          <p className="text-xs text-ap-muted">{t("blockDefaults.noProducts")}</p>
        ) : (
          <ul className="space-y-2">
            {template.imagery.map((row, i) => {
              const meta = productById.get(row.product_id);
              return (
                <li key={i} className="flex flex-wrap items-center gap-2 rounded-lg border border-ap-line/70 p-2 text-sm">
                  <select value={row.product_id} onChange={(e) => updateImageryRow(i, { product_id: e.target.value })} className={input}>
                    {products.map((p) => (
                      <option key={p.product_id} value={p.product_id}>
                        {p.product_name}
                      </option>
                    ))}
                  </select>
                  <label className="flex items-center gap-1 text-xs text-ap-muted">
                    {t("blockDefaults.cadence")}
                    <input type="number" min={1} value={row.cadence_hours} onChange={(e) => updateImageryRow(i, { cadence_hours: Math.max(1, Number(e.target.value)) })} className={input + " w-16"} />
                    h
                  </label>
                  <label className="flex items-center gap-1 text-xs text-ap-muted">
                    {t("blockDefaults.cloud")} ≤
                    <input
                      type="number"
                      min={0}
                      max={100}
                      value={row.cloud_cover_max_pct ?? ""}
                      onChange={(e) => updateImageryRow(i, { cloud_cover_max_pct: e.target.value === "" ? null : Number(e.target.value) })}
                      className={input + " w-16"}
                    />
                    %
                  </label>
                  <label className="flex items-center gap-1 text-xs text-ap-muted">
                    <input type="checkbox" checked={row.is_active} onChange={(e) => updateImageryRow(i, { is_active: e.target.checked })} className="accent-ap-primary" />
                    {t("blockDefaults.active")}
                  </label>
                  <button type="button" onClick={() => removeImageryRow(i)} className="ms-auto rounded-lg border border-ap-line px-2 py-1 text-xs text-ap-crit hover:bg-ap-crit/10">
                    {t("blockDefaults.remove")}
                  </button>
                  {!meta ? <span className="basis-full text-xs text-ap-warn">{t("blockDefaults.notInCatalog")}</span> : null}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Card title={t("blockDefaults.weather")} lock={<span className="text-xs text-ap-muted">{t("blockDefaults.lockShared")}</span>}>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-ap-muted">{t("blockDefaults.providers")}</span>
          <button type="button" onClick={addWeatherRow} disabled={weatherProviders.length === 0} className={ghostBtn + " h-7 px-2 text-xs"}>
            + {t("blockDefaults.addProvider")}
          </button>
        </div>
        {weatherProviders.length === 0 ? (
          <p className="text-xs text-ap-warn">{t("blockDefaults.noProvidersCatalog")}</p>
        ) : template.weather.length === 0 ? (
          <p className="text-xs text-ap-muted">{t("blockDefaults.noProviders")}</p>
        ) : (
          <ul className="space-y-2">
            {template.weather.map((row, i) => {
              const inCatalog = weatherProviders.some((p) => p.code === row.provider_code);
              return (
                <li key={i} className="flex flex-wrap items-center gap-2 rounded-lg border border-ap-line/70 p-2 text-sm">
                  <select value={row.provider_code} onChange={(e) => updateWeatherRow(i, { provider_code: e.target.value })} className={input}>
                    {!inCatalog && row.provider_code ? <option value={row.provider_code}>{row.provider_code} ({t("blockDefaults.notInCatalog")})</option> : null}
                    {weatherProviders.map((p) => (
                      <option key={p.code} value={p.code}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                  <label className="flex items-center gap-1 text-xs text-ap-muted">
                    {t("blockDefaults.cadence")}
                    <input type="number" min={1} value={row.cadence_hours} onChange={(e) => updateWeatherRow(i, { cadence_hours: Math.max(1, Number(e.target.value)) })} className={input + " w-16"} />
                    h
                  </label>
                  <label className="flex items-center gap-1 text-xs text-ap-muted">
                    <input type="checkbox" checked={row.is_active} onChange={(e) => updateWeatherRow(i, { is_active: e.target.checked })} className="accent-ap-primary" />
                    {t("blockDefaults.active")}
                  </label>
                  <button type="button" onClick={() => removeWeatherRow(i)} className="ms-auto rounded-lg border border-ap-line px-2 py-1 text-xs text-ap-crit hover:bg-ap-crit/10">
                    {t("blockDefaults.remove")}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {/* Subscriptions Save + Apply (covers imagery + weather). */}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={save} disabled={saving} className={primaryBtn}>
          {saving ? t("manage.saving") : t("blockDefaults.saveSubs")}
        </button>
        <button
          type="button"
          onClick={openPreview}
          disabled={previewLoading || dirty}
          title={dirty ? t("blockDefaults.unsavedFirst") : undefined}
          className={applyBtn}
        >
          {previewLoading ? t("blockDefaults.previewing") : t("blockDefaults.applySubs")}
        </button>
        {saveError ? <span className="text-xs text-ap-crit">{saveError}</span> : null}
        {applyMessage ? <span className={"text-xs " + (applyKind === "ok" ? "text-ap-good" : "text-ap-warn")}>{applyMessage}</span> : null}
      </div>
      {dirty ? <p className="text-xs text-ap-warn">{t("blockDefaults.unsavedFirst")}</p> : null}
      {!dirty && savedIsEmpty ? <p className="text-xs text-ap-muted">{t("blockDefaults.emptyTemplateHint")}</p> : null}

      {preview ? (
        <ApplyPreviewPanel
          preview={preview}
          excluded={excluded}
          onToggle={toggleExcluded}
          onApply={apply}
          onCancel={() => setPreview(null)}
          applying={applying}
          savedIsEmpty={savedIsEmpty}
        />
      ) : null}

      <Card title={t("blockDefaults.irrigation")} lock={lockChip("irrigation")}>
        {irrigation ? <IrrigationSection farmId={farmId} value={irrigation} onChange={setIrrigation} /> : null}
      </Card>

      <Card title={t("blockDefaults.tags")} lock={lockChip("org")}>
        {orgTpl ? <OrgSection farmId={farmId} value={orgTpl} onChange={setOrgTpl} /> : null}
      </Card>

      <Card title={t("blockDefaults.grid")} lock={lockChip("grid")}>
        {gridTpl ? <GridSection farmId={farmId} value={gridTpl} onChange={setGridTpl} /> : null}
      </Card>
    </div>
  );
}

// ---- Grid & anomaly --------------------------------------------------------

// Same reasoning as normalizeTemplate: Apply reconciles against the SAVED
// template, so an unsaved edit would make it a silent no-op.
function normalizeGrid(v: GridTemplate): string {
  return JSON.stringify({
    cell_size_m: v.cell_size_m ?? null,
    anomaly_z_threshold: v.anomaly_z_threshold ?? null,
  });
}

function GridSection({ farmId, value, onChange }: { farmId: string; value: GridTemplate; onChange: (next: GridTemplate) => void }): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [savedSnapshot, setSavedSnapshot] = useState<string>(() => normalizeGrid(value));
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [clearOverride, setClearOverride] = useState(false);
  const [preview, setPreview] = useState<GridApplyPreview | null>(null);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState<string | null>(null);
  const [msgKind, setMsgKind] = useState<"ok" | "warn">("ok");

  const dirty = normalizeGrid(value) !== savedSnapshot;

  const say = (text: string, kind: "ok" | "warn" = "ok") => {
    setMsgKind(kind);
    setMsg(text);
  };

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const updated = await putGridTemplate(farmId, value);
      onChange(updated);
      setSavedSnapshot(normalizeGrid(updated));
      setPreview(null);
      say(t("blockDefaults.templateSaved"));
    } catch (e) {
      say((e as Error).message ?? t("blockDefaults.saveFailed"), "warn");
    } finally {
      setSaving(false);
    }
  };

  const openPreview = async () => {
    // #330 guard: never preview a template the server hasn't seen.
    if (dirty) {
      say(t("blockDefaults.unsavedFirst"), "warn");
      return;
    }
    setMsg(null);
    try {
      setPreview(await previewApplyGrid(farmId, null, clearOverride));
      setExcluded(new Set());
    } catch (e) {
      say((e as Error).message ?? t("blockDefaults.previewFailed"), "warn");
    }
  };

  // A row's identity is (block, product) — a block can be gridded against
  // more than one product, and those are independent decisions.
  const rowKey = (r: GridApplyPreview["rows"][number]) => `${r.block_id}::${r.product_id ?? "none"}`;

  const toggleExcluded = (key: string) => {
    const next = new Set(excluded);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setExcluded(next);
  };

  const selectedBlockIds = (): string[] => {
    if (!preview) return [];
    const ids = new Set<string>();
    for (const r of preview.rows) {
      if (r.action === "threshold" && !excluded.has(rowKey(r))) ids.add(r.block_id);
    }
    return [...ids];
  };

  const apply = async () => {
    if (!preview) return;
    setApplying(true);
    setMsg(null);
    try {
      const counts = await applyGrid(farmId, selectedBlockIds(), clearOverride);
      // Zero changes is not a success — same lesson as #330.
      say(
        counts.blocks_touched === 0
          ? t("blockDefaults.appliedNothing")
          : t("blockDefaults.appliedSimple", { blocks: counts.blocks_touched }),
        counts.blocks_touched === 0 ? "warn" : "ok",
      );
      setPreview(null);
    } catch (e) {
      say((e as Error).message ?? t("blockDefaults.applyFailed"), "warn");
    } finally {
      setApplying(false);
    }
  };

  const selectedCount = preview ? selectedBlockIds().length : 0;

  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-ap-muted">{t("blockDefaults.gridIntro")}</p>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-ap-muted">
          {t("blockDefaults.anomalyThreshold")}
          <input
            type="number"
            min={0.1}
            step={0.1}
            value={value.anomaly_z_threshold ?? ""}
            onChange={(e) => onChange({ ...value, anomaly_z_threshold: e.target.value === "" ? null : Number(e.target.value) })}
            className={input + " w-24"}
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-ap-muted">
          {t("blockDefaults.cellSize")}
          <input
            type="number"
            min={1}
            step={1}
            value={value.cell_size_m ?? ""}
            onChange={(e) => onChange({ ...value, cell_size_m: e.target.value === "" ? null : Number(e.target.value) })}
            className={input + " w-24"}
          />
        </label>
      </div>
      <p className="text-xs text-ap-muted">{t("blockDefaults.thresholdHint")}</p>
      {/* Cell size is stored but deliberately not applied yet — say so rather
          than letting the field imply a bulk rezone is one click away. */}
      <p className="rounded-lg bg-ap-warn-soft px-2.5 py-1.5 text-xs text-ap-warn">{t("blockDefaults.cellSizeNotApplied")}</p>

      <label className="flex items-start gap-2 text-xs text-ap-ink">
        <input type="checkbox" checked={clearOverride} onChange={(e) => { setClearOverride(e.target.checked); setPreview(null); }} className="mt-0.5" />
        <span>{t("blockDefaults.clearOverride")}</span>
      </label>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={save} disabled={saving || !dirty} className={primaryBtn}>
          {saving ? t("manage.saving") : t("blockDefaults.saveTemplate")}
        </button>
        <button type="button" onClick={openPreview} disabled={dirty} title={dirty ? t("blockDefaults.unsavedFirst") : undefined} className={applyBtn}>
          {t("blockDefaults.applyBlocks")}
        </button>
        {dirty ? <span className="text-xs text-ap-warn">{t("blockDefaults.unsavedFirst")}</span> : null}
        {msg ? <span className={msgKind === "warn" ? "text-xs text-ap-warn" : "text-xs text-ap-muted"}>{msg}</span> : null}
      </div>

      {preview ? (
        <div className="space-y-2 rounded-lg border border-ap-line bg-ap-panel p-3">
          <p className="text-xs text-ap-muted">
            {t("blockDefaults.gridPreviewSummary", {
              changed: preview.changed_rows,
              unchanged: preview.unchanged_rows,
              skipped: preview.skipped_rows,
            })}
          </p>
          {preview.is_noop ? <p className="text-xs text-ap-warn">{t("blockDefaults.gridNothingToDo")}</p> : null}
          <ul className="max-h-56 space-y-1 overflow-auto">
            {preview.rows.map((r) => {
              const key = rowKey(r);
              const selectable = r.action === "threshold";
              return (
                <li key={key} className={"flex items-center gap-2 rounded border border-ap-line/60 px-2 py-1 text-xs " + (selectable ? "" : "opacity-60")}>
                  <input
                    type="checkbox"
                    checked={selectable && !excluded.has(key)}
                    disabled={!selectable}
                    onChange={() => toggleExcluded(key)}
                    aria-label={r.block_code}
                  />
                  <span className="font-semibold text-ap-ink">{r.block_code}</span>
                  <span className="text-ap-muted">{r.product_code ?? "—"}</span>
                  <span className="ms-auto text-ap-muted">
                    {selectable
                      ? `${r.current_anomaly_z_threshold ?? "—"} → ${r.target_anomaly_z_threshold ?? t("blockDefaults.inherit")}`
                      : r.reason}
                  </span>
                </li>
              );
            })}
          </ul>
          <div className="flex items-center gap-2">
            <button type="button" onClick={apply} disabled={applying || selectedCount === 0} className={primaryBtn}>
              {applying ? t("manage.saving") : t("blockDefaults.gridConfirmApply", { blocks: selectedCount })}
            </button>
            <button type="button" onClick={() => setPreview(null)} className={ghostBtn}>
              {t("manage.cancel")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// ---- Lock chip -------------------------------------------------------------

function LockChip({ farmId, category, locked, onChange }: { farmId: string; category: LockCategory; locked: boolean; onChange: () => void }): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [busy, setBusy] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggle = async (force: boolean) => {
    setBusy(true);
    setError(null);
    setConflict(false);
    try {
      if (locked) await unlockCategory(farmId, category);
      else await lockCategory(farmId, category, force);
      onChange();
    } catch (e) {
      const err = e as { response?: { status?: number; data?: { diff?: unknown; detail?: string } } };
      if (err.response?.status === 409 && err.response.data?.diff) setConflict(true);
      else setError(err.response?.data?.detail ?? t("blockDefaults.toggleFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-1.5">
      <button
        type="button"
        onClick={() => toggle(false)}
        disabled={busy}
        className={"rounded-lg border px-2 py-1 text-xs font-semibold " + (locked ? "border-ap-crit/40 bg-ap-crit/10 text-ap-crit" : "border-ap-good/40 bg-ap-good/10 text-ap-good")}
        title={locked ? t("blockDefaults.lockedHint") : t("blockDefaults.unlockedHint")}
      >
        {locked ? `🔒 ${t("blockDefaults.locked")}` : `🔓 ${t("blockDefaults.unlocked")}`}
      </button>
      {conflict ? (
        <button type="button" onClick={() => toggle(true)} disabled={busy} className="text-xs text-ap-warn underline">
          {t("blockDefaults.lockOverwrite")}
        </button>
      ) : null}
      {error ? <span className="text-xs text-ap-crit">{error}</span> : null}
    </div>
  );
}

// ---- Irrigation ------------------------------------------------------------

function IrrigationSection({ farmId, value, onChange }: { farmId: string; value: IrrigationTemplate; onChange: (next: IrrigationTemplate) => void }): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [preview, setPreview] = useState<SimpleApplyPreview | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      onChange(await putIrrigationTemplate(farmId, value));
      setMsg(t("blockDefaults.templateSaved"));
    } catch (e) {
      setMsg((e as Error).message ?? t("blockDefaults.saveFailed"));
    } finally {
      setSaving(false);
    }
  };
  const openPreview = async () => {
    setMsg(null);
    try {
      setPreview(await previewApplyIrrigation(farmId, null));
    } catch (e) {
      setMsg((e as Error).message ?? t("blockDefaults.previewFailed"));
    }
  };
  const apply = async () => {
    if (!preview) return;
    setApplying(true);
    setMsg(null);
    try {
      const counts = await applyIrrigation(farmId, null);
      setMsg(t("blockDefaults.appliedSimple", { blocks: counts.blocks_touched }));
      setPreview(null);
    } catch (e) {
      setMsg((e as Error).message ?? t("blockDefaults.applyFailed"));
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="space-y-3 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1.5 text-xs text-ap-muted">
          {t("blockDefaults.system")}
          <select value={value.irrigation_system ?? ""} onChange={(e) => onChange({ ...value, irrigation_system: e.target.value || null })} className={input}>
            <option value="">—</option>
            {IRRIGATION_SYSTEMS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-ap-muted">
          {t("blockDefaults.source")}
          <select value={value.irrigation_source ?? ""} onChange={(e) => onChange({ ...value, irrigation_source: e.target.value || null })} className={input}>
            <option value="">—</option>
            {IRRIGATION_SOURCES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-xs text-ap-muted">
          {t("blockDefaults.flow")}
          <input
            type="number"
            min={0}
            step={0.1}
            value={value.flow_rate_m3_per_hour ?? ""}
            onChange={(e) => onChange({ ...value, flow_rate_m3_per_hour: e.target.value === "" ? null : Number(e.target.value) })}
            className={input + " w-24"}
          />
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={save} disabled={saving} className={primaryBtn}>
          {saving ? t("manage.saving") : t("blockDefaults.saveTemplate")}
        </button>
        <button type="button" onClick={openPreview} className={applyBtn}>
          {t("blockDefaults.applyBlocks")}
        </button>
        {msg ? <span className="text-xs text-ap-muted">{msg}</span> : null}
      </div>
      {preview ? <SimpleApplyPanel preview={preview} onApply={apply} onCancel={() => setPreview(null)} applying={applying} /> : null}
    </div>
  );
}

// ---- Tags ------------------------------------------------------------------

function OrgSection({ farmId, value, onChange }: { farmId: string; value: OrgTemplate; onChange: (next: OrgTemplate) => void }): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [raw, setRaw] = useState(value.default_tags.join(", "));
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [preview, setPreview] = useState<SimpleApplyPreview | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const tags = raw.split(",").map((s) => s.trim()).filter(Boolean);
      const updated = await putOrgTemplate(farmId, { default_tags: tags });
      onChange(updated);
      setRaw(updated.default_tags.join(", "));
      setMsg(t("blockDefaults.templateSaved"));
    } catch (e) {
      setMsg((e as Error).message ?? t("blockDefaults.saveFailed"));
    } finally {
      setSaving(false);
    }
  };
  const openPreview = async () => {
    setMsg(null);
    try {
      setPreview(await previewApplyOrg(farmId, null));
    } catch (e) {
      setMsg((e as Error).message ?? t("blockDefaults.previewFailed"));
    }
  };
  const apply = async () => {
    setApplying(true);
    setMsg(null);
    try {
      const counts = await applyOrg(farmId, null);
      setMsg(t("blockDefaults.mergedTags", { blocks: counts.blocks_touched }));
      setPreview(null);
    } catch (e) {
      setMsg((e as Error).message ?? t("blockDefaults.applyFailed"));
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-ap-muted">{t("blockDefaults.tagsHint")}</p>
      <input type="text" value={raw} onChange={(e) => setRaw(e.target.value)} placeholder="#cotton, #south" className={input + " w-full"} />
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={save} disabled={saving} className={primaryBtn}>
          {saving ? t("manage.saving") : t("blockDefaults.saveTemplate")}
        </button>
        <button type="button" onClick={openPreview} className={applyBtn}>
          {t("blockDefaults.applyBlocks")}
        </button>
        {msg ? <span className="text-xs text-ap-muted">{msg}</span> : null}
      </div>
      {preview ? <SimpleApplyPanel preview={preview} onApply={apply} onCancel={() => setPreview(null)} applying={applying} /> : null}
    </div>
  );
}

// ---- Apply preview panels --------------------------------------------------

function SimpleApplyPanel({ preview, onApply, onCancel, applying }: { preview: SimpleApplyPreview; onApply: () => void; onCancel: () => void; applying: boolean }): ReactNode {
  const { t } = useTranslation("farmConsole");
  return (
    <div className="rounded-xl border border-ap-warn/40 bg-ap-warn/10 p-3">
      <p className="text-xs font-semibold text-ap-ink">{t("blockDefaults.previewMatch", { matched: preview.matched_blocks, total: preview.total_blocks })}</p>
      <ul className="mt-2 max-h-40 divide-y divide-ap-line/60 overflow-y-auto text-sm">
        {preview.blocks.map((d) => (
          <li key={d.block_id} className="flex items-center gap-2 py-1">
            <span className="flex-1 truncate font-mono text-xs text-ap-muted">{d.block_id.slice(0, 8)}…</span>
            <span className={"text-xs " + (d.matches ? "text-ap-good" : "text-ap-warn")}>{d.matches ? t("blockDefaults.matches") : t("blockDefaults.willChange")}</span>
          </li>
        ))}
      </ul>
      <div className="mt-2 flex gap-2">
        <button type="button" onClick={onApply} disabled={applying} className={primaryBtn}>
          {applying ? t("blockDefaults.applying") : t("blockDefaults.confirmApply")}
        </button>
        <button type="button" onClick={onCancel} disabled={applying} className={ghostBtn}>
          {t("manage.cancel")}
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
  savedIsEmpty,
}: {
  preview: ApplyPreview;
  excluded: Set<string>;
  onToggle: (id: string) => void;
  onApply: () => void;
  onCancel: () => void;
  applying: boolean;
  savedIsEmpty: boolean;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const imageryById = new Map(preview.imagery.map((d) => [d.block_id, d]));
  const weatherById = new Map(preview.weather.map((d) => [d.block_id, d]));
  const allIds = new Set<string>();
  for (const d of preview.imagery) allIds.add(d.block_id);
  for (const d of preview.weather) allIds.add(d.block_id);
  // Every block already matches, so confirming would change nothing. Don't
  // offer a button whose only outcome is a misleading success message.
  const nothingToDo = preview.total_blocks > 0 && preview.matched_blocks === preview.total_blocks;

  return (
    <div className="rounded-xl border border-ap-warn/40 bg-ap-warn/10 p-3">
      <p className="text-xs font-semibold text-ap-ink">{t("blockDefaults.previewMatch", { matched: preview.matched_blocks, total: preview.total_blocks })}</p>
      {nothingToDo ? (
        <p className="mt-1 text-xs text-ap-warn">
          {savedIsEmpty ? t("blockDefaults.emptyTemplateHint") : t("blockDefaults.nothingToApply")}
        </p>
      ) : null}
      <ul className="mt-2 max-h-56 divide-y divide-ap-line/60 overflow-y-auto text-sm">
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
              <input type="checkbox" checked={!excluded.has(blockId)} onChange={() => onToggle(blockId)} disabled={matches} className="accent-ap-primary" />
              <span className="flex-1 truncate font-mono text-xs text-ap-muted">{blockId.slice(0, 8)}…</span>
              {matches ? <span className="text-xs text-ap-good">{t("blockDefaults.matches")}</span> : <span className="text-xs text-ap-warn">+{counts[0]} / ~{counts[1]} / -{counts[2]}</span>}
            </li>
          );
        })}
      </ul>
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          onClick={onApply}
          disabled={applying || nothingToDo}
          title={nothingToDo ? t("blockDefaults.nothingToApply") : undefined}
          className={primaryBtn}
        >
          {applying ? t("blockDefaults.applying") : t("blockDefaults.confirmApply")}
        </button>
        <button type="button" onClick={onCancel} disabled={applying} className={ghostBtn}>
          {t("manage.cancel")}
        </button>
      </div>
    </div>
  );
}
