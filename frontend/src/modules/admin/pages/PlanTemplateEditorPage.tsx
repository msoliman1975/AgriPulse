import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import {
  ACTIVITY_TYPES,
  type ActivityAnchor,
  type ActivityInput,
  type MilestoneInput,
  type PlanActivityType,
  type PlanTemplateWriteRequest,
} from "@/api/planTemplates";
import { CropPathFilter } from "@/modules/reports/components/CropPathFilter";
import { Field, FIELD_CONTROL_CLASS } from "@/components/Field";
import { Page } from "@/components/Page";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import {
  useArchivePlanTemplate,
  useCreatePlanTemplate,
  useDeletePlanTemplate,
  usePlanTemplate,
  usePublishPlanTemplate,
  useTemplatePhenology,
  useUpdatePlanTemplate,
} from "@/queries/planTemplates";

interface MilestoneRow extends MilestoneInput {
  key: string;
}
interface ActivityRow extends ActivityInput {
  key: string;
}

let _seq = 0;
const nextKey = (): string => `r${(_seq += 1)}`;

const EMPTY_ACTIVITY = (): ActivityRow => ({
  key: nextKey(),
  activity_type: "fertilizing",
  anchor: "start",
  offset_days: 0,
  duration_days: 1,
  sort_order: 0,
});

/**
 * /platform/plan-templates/(new|:id) — author the whole tree of a plan
 * template: header (crop_path via the cascading picker), template-local
 * milestones, and activities anchored to start / a milestone / a phenology
 * stage. Stage anchors only offer codes from the resolved phenology for the
 * chosen crop_path. A relative-day timeline previews the schedule. Saves
 * replace the whole tree atomically (PUT) or create (POST).
 */
