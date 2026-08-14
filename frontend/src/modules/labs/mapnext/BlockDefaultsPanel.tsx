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
  applyGridCellSize,
  applyIrrigation,
  applyOrg,
  getGridTemplate,
  getIrrigationTemplate,
  getLocks,
  getOrgTemplate,
  lockCategory,
  previewApplyGrid,
  previewApplyIrrigation,
  previewApplyOrg,
  putGridTemplate,
  putIrrigationTemplate,
  putOrgTemplate,
  unlockCategory,
} from "@/api/farmConfig";
import type {
  GridApplyPreview,
  GridScope,
  GridTemplate,
  IrrigationTemplate,
  LockCategory,
  LockState,
  OrgTemplate,
  SimpleApplyPreview,
} from "@/api/farmConfig";
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

const input =
  "rounded-lg border border-ap-line bg-ap-panel px-2.5 py-1.5 text-sm text-ap-ink focus:border-ap-primary focus:outline-none";
const primaryBtn =
  "h-9 rounded-lg bg-ap-primary px-4 text-sm font-semibold text-white hover:bg-ap-primary/90 disabled:opacity-50";
const ghostBtn =
  "h-9 rounded-lg border border-ap-line bg-ap-panel px-3 text-sm font-semibold text-ap-ink hover:bg-ap-primary-soft disabled:opacity-50";
const applyBtn =
  "h-9 rounded-lg border border-ap-primary bg-ap-primary-soft px-3 text-sm font-semibold text-ap-primary hover:bg-ap-primary/15 disabled:opacity-50";
// Destructive actions read as destructive. `ap-crit` is the design
// system's existing critical colour — the bulk rezone retires live
// geometry across a whole farm and should not look like a Save.
const dangerBtn =
  "h-9 rounded-lg bg-ap-crit px-4 text-sm font-semibold text-white hover:bg-ap-crit/90 disabled:opacity-50";

function Card({
  title,
  lock,
  children,
}: {
  title: string;
  lock?: ReactNode;
  children: ReactNode;
}): ReactNode {
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
  /** Needed for the type-the-farm-name rezone confirmation. */
  farmName: string;
}

