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
  applyIrrigation,
  applyOrg,
  getIrrigationTemplate,
  getLocks,
  getOrgTemplate,
  lockCategory,
  previewApplyIrrigation,
  previewApplyOrg,
  putIrrigationTemplate,
  putOrgTemplate,
  unlockCategory,
} from "@/api/farmConfig";
import type {
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

export function BlockDefaultsPanel({ farmId }: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const [featureOff, setFeatureOff] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [locks, setLocks] = useState<LockState | null>(null);
  const [irrigation, setIrrigation] = useState<IrrigationTemplate | null>(null);
  const [orgTpl, setOrgTpl] = useState<OrgTemplate | null>(null);

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
        const [l, irr, org] = await Promise.all([
          getLocks(farmId),
          getIrrigationTemplate(farmId),
          getOrgTemplate(farmId),
        ]);
        if (cancelled) return;
        setLocks(l);
        setIrrigation(irr);
        setOrgTpl(org);
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