export function PlanTemplateEditorPage(): ReactNode {
  const { t } = useTranslation("planTemplates");
  const navigate = useNavigate();
  const { id } = useParams<{ id?: string }>();
  const isNew = !id || id === "new";
  const templateId = isNew ? null : id;

  const detailQuery = usePlanTemplate(templateId);
  const create = useCreatePlanTemplate();
  const update = useUpdatePlanTemplate(templateId ?? "");
  const publish = usePublishPlanTemplate();
  const archive = useArchivePlanTemplate();
  const remove = useDeletePlanTemplate();

  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [cropPath, setCropPath] = useState<string | null>(null);
  const [country, setCountry] = useState("");
  const [region, setRegion] = useState("");
  const [description, setDescription] = useState("");
  const [milestones, setMilestones] = useState<MilestoneRow[]>([]);
  const [activities, setActivities] = useState<ActivityRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const status = detailQuery.data?.status ?? "draft";

  // Hydrate state from a loaded template (edit mode), once.
  useEffect(() => {
    const d = detailQuery.data;
    if (!d || loaded) return;
    setCode(d.code);
    setName(d.name);
    setCropPath(d.crop_path);
    setCountry(d.country ?? "");
    setRegion(d.region ?? "");
    setDescription(d.description ?? "");
    const msById = new Map(d.milestones.map((m) => [m.id, m.code]));
    setMilestones(
      d.milestones.map((m) => ({
        key: nextKey(),
        code: m.code,
        name: m.name,
        day_from_start: m.day_from_start,
        sort_order: m.sort_order,
      })),
    );
    setActivities(
      d.activities.map((a) => ({
        key: nextKey(),
        activity_type: a.activity_type as PlanActivityType,
        anchor: a.anchor,
        milestone_code: a.milestone_id ? (msById.get(a.milestone_id) ?? null) : null,
        stage_code: a.stage_code,
        offset_days: a.offset_days,
        duration_days: a.duration_days,
        product_name: a.product_name,
        dosage: a.dosage,
        notes: a.notes,
        sort_order: a.sort_order,
      })),
    );
    setLoaded(true);
  }, [detailQuery.data, loaded]);

  const phenology = useTemplatePhenology(cropPath);
  const stageOptions = phenology.data?.stages ?? [];
  const { i18n } = useTranslation();
  const isAr = i18n.language === "ar";
  const stageLabel = (codeStr: string): string => {
    const s = stageOptions.find((st) => st.code === codeStr);
    if (!s) return codeStr;
    return (isAr ? s.name_ar || s.name_en : s.name_en) || codeStr;
  };

  const milestoneCodes = milestones.map((m) => m.code).filter(Boolean);

  function buildBody(): PlanTemplateWriteRequest {
    return {
      code: code.trim(),
      name: name.trim(),
      crop_path: (cropPath ?? "").trim(),
      country: country.trim() || null,
      region: region.trim() || null,
      description: description.trim() || null,
      milestones: milestones.map((m, i) => ({
        code: m.code.trim(),
        name: m.name.trim(),
        day_from_start: Number(m.day_from_start) || 0,
        sort_order: i,
      })),
      activities: activities.map((a, i) => ({
        activity_type: a.activity_type,
        anchor: a.anchor,
        milestone_code: a.anchor === "milestone" ? (a.milestone_code ?? null) : null,
        stage_code: a.anchor === "stage" ? (a.stage_code ?? null) : null,
        offset_days: Number(a.offset_days) || 0,
        duration_days: Math.max(1, Number(a.duration_days) || 1),
        product_name: a.product_name?.trim() || null,
        dosage: a.dosage?.trim() || null,
        notes: a.notes?.trim() || null,
        sort_order: i,
      })),
    };
  }

  function clientValidate(body: PlanTemplateWriteRequest): string | null {
    if (!body.code) return t("editor.err.codeRequired");
    if (!body.name) return t("editor.err.nameRequired");
    if (!body.crop_path) return t("editor.err.cropRequired");
    for (const a of body.activities) {
      if (a.anchor === "milestone" && !a.milestone_code) return t("editor.err.milestoneRequired");
      if (a.anchor === "stage" && !a.stage_code) return t("editor.err.stageRequired");
    }
    return null;
  }

  function handleSave(): void {
    setError(null);
    const body = buildBody();
    const v = clientValidate(body);
    if (v) {
      setError(v);
      return;
    }
    if (isNew) {
      create.mutate(body, {
        onSuccess: (saved) => navigate(`/platform/plan-templates/${saved.id}`),
        onError: (e) => setError(e.message),
      });
    } else {
      update.mutate(body, { onError: (e) => setError(e.message) });
    }
  }

  const saving = create.isPending || update.isPending;

  if (!isNew && detailQuery.isLoading) {
    return (
      <Page>
        <Skeleton className="h-96 w-full" />
      </Page>
    );
  }

  return (
    <Page>
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => navigate("/platform/plan-templates")}
            className="text-sm text-ap-muted hover:text-ap-ink"
          >
            {i18n.dir() === "rtl" ? "→" : "←"} {t("editor.back")}
          </button>
          <h1 className="text-xl font-semibold text-ap-ink">
            {isNew ? t("editor.titleNew") : t("editor.titleEdit")}
          </h1>
          {!isNew ? (
            <Pill kind={status === "published" ? "ok" : "neutral"}>{t(`status.${status}`)}</Pill>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {!isNew && status !== "published" ? (
            <button
              type="button"
              onClick={() =>
                templateId && publish.mutate(templateId, { onError: (e) => setError(e.message) })
              }
              disabled={publish.isPending}
              className="rounded-md border border-ap-primary px-3 py-2 text-sm font-medium text-ap-primary hover:bg-ap-primary-soft disabled:opacity-60"
            >
              {t("editor.publish")}
            </button>
          ) : null}
          {!isNew && status === "published" ? (
            <button
              type="button"
              onClick={() =>
                templateId && archive.mutate(templateId, { onError: (e) => setError(e.message) })
              }
              disabled={archive.isPending}
              className="rounded-md border border-ap-line px-3 py-2 text-sm text-ap-muted hover:bg-ap-line/50 disabled:opacity-60"
            >
              {t("editor.archive")}
            </button>
          ) : null}
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-md bg-ap-primary px-4 py-2 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
          >
            {saving ? t("editor.saving") : t("editor.save")}
          </button>
        </div>
      </header>

      {error ? (
        <div className="rounded-md border border-ap-crit/40 bg-ap-crit-soft px-3 py-2 text-sm text-ap-crit">
          {error}
        </div>
      ) : null}

      {/* Header fields */}
      <section className="rounded-xl border border-ap-line bg-ap-panel p-4">
        <h2 className="mb-3 text-sm font-semibold text-ap-ink">{t("editor.section.header")}</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label={t("editor.field.name")}>
            {(props) => (
              <input
                {...props}
                className={FIELD_CONTROL_CLASS}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("editor.field.code")} help={t("editor.field.codeHint")}>
            {(props) => (
              <input
                {...props}
                className={`${FIELD_CONTROL_CLASS} font-mono`}
                value={code}
                disabled={!isNew}
                onChange={(e) => setCode(e.target.value)}
              />
            )}
          </Field>
          <div className="sm:col-span-2">
            <span className="mb-1 block text-xs font-medium text-ap-muted">
              {t("editor.field.cropPath")}
            </span>
            <CropPathFilter value={cropPath} onChange={setCropPath} scope="platform" />
          </div>
          <Field label={t("editor.field.country")}>
            {(props) => (
              <input
                {...props}
                className={FIELD_CONTROL_CLASS}
                value={country}
                onChange={(e) => setCountry(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("editor.field.region")}>
            {(props) => (
              <input
                {...props}
                className={FIELD_CONTROL_CLASS}
                value={region}
                onChange={(e) => setRegion(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("editor.field.description")} className="sm:col-span-2">
            {(props) => (
              <textarea
                {...props}
                className={`${FIELD_CONTROL_CLASS} min-h-[60px]`}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            )}
          </Field>
        </div>
      </section>

      {/* Milestones */}
      <section className="rounded-xl border border-ap-line bg-ap-panel p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ap-ink">{t("editor.section.milestones")}</h2>
          <button
            type="button"
            onClick={() =>
              setMilestones((prev) => [
                ...prev,
                { key: nextKey(), code: "", name: "", day_from_start: 0, sort_order: prev.length },
              ])
            }
            className="rounded-md border border-ap-line px-2 py-1 text-xs text-ap-primary hover:bg-ap-primary-soft"
          >
            + {t("editor.addMilestone")}
          </button>
        </div>
        {milestones.length === 0 ? (
          <p className="text-xs text-ap-muted">{t("editor.noMilestones")}</p>
        ) : (
          <div className="flex flex-col gap-2">
            {milestones.map((m, idx) => (
              <div key={m.key} className="flex flex-wrap items-center gap-2">
                <input
                  className="input w-32 font-mono"
                  placeholder={t("editor.field.code")}
                  value={m.code}
                  onChange={(e) =>
                    setMilestones((prev) =>
                      prev.map((x, i) => (i === idx ? { ...x, code: e.target.value } : x)),
                    )
                  }
                />
                <input
                  className="input flex-1"
                  placeholder={t("editor.field.name")}
                  value={m.name}
                  onChange={(e) =>
                    setMilestones((prev) =>
                      prev.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)),
                    )
                  }
                />
                <label className="flex items-center gap-1 text-xs text-ap-muted">
                  {t("editor.field.dayFromStart")}
                  <input
                    type="number"
                    className="input w-20"
                    value={m.day_from_start}
                    onChange={(e) =>
                      setMilestones((prev) =>
                        prev.map((x, i) =>
                          i === idx ? { ...x, day_from_start: Number(e.target.value) } : x,
                        ),
                      )
                    }
                  />
                </label>
                <button
                  type="button"
                  onClick={() => setMilestones((prev) => prev.filter((_, i) => i !== idx))}
                  className="text-xs text-ap-crit hover:underline"
                >
                  {t("editor.remove")}
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Activities */}
      <section className="rounded-xl border border-ap-line bg-ap-panel p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ap-ink">{t("editor.section.activities")}</h2>
          <button
            type="button"
            onClick={() => setActivities((prev) => [...prev, EMPTY_ACTIVITY()])}
            className="rounded-md border border-ap-line px-2 py-1 text-xs text-ap-primary hover:bg-ap-primary-soft"
          >
            + {t("editor.addActivity")}
          </button>
        </div>
        {activities.length === 0 ? (
          <p className="text-xs text-ap-muted">{t("editor.noActivities")}</p>
        ) : (
          <div className="flex flex-col gap-3">
            {activities.map((a, idx) => {
              const set = (patch: Partial<ActivityRow>): void =>
                setActivities((prev) => prev.map((x, i) => (i === idx ? { ...x, ...patch } : x)));
              return (
                <div
                  key={a.key}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-ap-line/70 bg-white p-2"
                >
                  <select
                    className="input w-36"
                    value={a.activity_type}
                    onChange={(e) => set({ activity_type: e.target.value as PlanActivityType })}
                    aria-label={t("editor.field.activityType")}
                  >
                    {ACTIVITY_TYPES.map((ty) => (
                      <option key={ty} value={ty}>
                        {t(`activityType.${ty}`)}
                      </option>
                    ))}
                  </select>
                  <select
                    className="input w-32"
                    value={a.anchor}
                    onChange={(e) => set({ anchor: e.target.value as ActivityAnchor })}
                    aria-label={t("editor.field.anchor")}
                  >
                    <option value="start">{t("anchor.start")}</option>
                    <option value="milestone">{t("anchor.milestone")}</option>
                    <option value="stage">{t("anchor.stage")}</option>
                  </select>
                  {a.anchor === "milestone" ? (
                    <select
                      className="input w-40"
                      value={a.milestone_code ?? ""}
                      onChange={(e) => set({ milestone_code: e.target.value || null })}
                      aria-label={t("anchor.milestone")}
                    >
                      <option value="">{t("editor.pickMilestone")}</option>
                      {milestoneCodes.map((mc) => (
                        <option key={mc} value={mc}>
                          {mc}
                        </option>
                      ))}
                    </select>
                  ) : null}
                  {a.anchor === "stage" ? (
                    <select
                      className="input w-44"
                      value={a.stage_code ?? ""}
                      onChange={(e) => set({ stage_code: e.target.value || null })}
                      disabled={phenology.isLoading || stageOptions.length === 0}
                      aria-label={t("anchor.stage")}
                    >
                      <option value="">{t("editor.pickStage")}</option>
                      {stageOptions.map((s) => (
                        <option key={s.code} value={s.code}>
                          {stageLabel(s.code)}
                        </option>
                      ))}
                    </select>
                  ) : null}
                  <label className="flex items-center gap-1 text-xs text-ap-muted">
                    {t("editor.field.offset")}
                    <input
                      type="number"
                      className="input w-16"
                      value={a.offset_days}
                      onChange={(e) => set({ offset_days: Number(e.target.value) })}
                    />
                  </label>
                  <label className="flex items-center gap-1 text-xs text-ap-muted">
                    {t("editor.field.duration")}
                    <input
                      type="number"
                      min={1}
                      className="input w-16"
                      value={a.duration_days}
                      onChange={(e) => set({ duration_days: Number(e.target.value) })}
                    />
                  </label>
                  <input
                    className="input w-40"
                    placeholder={t("editor.field.product")}
                    value={a.product_name ?? ""}
                    onChange={(e) => set({ product_name: e.target.value })}
                  />
                  <button
                    type="button"
                    onClick={() => setActivities((prev) => prev.filter((_, i) => i !== idx))}
                    className="ms-auto text-xs text-ap-crit hover:underline"
                  >
                    {t("editor.remove")}
                  </button>
                </div>
              );
            })}
          </div>
        )}
        {cropPath && stageOptions.length === 0 && !phenology.isLoading ? (
          <p className="mt-2 text-[11px] text-ap-warn">{t("editor.noStages")}</p>
        ) : null}
      </section>

      {/* Timeline preview */}
      <TimelinePreview milestones={milestones} activities={activities} stageLabel={stageLabel} />

      {!isNew ? (
        <div className="flex justify-end">
          <button
            type="button"
            onClick={() => {
              if (templateId && window.confirm(t("editor.confirmDelete"))) {
                remove.mutate(templateId, {
                  onSuccess: () => navigate("/platform/plan-templates"),
                  onError: (e) => setError(e.message),
                });
              }
            }}
            className="text-xs text-ap-crit hover:underline"
          >
            {t("editor.delete")}
          </button>
        </div>
      ) : null}
    </Page>
  );
}

/**
 * Relative-day timeline. Start- and milestone-anchored activities resolve to
 * a concrete day-from-start so they plot on a shared axis; stage-anchored
 * activities depend on per-block phenology, so they're listed by stage.
 */
function TimelinePreview({
  milestones,
  activities,
  stageLabel,
}: {
  milestones: MilestoneRow[];
  activities: ActivityRow[];
  stageLabel: (code: string) => string;
}): ReactNode {
  const { t } = useTranslation("planTemplates");
  const milestoneByCode = useMemo(() => new Map(milestones.map((m) => [m.code, m])), [milestones]);

  const dated = activities
    .map((a) => {
      if (a.anchor === "start") return { a, day: Number(a.offset_days) || 0 };
      if (a.anchor === "milestone") {
        const m = a.milestone_code ? milestoneByCode.get(a.milestone_code) : undefined;
        if (!m) return null;
        return { a, day: (Number(m.day_from_start) || 0) + (Number(a.offset_days) || 0) };
      }
      return null;
    })
    .filter((x): x is { a: ActivityRow; day: number } => x !== null)
    .sort((p, q) => p.day - q.day);

  const staged = activities.filter((a) => a.anchor === "stage");
  const maxDay = dated.reduce((mx, d) => Math.max(mx, d.day + (Number(d.a.duration_days) || 1)), 1);

  return (
    <section className="rounded-xl border border-ap-line bg-ap-panel p-4">
      <h2 className="mb-3 text-sm font-semibold text-ap-ink">{t("editor.section.timeline")}</h2>
      {dated.length === 0 && staged.length === 0 ? (
        <p className="text-xs text-ap-muted">{t("editor.timelineEmpty")}</p>
      ) : null}
      {dated.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          {dated.map(({ a, day }) => {
            const dur = Number(a.duration_days) || 1;
            const left = (day / maxDay) * 100;
            const width = Math.max(2, (dur / maxDay) * 100);
            return (
              <div key={a.key} className="flex items-center gap-2">
                <span className="w-28 shrink-0 truncate text-[11px] text-ap-muted">
                  {t(`activityType.${a.activity_type}`)}
                </span>
                <div className="relative h-4 flex-1 rounded bg-ap-line/40">
                  <div
                    className="absolute top-0 h-4 rounded bg-ap-primary/70"
                    style={{ insetInlineStart: `${left}%`, width: `${width}%` }}
                    title={t("editor.dayN", { day })}
                  />
                </div>
                <span className="w-16 shrink-0 text-end text-[11px] text-ap-muted">
                  {t("editor.dayN", { day })}
                </span>
              </div>
            );
          })}
        </div>
      ) : null}
      {staged.length > 0 ? (
        <div className="mt-3 border-t border-ap-line pt-3">
          <p className="mb-1 text-[11px] font-medium text-ap-muted">{t("editor.stageAnchored")}</p>
          <ul className="flex flex-col gap-1">
            {staged.map((a) => (
              <li key={a.key} className="text-[11px] text-ap-ink">
                <span className="font-medium">{t(`activityType.${a.activity_type}`)}</span>{" "}
                <span className="text-ap-muted">
                  {t("editor.atStage", {
                    stage: a.stage_code ? stageLabel(a.stage_code) : "—",
                    offset: Number(a.offset_days) || 0,
                  })}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