export function BlockDefaultsPanel({ farmId, farmName }: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [featureOff, setFeatureOff] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
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
        const [l, irr, org, grid] = await Promise.all([
          getLocks(farmId),
          getIrrigationTemplate(farmId),
          getOrgTemplate(farmId),
          getGridTemplate(farmId),
        ]);
        if (cancelled) return;
        setLocks(l);
        setIrrigation(irr);
        setOrgTpl(org);
        setGridTpl(grid);
      } catch (err) {
        if (cancelled) return;
        const status = isApiError(err)
          ? err.status
          : (err as { response?: { status?: number } })?.response?.status;
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
  if (!locks) return <p className="text-sm text-ap-muted">{t("blockDefaults.loading")}</p>;

  const lockChip = (cat: LockCategory) => (
    <LockChip
      farmId={farmId}
      category={cat}
      locked={locks?.[cat] ?? false}
      onChange={reloadLocks}
    />
  );

  return (
    <div className="space-y-4">
      <p className="rounded-lg bg-ap-primary-soft px-3 py-2 text-xs text-ap-ink">
        {t("blockDefaults.intro")}
      </p>

      <Card title={t("blockDefaults.irrigation")} lock={lockChip("irrigation")}>
        {irrigation ? (
          <IrrigationSection farmId={farmId} value={irrigation} onChange={setIrrigation} />
        ) : null}
      </Card>

      <Card title={t("blockDefaults.tags")} lock={lockChip("org")}>
        {orgTpl ? <OrgSection farmId={farmId} value={orgTpl} onChange={setOrgTpl} /> : null}
      </Card>

      <Card title={t("blockDefaults.grid")} lock={lockChip("grid")}>
        {gridTpl ? (
          <GridSection farmId={farmId} farmName={farmName} value={gridTpl} onChange={setGridTpl} />
        ) : null}
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

// Which actions a given scope's Apply would actually write. Used both to
// enable a row's checkbox and to count the selection, so the footer can
// never claim work the apply won't do.
const WRITES: Record<GridScope, ReadonlySet<string>> = {
  threshold: new Set(["threshold"]),
  cell_size: new Set(["rezone", "create"]),
};

function GridSection({
  farmId,
  farmName,
  value,
  onChange,
}: {
  farmId: string;
  farmName: string;
  value: GridTemplate;
  onChange: (next: GridTemplate) => void;
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [savedSnapshot, setSavedSnapshot] = useState<string>(() => normalizeGrid(value));
  const [saving, setSaving] = useState(false);
  const [applying, setApplying] = useState(false);
  const [clearOverride, setClearOverride] = useState(false);
  const [preview, setPreview] = useState<GridApplyPreview | null>(null);
  // Which scope the open preview belongs to. Kept beside the preview so a
  // stale preview from the other scope can never be confirmed.
  const [scope, setScope] = useState<GridScope>("threshold");
  const [confirmName, setConfirmName] = useState("");
  const [budget, setBudget] = useState<string>("");
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

  const openPreview = async (next: GridScope) => {
    // #330 guard: never preview a template the server hasn't seen.
    if (dirty) {
      say(t("blockDefaults.unsavedFirst"), "warn");
      return;
    }
    setMsg(null);
    try {
      const p = await previewApplyGrid(farmId, null, clearOverride, next);
      setScope(next);
      setPreview(p);
      setExcluded(new Set());
      setConfirmName("");
    } catch (e) {
      say((e as Error).message ?? t("blockDefaults.previewFailed"), "warn");
    }
  };

  // A row's identity is (block, product) — a block can be gridded against
  // more than one product, and those are independent decisions.
  const rowKey = (r: GridApplyPreview["rows"][number]) =>
    `${r.block_id}::${r.product_id ?? "none"}`;

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
      if (WRITES[scope].has(r.action) && !excluded.has(rowKey(r))) ids.add(r.block_id);
    }
    return [...ids];
  };

  const apply = async () => {
    if (!preview) return;
    setApplying(true);
    setMsg(null);
    try {
      const counts =
        scope === "cell_size"
          ? await applyGridCellSize(
              farmId,
              selectedBlockIds(),
              confirmName || null,
              budget.trim() === "" ? null : Number(budget),
            )
          : await applyGrid(farmId, selectedBlockIds(), clearOverride);
      if (counts.blocks_touched === 0) {
        // Zero changes is not a success — same lesson as #330.
        say(t("blockDefaults.appliedNothing"), "warn");
      } else if (scope === "cell_size" && counts.scenes_stranded > 0) {
        // Never let a partial recompute read as a clean rewrite.
        say(
          t("blockDefaults.rezonedPartial", {
            blocks: counts.blocks_touched,
            queued: counts.scenes_queued,
            stranded: counts.scenes_stranded,
          }),
          "warn",
        );
      } else {
        say(t("blockDefaults.appliedSimple", { blocks: counts.blocks_touched }));
      }
      setPreview(null);
      setConfirmName("");
    } catch (e) {
      say((e as Error).message ?? t("blockDefaults.applyFailed"), "warn");
    } finally {
      setApplying(false);
    }
  };

  const selectedCount = preview ? selectedBlockIds().length : 0;
  // The server re-checks this; the UI only decides when to ask.
  const needsConfirm = Boolean(preview?.requires_confirmation);
  const confirmSatisfied = !needsConfirm || confirmName.trim() === farmName;

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
            onChange={(e) =>
              onChange({
                ...value,
                anomaly_z_threshold: e.target.value === "" ? null : Number(e.target.value),
              })
            }
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
            onChange={(e) =>
              onChange({
                ...value,
                cell_size_m: e.target.value === "" ? null : Number(e.target.value),
              })
            }
            className={input + " w-24"}
          />
        </label>
      </div>
      <p className="text-xs text-ap-muted">{t("blockDefaults.thresholdHint")}</p>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={save} disabled={saving || !dirty} className={primaryBtn}>
          {saving ? t("manage.saving") : t("blockDefaults.saveTemplate")}
        </button>
        {dirty ? (
          <span className="text-xs text-ap-warn">{t("blockDefaults.unsavedFirst")}</span>
        ) : null}
        {msg ? (
          <span className={msgKind === "warn" ? "text-xs text-ap-muted" : "text-xs text-ap-muted"}>
            {msg}
          </span>
        ) : null}
      </div>

      {/* The numbering is load-bearing: a block with no grid cannot take a
          threshold, so ① gates ②. Applying them is deliberately two
          separate actions — one retires geometry and spends compute, the
          other writes a number. */}
      <div className="space-y-2 rounded-lg border border-ap-line p-3">
        <p className="text-xs font-semibold text-ap-ink">
          {t("blockDefaults.gridSectionCellSize")}
        </p>
        <p className="text-xs text-ap-muted">{t("blockDefaults.cellSizeDestructive")}</p>
        <button
          type="button"
          onClick={() => void openPreview("cell_size")}
          disabled={dirty}
          title={dirty ? t("blockDefaults.unsavedFirst") : undefined}
          className={dangerBtn}
        >
          {t("blockDefaults.applyCellSize")}
        </button>
      </div>

      <div className="space-y-2 rounded-lg border border-ap-line p-3">
        <p className="text-xs font-semibold text-ap-ink">
          {t("blockDefaults.gridSectionThreshold")}
        </p>
        <label className="flex items-start gap-2 text-xs text-ap-ink">
          <input
            type="checkbox"
            checked={clearOverride}
            onChange={(e) => {
              setClearOverride(e.target.checked);
              setPreview(null);
            }}
            className="mt-0.5"
          />
          <span>{t("blockDefaults.clearOverride")}</span>
        </label>
        <button
          type="button"
          onClick={() => void openPreview("threshold")}
          disabled={dirty}
          title={dirty ? t("blockDefaults.unsavedFirst") : undefined}
          className={applyBtn}
        >
          {t("blockDefaults.applyBlocks")}
        </button>
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
          {preview.is_noop ? (
            <p className="text-xs text-ap-warn">{t("blockDefaults.gridNothingToDo")}</p>
          ) : null}
          {scope === "cell_size" && preview.blocked_rows > 0 ? (
            <p className="text-xs text-ap-warn">
              {t("blockDefaults.gridBlockedRows", { blocked: preview.blocked_rows })}
            </p>
          ) : null}

          <ul className="max-h-56 space-y-1 overflow-auto">
            {preview.rows.map((r) => {
              const key = rowKey(r);
              const selectable = WRITES[scope].has(r.action);
              return (
                <li
                  key={key}
                  className={
                    "flex items-center gap-2 rounded border border-ap-line/60 px-2 py-1 text-xs " +
                    (selectable ? "" : "opacity-60")
                  }
                >
                  <input
                    type="checkbox"
                    checked={selectable && !excluded.has(key)}
                    disabled={!selectable}
                    onChange={() => toggleExcluded(key)}
                    aria-label={r.block_code}
                  />
                  <span className="font-semibold text-ap-ink">{r.block_code}</span>
                  {/* Product is a COLUMN, never a control: each block grids
                      against its own active subscription, so a farm-level
                      picker could select a product some blocks lack. */}
                  <span className="text-ap-muted">{r.product_code ?? "—"}</span>
                  <span
                    className={
                      "rounded px-1 " +
                      (r.action === "blocked" ? "bg-ap-warn-soft text-ap-warn" : "text-ap-muted")
                    }
                  >
                    {t(`blockDefaults.gridAction.${r.action}`)}
                  </span>
                  <span className="ms-auto text-ap-muted">
                    {!selectable
                      ? r.reason
                      : scope === "cell_size"
                        ? r.reason
                        : `${r.current_anomaly_z_threshold ?? "—"} → ${r.target_anomaly_z_threshold ?? t("blockDefaults.inherit")}`}
                  </span>
                </li>
              );
            })}
          </ul>

          {scope === "cell_size" && preview.rezone_rows > 0 ? (
            <div className="space-y-2 rounded-lg bg-ap-crit-soft p-2.5">
              {/* Refuse to hide the cost. An operator who doesn't know the
                  history goes dark until the backfill lands will read the
                  empty heatmap as a bug. */}
              <p className="text-xs text-ap-crit">
                {t("blockDefaults.rezoneCost", {
                  grids: preview.rezone_rows,
                  scenes: preview.scenes_affected,
                })}
              </p>
              <label className="flex flex-col gap-1 text-xs text-ap-muted">
                {t("blockDefaults.backfillBudget")}
                <input
                  type="number"
                  min={0}
                  step={100}
                  value={budget}
                  placeholder={t("blockDefaults.backfillBudgetAll")}
                  onChange={(e) => setBudget(e.target.value)}
                  className={input + " w-32"}
                />
              </label>
              {needsConfirm ? (
                <label className="flex flex-col gap-1 text-xs text-ap-crit">
                  {t("blockDefaults.typeFarmName", { farm: farmName })}
                  <input
                    type="text"
                    value={confirmName}
                    onChange={(e) => setConfirmName(e.target.value)}
                    aria-label={t("blockDefaults.typeFarmNameLabel")}
                    className={input + " w-56"}
                  />
                </label>
              ) : null}
            </div>
          ) : null}

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={apply}
              disabled={applying || selectedCount === 0 || !confirmSatisfied}
              className={scope === "cell_size" && preview.rezone_rows > 0 ? dangerBtn : primaryBtn}
            >
              {applying
                ? t("manage.saving")
                : scope === "cell_size" && preview.rezone_rows > 0
                  ? t("blockDefaults.gridConfirmRezone", { blocks: selectedCount })
                  : t("blockDefaults.gridConfirmApply", { blocks: selectedCount })}
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
}): ReactNode {
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
      const err = e as {
        response?: { status?: number; data?: { diff?: unknown; detail?: string } };
      };
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
        className={
          "rounded-lg border px-2 py-1 text-xs font-semibold " +
          (locked
            ? "border-ap-crit/40 bg-ap-crit/10 text-ap-crit"
            : "border-ap-good/40 bg-ap-good/10 text-ap-good")
        }
        title={locked ? t("blockDefaults.lockedHint") : t("blockDefaults.unlockedHint")}
      >
        {locked ? `🔒 ${t("blockDefaults.locked")}` : `🔓 ${t("blockDefaults.unlocked")}`}
      </button>
      {conflict ? (
        <button
          type="button"
          onClick={() => toggle(true)}
          disabled={busy}
          className="text-xs text-ap-warn underline"
        >
          {t("blockDefaults.lockOverwrite")}
        </button>
      ) : null}
      {error ? <span className="text-xs text-ap-crit">{error}</span> : null}
    </div>
  );
}

