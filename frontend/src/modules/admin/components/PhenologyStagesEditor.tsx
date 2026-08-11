// Author a crop's stage calendar.
//
// This is what makes `growth_stage` exist. A daily task walks every block and
// moves it to whichever stage matches today — but only for crops that define a
// calendar, and only 3 of 23 did, because there has never been a way to write
// one outside a migration. For the other twenty, every stage-gated decision
// tree is silently unfireable.
//
// The rules the backend enforces, restated here so the author finds out before
// saving rather than after:
//
//   * Stage codes must be unique. Order is taken from position, so it cannot
//     collide by construction.
//   * A perennial has no planting date to count from, so it advances on
//     calendar windows (or by hand). An annual has no fixed calendar window,
//     so it counts days or degree-days from planting.
//   * `gdd_from_planting` needs the crop to set a GDD base temperature —
//     without one the stage can never resolve.
//
// The whole calendar is saved at once. The stages are too interdependent to
// patch one at a time, and a half-applied calendar would advance blocks
// through a sequence nobody authored.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ANNUAL_ADVANCE_MODES, PERENNIAL_ADVANCE_MODES } from "@/api/cropCatalog";
import type { AdvanceRule, Crop, PhenologyStage } from "@/api/crops";
import { defaultAdvance, validateStages } from "@/modules/admin/lib/phenologyStages";

interface Props {
  /** The crop supplies the *rules* — cycle and GDD base — even when the
   *  ladder being edited belongs to one of its varieties or strains. Every
   *  level is validated against the crop, never against its parent node. */
  crop: Crop;
  /** The ladder to edit. Omit for the crop's own; pass an override's stages
   *  (or a copy of the inherited ones) when editing a variety or strain. */
  initialStages?: PhenologyStage[];
  /** Overrides the default "Stage calendar — {crop}" heading, so an override
   *  editor can name the node it will actually write to. */
  heading?: string;
  busy: boolean;
  onCancel: () => void;
  onSave: (stages: PhenologyStage[]) => void;
}

export function PhenologyStagesEditor({
  crop,
  initialStages,
  heading,
  busy,
  onCancel,
  onSave,
}: Props): ReactNode {
  const { t } = useTranslation("admin");
  const [stages, setStages] = useState<PhenologyStage[]>(
    () =>
      (initialStages ?? crop.phenology_stages?.stages)
        ?.slice()
        .sort((a, b) => a.order - b.order)
        .map((s) => ({ ...s })) ?? [],
  );
  const [showProblems, setShowProblems] = useState(false);

  const modes: readonly string[] = crop.is_perennial
    ? PERENNIAL_ADVANCE_MODES
    : ANNUAL_ADVANCE_MODES;
  const problems = validateStages(stages, crop);

  const patch = (idx: number, next: Partial<PhenologyStage>): void =>
    setStages((prev) => prev.map((s, i) => (i === idx ? { ...s, ...next } : s)));

  const move = (idx: number, delta: number): void =>
    setStages((prev) => {
      const to = idx + delta;
      if (to < 0 || to >= prev.length) return prev;
      const next = [...prev];
      [next[idx], next[to]] = [next[to], next[idx]];
      return next;
    });

  const submit = (): void => {
    if (problems.length > 0) {
      setShowProblems(true);
      return;
    }
    // Order is position, so it is unique by construction — the backend
    // rejects duplicates and there is no reason to make a human maintain it.
    onSave(stages.map((s, i) => ({ ...s, order: i + 1 })));
  };

  return (
    <section className="rounded-md border border-ap-line bg-ap-panel p-3">
      <header className="mb-2">
        <h3 className="text-sm font-semibold text-ap-ink">
          {heading ?? t("phenology.heading", { crop: crop.name_en })}
        </h3>
        <p className="text-[11px] text-ap-muted">
          {crop.is_perennial ? t("phenology.perennialHint") : t("phenology.annualHint")}
        </p>
      </header>

      {stages.length === 0 ? (
        <p className="rounded border border-ap-warn/40 bg-ap-warn/5 p-2 text-[11px] text-ap-warn">
          {t("phenology.empty")}
        </p>
      ) : null}

      <ol className="flex flex-col gap-2">
        {stages.map((stage, idx) => (
          <li key={idx} className="rounded-md border border-ap-line bg-ap-bg/30 p-2">
            <div className="flex flex-wrap items-end gap-2">
              <span className="w-5 text-center text-xs text-ap-muted">{idx + 1}</span>
              <Text
                label={t("phenology.code")}
                value={stage.code}
                mono
                onChange={(v) => patch(idx, { code: v })}
              />
              <Text
                label={t("phenology.nameEn")}
                value={stage.name_en}
                onChange={(v) => patch(idx, { name_en: v })}
              />
              <Text
                label={t("phenology.nameAr")}
                value={stage.name_ar}
                dir="rtl"
                onChange={(v) => patch(idx, { name_ar: v })}
              />
              <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
                {t("phenology.advance")}
                <select
                  value={stage.advance.mode}
                  onChange={(e) =>
                    patch(idx, { advance: defaultAdvance(e.target.value as AdvanceRule["mode"]) })
                  }
                  className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs text-ap-ink"
                  aria-label={`${t("phenology.advance")} ${idx + 1}`}
                >
                  {modes.map((m) => (
                    <option key={m} value={m}>
                      {t(`phenology.mode.${m}`)}
                    </option>
                  ))}
                </select>
              </label>
              <AdvanceFields
                advance={stage.advance}
                onChange={(advance) => patch(idx, { advance })}
              />
              <div className="ms-auto flex gap-1">
                <IconButton label={t("phenology.moveUp")} onClick={() => move(idx, -1)}>
                  ↑
                </IconButton>
                <IconButton label={t("phenology.moveDown")} onClick={() => move(idx, 1)}>
                  ↓
                </IconButton>
                <IconButton
                  label={t("phenology.remove")}
                  danger
                  onClick={() => setStages((prev) => prev.filter((_, i) => i !== idx))}
                >
                  ✕
                </IconButton>
              </div>
            </div>
            {stage.advance.mode === "gdd_from_planting" && !crop.gdd_base_temp_c ? (
              <p className="mt-1 text-[11px] text-ap-warn">{t("phenology.needsGddBase")}</p>
            ) : null}
          </li>
        ))}
      </ol>

      <button
        type="button"
        onClick={() =>
          setStages((prev) => [
            ...prev,
            {
              code: "",
              name_en: "",
              name_ar: "",
              order: prev.length + 1,
              advance: defaultAdvance(crop.is_perennial ? "calendar_doy" : "days_from_planting"),
            },
          ])
        }
        className="mt-2 self-start rounded-md border border-dashed border-ap-line px-2 py-1 text-xs text-ap-ink hover:bg-ap-bg/60"
      >
        {t("phenology.addStage")}
      </button>

      {showProblems && problems.length > 0 ? (
        <ul role="alert" className="mt-2 flex flex-col gap-0.5">
          {problems.map((p) => (
            <li key={p} className="text-[11px] text-ap-crit">
              {p}
            </li>
          ))}
        </ul>
      ) : null}

      <footer className="mt-3 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-xs text-ap-ink hover:bg-ap-line/40"
        >
          {t("phenology.cancel")}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={submit}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {busy ? t("phenology.saving") : t("phenology.save")}
        </button>
      </footer>
    </section>
  );
}

function AdvanceFields({
  advance,
  onChange,
}: {
  advance: AdvanceRule;
  onChange: (next: AdvanceRule) => void;
}): ReactNode {
  const { t } = useTranslation("admin");
  if (advance.mode === "calendar_doy") {
    return (
      <>
        <Text
          label={t("phenology.from")}
          value={advance.start_doy}
          mono
          placeholder="03-15"
          onChange={(v) => onChange({ ...advance, start_doy: v })}
        />
        <Text
          label={t("phenology.to")}
          value={advance.end_doy}
          mono
          placeholder="05-31"
          onChange={(v) => onChange({ ...advance, end_doy: v })}
        />
      </>
    );
  }
  if (advance.mode === "days_from_planting") {
    return (
      <>
        <Num
          label={t("phenology.fromDay")}
          value={advance.start_day}
          onChange={(v) => onChange({ ...advance, start_day: v })}
        />
        <Num
          label={t("phenology.toDay")}
          value={advance.end_day}
          onChange={(v) => onChange({ ...advance, end_day: v })}
        />
      </>
    );
  }
  if (advance.mode === "gdd_from_planting") {
    return (
      <>
        <Num
          label={t("phenology.fromGdd")}
          value={advance.start_gdd}
          onChange={(v) => onChange({ ...advance, start_gdd: v })}
        />
        <Num
          label={t("phenology.toGdd")}
          value={advance.end_gdd}
          onChange={(v) => onChange({ ...advance, end_gdd: v })}
        />
      </>
    );
  }
  return null;
}

function Text({
  label,
  value,
  onChange,
  mono = false,
  dir,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  mono?: boolean;
  dir?: "rtl";
  placeholder?: string;
}): ReactNode {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
      {label}
      <input
        type="text"
        value={value}
        dir={dir}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        aria-label={label}
        className={`w-28 rounded-md border border-ap-line bg-white px-2 py-1 text-xs text-ap-ink ${
          mono ? "font-mono" : ""
        }`}
      />
    </label>
  );
}

function Num({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
}): ReactNode {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-ap-muted">
      {label}
      <input
        type="number"
        value={value}
        onChange={(e) => {
          const n = Number(e.target.value);
          if (!Number.isNaN(n)) onChange(n);
        }}
        aria-label={label}
        className="w-20 rounded-md border border-ap-line bg-white px-2 py-1 text-xs font-mono text-ap-ink"
      />
    </label>
  );
}

function IconButton({
  label,
  onClick,
  children,
  danger = false,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
  danger?: boolean;
}): ReactNode {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`rounded-md border border-ap-line bg-white px-2 py-0.5 text-[11px] hover:bg-ap-line/30 ${
        danger ? "text-ap-crit" : "text-ap-ink"
      }`}
    >
      {children}
    </button>
  );
}