// ---- Irrigation ------------------------------------------------------------

function IrrigationSection({
  farmId,
  value,
  onChange,
}: {
  farmId: string;
  value: IrrigationTemplate;
  onChange: (next: IrrigationTemplate) => void;
}): ReactNode {
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
          <select
            value={value.irrigation_system ?? ""}
            onChange={(e) => onChange({ ...value, irrigation_system: e.target.value || null })}
            className={input}
          >
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
          <select
            value={value.irrigation_source ?? ""}
            onChange={(e) => onChange({ ...value, irrigation_source: e.target.value || null })}
            className={input}
          >
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
            onChange={(e) =>
              onChange({
                ...value,
                flow_rate_m3_per_hour: e.target.value === "" ? null : Number(e.target.value),
              })
            }
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

// ---- Tags ------------------------------------------------------------------

function OrgSection({
  farmId,
  value,
  onChange,
}: {
  farmId: string;
  value: OrgTemplate;
  onChange: (next: OrgTemplate) => void;
}): ReactNode {
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
      const tags = raw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
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
      <input
        type="text"
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        placeholder="#cotton, #south"
        className={input + " w-full"}
      />
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={save} disabled={saving} className={primaryBtn}>
          {saving ? t("manage.saving") : t("blockDefaults.saveTemplate")}
        </button>
        <button type="button" onClick={openPreview} className={applyBtn}>
          {t("blockDefaults.applyBlocks")}
        </button>
        {msg ? <span className="text-xs text-ap-muted">{msg}</span> : null}
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

// ---- Apply preview panels --------------------------------------------------

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
}): ReactNode {
  const { t } = useTranslation("farmConsole");
  return (
    <div className="rounded-xl border border-ap-warn/40 bg-ap-warn/10 p-3">
      <p className="text-xs font-semibold text-ap-ink">
        {t("blockDefaults.previewMatch", {
          matched: preview.matched_blocks,
          total: preview.total_blocks,
        })}
      </p>
      <ul className="mt-2 max-h-40 divide-y divide-ap-line/60 overflow-y-auto text-sm">
        {preview.blocks.map((d) => (
          <li key={d.block_id} className="flex items-center gap-2 py-1">
            <span className="flex-1 truncate font-mono text-xs text-ap-muted">
              {d.block_id.slice(0, 8)}…
            </span>
            <span className={"text-xs " + (d.matches ? "text-ap-good" : "text-ap-warn")}>
              {d.matches ? t("blockDefaults.matches") : t("blockDefaults.willChange")}
            </span>
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
