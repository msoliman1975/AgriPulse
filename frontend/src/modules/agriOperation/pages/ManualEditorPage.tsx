// Platform > Operation manuals > one manual: the manual laid out by growth
// stage, edited in place (decisions H1, H3). Stage anchors come first; start
// and milestone anchors sit under "More anchors" (H4). A variety switcher
// shows the resolved weeks per variety (H5), and Publish shows what changed
// since the last publish and how many farms use the manual (H6).
// Replaces PlanTemplateEditorPage once it covers everything that page did (H2).

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

import type { PhenologyStage } from "@/api/agriOperation";
import { listInputs } from "@/api/inputs";
import { ACTIVITY_TYPES, type EvidenceTier, type PlanActivityType } from "@/api/planTemplates";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { StatusBanner } from "@/components/StatusBanner";
import { resolveErrorMessage } from "@/components/asyncState";
import { localizedField, localizedName } from "@/lib/localizedField";
import { ActivityInputFields } from "../components/ActivityInputFields";
import { CropPathFilter } from "@/modules/reports/components/CropPathFilter";
import { useAuthoringManual, usePublishImpact } from "@/queries/agriOperation";
import {
  useArchivePlanTemplate,
  useCreatePlanTemplate,
  useDeletePlanTemplate,
  usePlanTemplate,
  usePublishPlanTemplate,
  useTemplatePhenology,
  useUpdatePlanTemplate,
} from "@/queries/planTemplates";
import { SourcesMarker } from "@/modules/sources/SourcesMarker";
import { trackFeature } from "@/telemetry";
import { StageRibbon } from "../components/ManualView";
import {
  draftFromDetail,
  emptyManual,
  manualProblems,
  newActivity,
  nextKey,
  toWriteRequest,
  type ActivityDraft,
  type ManualDraft,
} from "../lib/manualDraft";
import { STAGE_COLORS, stageName, TYPE_CLASS } from "../lib/manualStyle";
import { activityWeek, seasonLayout } from "../lib/weeks";

const EVIDENCE: EvidenceTier[] = ["eg_fao", "eg", "generic", "manual"];
const INPUT = "rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink";
const LABEL = "flex flex-col gap-1 text-xs font-semibold text-ap-muted";

export function ManualEditorPage(): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const lang = i18n.language;
  const navigate = useNavigate();
  const { id } = useParams<{ id?: string }>();
  const isNew = !id || id === "new";
  const templateId = isNew ? null : (id ?? null);

  const detail = usePlanTemplate(templateId);
  const authoring = useAuthoringManual(templateId);
  const create = useCreatePlanTemplate();
  const update = useUpdatePlanTemplate(templateId ?? "");
  const publish = usePublishPlanTemplate();
  const archive = useArchivePlanTemplate();
  const remove = useDeletePlanTemplate();

  const [draft, setDraft] = useState<ManualDraft>(emptyManual);
  const [loaded, setLoaded] = useState(isNew);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [varietyPath, setVarietyPath] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [moreAnchors, setMoreAnchors] = useState(false);

  useEffect(() => {
    if (!detail.data || loaded) return;
    const d = draftFromDetail(detail.data);
    setDraft(d);
    setLoaded(true);
    if (d.activities.some((a) => a.anchor !== "stage") || d.milestones.length > 0) {
      setMoreAnchors(true);
    }
  }, [detail.data, loaded]);

  const edit = (patch: Partial<ManualDraft>): void => {
    setDraft((d) => ({ ...d, ...patch }));
    setDirty(true);
  };
  const editActivity = (key: string, patch: Partial<ActivityDraft>): void =>
    edit({ activities: draft.activities.map((a) => (a.key === key ? { ...a, ...patch } : a)) });

  // Stages: the saved manual's per-variety stages when the crop path is the
  // saved one, otherwise the phenology resolved for the path being edited.
  const phenology = useTemplatePhenology(draft.crop_path || null);
  const savedPath = detail.data?.crop_path ?? null;
  const varieties = savedPath === draft.crop_path ? (authoring.data?.varieties ?? []) : [];
  const variety = varieties.find((v) => v.path === varietyPath) ?? varieties[0] ?? null;
  const stages = useMemo<PhenologyStage[]>(
    () =>
      variety?.stages ??
      (phenology.data?.stages ?? [])
        .filter((s) => s.advance && typeof s.advance.mode === "string")
        .map((s) => ({
          code: s.code,
          name_en: s.name_en ?? null,
          name_ar: s.name_ar ?? null,
          advance: s.advance as unknown as PhenologyStage["advance"],
        })),
    [variety, phenology.data],
  );
  const perennial = variety?.is_perennial ?? phenology.data?.is_perennial ?? true;
  const layout = useMemo(() => seasonLayout(stages, perennial), [stages, perennial]);
  const colorOf = (code: string): string =>
    STAGE_COLORS[
      Math.max(
        0,
        layout.windows.findIndex((w) => w.code === code),
      ) % STAGE_COLORS.length
    ] ?? "bg-ap-line";

  const inputs = useQuery({
    queryKey: ["inputs", "template", draft.crop_path] as const,
    queryFn: () => listInputs({ cropPath: draft.crop_path || undefined }),
  });

  const status = detail.data?.status ?? "draft";
  const problems = manualProblems(draft);
  const saving = create.isPending || update.isPending;

  function save(): void {
    setError(null);
    if (problems.length > 0) {
      setError(t(`planTemplates:${problems[0]}`));
      return;
    }
    const body = toWriteRequest(draft);
    if (isNew) {
      create.mutate(body, {
        onSuccess: (saved) => {
          setDirty(false);
          trackFeature("operation_manual", { props: { action: "manual_created" } });
          navigate(`/platform/operation-manuals/${saved.id}`);
        },
        onError: (e) => setError(e.message),
      });
    } else {
      update.mutate(body, {
        onSuccess: (saved) => {
          setDraft(draftFromDetail(saved));
          setDirty(false);
          trackFeature("operation_manual", { props: { action: "manual_saved" } });
        },
        onError: (e) => setError(e.message),
      });
    }
  }

  if (!isNew && (detail.isLoading || !loaded)) {
    return (
      <Page>
        <Skeleton className="h-96 w-full" />
      </Page>
    );
  }

  const stageActs = (code: string): ActivityDraft[] =>
    draft.activities
      .filter((a) => a.anchor === "stage" && a.stage_code === code)
      .sort((a, b) => (activityWeek(a, layout) ?? 0) - (activityWeek(b, layout) ?? 0));
  const known = new Set(layout.windows.map((w) => w.code));
  const otherActs = draft.activities.filter(
    (a) => a.anchor !== "stage" || !a.stage_code || !known.has(a.stage_code),
  );

  return (
    <Page>
      <PageHeader
        title={
          isNew
            ? t("editor.newTitle")
            : localizedName(lang, draft.name || draft.code, draft.name_ar)
        }
        badge={
          isNew ? null : (
            <Pill kind={status === "published" ? "ok" : status === "archived" ? "neutral" : "warn"}>
              {t(`editor.status.${status}`)}
            </Pill>
          )
        }
        subtitle={t("editor.subtitle")}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => navigate("/platform/operation-manuals")}>
              {t("editor.back")}
            </Button>
            <Button disabled={saving || (!dirty && !isNew)} onClick={save}>
              {saving ? t("editor.saving") : t("editor.save")}
            </Button>
            {!isNew ? (
              <Button
                variant="secondary"
                disabled={dirty || publish.isPending}
                title={dirty ? t("editor.saveFirst") : undefined}
                onClick={() => setPublishing(true)}
              >
                {t("editor.publish")}
              </Button>
            ) : null}
          </div>
        }
      />

      {error ? <StatusBanner kind="crit">{error}</StatusBanner> : null}
      {dirty && !isNew ? <StatusBanner kind="info">{t("editor.unsaved")}</StatusBanner> : null}

      {publishing && templateId ? (
        <PublishPanel
          templateId={templateId}
          pending={publish.isPending}
          onCancel={() => setPublishing(false)}
          onConfirm={() =>
            publish.mutate(templateId, {
              onSuccess: () => {
                setPublishing(false);
                trackFeature("operation_manual", { props: { action: "manual_published" } });
              },
              onError: (e) => setError(e.message),
            })
          }
        />
      ) : null}

      <Card className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className={LABEL}>
          {t("editor.code")}
          <input
            className={INPUT}
            value={draft.code}
            onChange={(e) => edit({ code: e.target.value })}
            placeholder="mango-keitt-eg"
          />
        </label>
        <label className={LABEL}>
          {t("editor.name")}
          <input
            className={INPUT}
            value={draft.name}
            onChange={(e) => edit({ name: e.target.value })}
          />
        </label>
        <label className={LABEL}>
          {t("editor.nameAr")}
          <input
            className={INPUT}
            dir="rtl"
            value={draft.name_ar}
            onChange={(e) => edit({ name_ar: e.target.value })}
          />
        </label>
        <div className={clsx(LABEL, "sm:col-span-2 lg:col-span-1")}>
          {t("editor.crop")}
          <CropPathFilter
            value={draft.crop_path || null}
            onChange={(p) => edit({ crop_path: p ?? "" })}
            scope="platform"
          />
        </div>
        <label className={LABEL}>
          {t("editor.country")}
          <input
            className={INPUT}
            value={draft.country}
            onChange={(e) => edit({ country: e.target.value })}
          />
        </label>
        <label className={LABEL}>
          {t("editor.region")}
          <input
            className={INPUT}
            value={draft.region}
            onChange={(e) => edit({ region: e.target.value })}
          />
        </label>
        <label className={clsx(LABEL, "sm:col-span-2 lg:col-span-3")}>
          {t("editor.description")}
          <textarea
            className={INPUT}
            rows={2}
            value={draft.description}
            onChange={(e) => edit({ description: e.target.value })}
          />
        </label>
        <label className={clsx(LABEL, "sm:col-span-2 lg:col-span-3")}>
          {t("editor.descriptionAr")}
          <textarea
            className={INPUT}
            dir="rtl"
            rows={2}
            value={draft.description_ar}
            onChange={(e) => edit({ description_ar: e.target.value })}
          />
        </label>
      </Card>

      {varieties.length > 1 ? (
        <label className={clsx(LABEL, "w-fit")}>
          {t("catalog.variety")}
          <select
            className={clsx(INPUT, "min-w-48")}
            value={variety?.path ?? ""}
            onChange={(e) => setVarietyPath(e.target.value)}
          >
            {varieties.map((v) => (
              <option key={v.path} value={v.path}>
                {v.name_en ? localizedName(lang, v.name_en, v.name_ar) : t("catalog.cropCalendar")}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {!draft.crop_path ? (
        <StatusBanner kind="info">{t("editor.pickCrop")}</StatusBanner>
      ) : layout.windows.length > 0 ? (
        <StageRibbon
          layout={layout.windows}
          total={layout.totalWeeks}
          colorOf={colorOf}
          lang={lang}
        />
      ) : (
        <StatusBanner kind="warn">{t("editor.noStages")}</StatusBanner>
      )}

      {layout.windows.map((w) => (
        <Card
          key={w.code}
          as="section"
          noPadding
          title={
            <span className="inline-flex items-center gap-2">
              <span className={clsx("h-4 w-1.5 rounded-sm", colorOf(w.code))} aria-hidden />
              {stageName(w.stage, lang)}
            </span>
          }
          actions={
            <>
              <span className="text-xs text-ap-muted">
                {t("manual.weeks", { from: w.startWeek, to: w.endWeek })}
              </span>
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  edit({
                    activities: [...draft.activities, newActivity(w.code, draft.activities.length)],
                  })
                }
              >
                {t("editor.addToStage")}
              </Button>
            </>
          }
        >
          {stageActs(w.code).length === 0 ? (
            <p className="px-4 py-3 text-sm text-ap-muted">{t("editor.noActivitiesInStage")}</p>
          ) : (
            <ul>
              {stageActs(w.code).map((a) => (
                <ActivityEditorRow
                  key={a.key}
                  activity={a}
                  week={activityWeek(a, layout)}
                  stages={stages}
                  milestones={draft.milestones.map((m) => m.code).filter(Boolean)}
                  moreAnchors={moreAnchors}
                  manualCode={detail.data?.code ?? null}
                  inputs={inputs.data ?? []}
                  onChange={(patch) => editActivity(a.key, patch)}
                  onRemove={() =>
                    edit({ activities: draft.activities.filter((x) => x.key !== a.key) })
                  }
                />
              ))}
            </ul>
          )}
        </Card>
      ))}

      <Card
        as="section"
        noPadding
        title={t("editor.moreAnchors")}
        actions={
          <Button size="sm" variant="ghost" onClick={() => setMoreAnchors((v) => !v)}>
            {moreAnchors ? t("editor.hide") : t("editor.show")}
          </Button>
        }
      >
        <p className="border-b border-ap-line px-4 py-2 text-xs text-ap-muted">
          {t("editor.moreAnchorsHint")}
        </p>
        {moreAnchors ? (
          <div className="flex flex-col gap-3 p-4">
            <MilestonesEditor
              milestones={draft.milestones}
              onChange={(milestones) => edit({ milestones })}
            />
            <div className="flex items-center justify-between">
              <h3 className="text-card-title font-semibold text-ap-ink">
                {t("editor.otherActivities")}
              </h3>
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  edit({
                    activities: [...draft.activities, newActivity(null, draft.activities.length)],
                  })
                }
              >
                {t("editor.addFromStart")}
              </Button>
            </div>
            {otherActs.length === 0 ? (
              <p className="text-sm text-ap-muted">{t("editor.noOtherActivities")}</p>
            ) : (
              <ul className="rounded-card border border-ap-line">
                {otherActs.map((a) => (
                  <ActivityEditorRow
                    key={a.key}
                    activity={a}
                    week={activityWeek(a, layout)}
                    stages={stages}
                    milestones={draft.milestones.map((m) => m.code).filter(Boolean)}
                    moreAnchors
                    manualCode={detail.data?.code ?? null}
                    inputs={inputs.data ?? []}
                    onChange={(patch) => editActivity(a.key, patch)}
                    onRemove={() =>
                      edit({ activities: draft.activities.filter((x) => x.key !== a.key) })
                    }
                  />
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </Card>

      {!isNew && templateId ? (
        <Card className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-ap-muted">{t("editor.retireHint")}</p>
          <div className="flex flex-wrap gap-2">
            {status !== "archived" ? (
              <Button
                variant="secondary"
                disabled={archive.isPending}
                onClick={() => archive.mutate(templateId, { onError: (e) => setError(e.message) })}
              >
                {t("editor.archive")}
              </Button>
            ) : null}
            {confirmDelete ? (
              <>
                <Button
                  variant="danger"
                  disabled={remove.isPending}
                  onClick={() =>
                    remove.mutate(templateId, {
                      onSuccess: () => navigate("/platform/operation-manuals"),
                      onError: (e) => setError(e.message),
                    })
                  }
                >
                  {t("editor.confirmDelete")}
                </Button>
                <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
                  {t("plan.cancel")}
                </Button>
              </>
            ) : (
              <Button variant="ghost" onClick={() => setConfirmDelete(true)}>
                {t("editor.delete")}
              </Button>
            )}
          </div>
        </Card>
      ) : null}
    </Page>
  );
}

function PublishPanel({
  templateId,
  pending,
  onCancel,
  onConfirm,
}: {
  templateId: string;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const impact = usePublishImpact(templateId);
  const d = impact.data;
  const title = (c: { code: string; title: string | null; title_ar: string | null }): string =>
    localizedField(i18n.language, c.title, c.title_ar) ?? c.code;
  return (
    <Card className="flex flex-col gap-3" title={t("editor.publishTitle")}>
      {impact.isError ? (
        <StatusBanner kind="crit">
          {resolveErrorMessage(impact.error, t("editor.impactFailed"))}
        </StatusBanner>
      ) : !d ? (
        <p className="text-sm text-ap-muted">{t("plan.calendar.loading")}</p>
      ) : (
        <>
          <p className="text-sm text-ap-ink">
            {t("editor.impactUsage", { farms: d.farms, plans: d.saved_plans })}
          </p>
          {!d.comparable ? (
            <p className="text-sm text-ap-ink">{t("editor.firstPublish")}</p>
          ) : d.added.length + d.removed.length + d.changed.length === 0 ? (
            <p className="text-sm text-ap-ink">{t("editor.noChanges")}</p>
          ) : (
            <ul className="flex flex-col gap-1 text-sm text-ap-ink">
              {d.added.map((c) => (
                <li key={`a-${c.code}`}>{t("plan.changes.added", { title: title(c) })}</li>
              ))}
              {d.removed.map((c) => (
                <li key={`r-${c.code}`}>{t("plan.changes.removed", { title: title(c) })}</li>
              ))}
              {d.changed.map((c) => (
                <li key={`c-${c.code}`}>
                  {t("plan.changes.changed", {
                    title: title(c),
                    fields: c.fields
                      .map((f) => t(`plan.changes.field.${f}`, { defaultValue: f }))
                      .join(", "),
                  })}
                </li>
              ))}
            </ul>
          )}
          {d.farms > 0 ? <p className="text-xs text-ap-muted">{t("editor.farmsWillSee")}</p> : null}
        </>
      )}
      <div className="flex gap-2">
        <Button disabled={pending || !d} onClick={onConfirm}>
          {t("editor.confirmPublish")}
        </Button>
        <Button variant="ghost" onClick={onCancel}>
          {t("plan.cancel")}
        </Button>
      </div>
    </Card>
  );
}

function MilestonesEditor({
  milestones,
  onChange,
}: {
  milestones: ManualDraft["milestones"];
  onChange: (m: ManualDraft["milestones"]) => void;
}): ReactNode {
  const { t } = useTranslation("agriOperation");
  const set = (key: string, patch: Partial<ManualDraft["milestones"][number]>): void =>
    onChange(milestones.map((m) => (m.key === key ? { ...m, ...patch } : m)));
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h3 className="text-card-title font-semibold text-ap-ink">{t("editor.milestones")}</h3>
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            onChange([
              ...milestones,
              { key: nextKey(), code: "", name: "", name_ar: "", day_from_start: 0 },
            ])
          }
        >
          {t("editor.addMilestone")}
        </Button>
      </div>
      {milestones.map((m) => (
        <div key={m.key} className="grid gap-2 sm:grid-cols-[1fr_1fr_1fr_8rem_auto]">
          <input
            className={INPUT}
            aria-label={t("editor.milestoneCode")}
            placeholder={t("editor.milestoneCode")}
            value={m.code}
            onChange={(e) => set(m.key, { code: e.target.value })}
          />
          <input
            className={INPUT}
            aria-label={t("editor.name")}
            placeholder={t("editor.name")}
            value={m.name}
            onChange={(e) => set(m.key, { name: e.target.value })}
          />
          <input
            className={INPUT}
            dir="rtl"
            aria-label={t("editor.nameAr")}
            placeholder={t("editor.nameAr")}
            value={m.name_ar}
            onChange={(e) => set(m.key, { name_ar: e.target.value })}
          />
          <input
            className={INPUT}
            type="number"
            min={0}
            aria-label={t("editor.dayFromStart")}
            value={m.day_from_start}
            onChange={(e) => set(m.key, { day_from_start: Number(e.target.value) || 0 })}
          />
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onChange(milestones.filter((x) => x.key !== m.key))}
          >
            {t("plan.ops.remove")}
          </Button>
        </div>
      ))}
    </div>
  );
}

function ActivityEditorRow({
  activity: a,
  week,
  stages,
  milestones,
  moreAnchors,
  manualCode,
  inputs,
  onChange,
  onRemove,
}: {
  activity: ActivityDraft;
  week: number | null;
  stages: PhenologyStage[];
  milestones: string[];
  moreAnchors: boolean;
  /** The saved manual's code; source links are keyed by it (D27). */
  manualCode: string | null;
  inputs: Parameters<typeof ActivityInputFields>[0]["inputs"];
  onChange: (patch: Partial<ActivityDraft>) => void;
  onRemove: () => void;
}): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const lang = i18n.language;
  const title =
    localizedField(lang, a.title ?? null, a.title_ar) ??
    t(`planTemplates:activityType.${a.activity_type}`);
  const field = (
    name: keyof ActivityDraft,
    label: string,
    opts: { rtl?: boolean; area?: boolean } = {},
  ): ReactNode => (
    <label className={clsx(LABEL, opts.area && "sm:col-span-2")}>
      {label}
      {opts.area ? (
        <textarea
          className={INPUT}
          rows={2}
          dir={opts.rtl ? "rtl" : undefined}
          value={(a[name] as string | null) ?? ""}
          onChange={(e) => onChange({ [name]: e.target.value })}
        />
      ) : (
        <input
          className={INPUT}
          dir={opts.rtl ? "rtl" : undefined}
          value={(a[name] as string | null) ?? ""}
          onChange={(e) => onChange({ [name]: e.target.value })}
        />
      )}
    </label>
  );
  return (
    <li className="border-b border-ap-line last:border-b-0">
      <details open={!a.code}>
        <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-2.5 hover:bg-ap-bg">
          <span className="w-14 shrink-0 text-xs font-semibold tabular-nums text-ap-muted">
            {week !== null ? t("manual.weekShort", { n: week }) : "—"}
          </span>
          <span
            className={clsx(
              "rounded px-2 py-0.5 text-meta font-semibold",
              TYPE_CLASS[a.activity_type],
            )}
          >
            {t(`planTemplates:activityType.${a.activity_type}`)}
          </span>
          <span className="min-w-0 flex-1 truncate text-sm font-medium text-ap-ink">{title}</span>
          {a.code ? <span className="font-mono text-meta text-ap-muted">{a.code}</span> : null}
        </summary>
        <div className="grid gap-3 bg-ap-bg px-4 py-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className={LABEL}>
            {t("plan.ops.field.type")}
            <select
              className={INPUT}
              value={a.activity_type}
              onChange={(e) => onChange({ activity_type: e.target.value as PlanActivityType })}
            >
              {ACTIVITY_TYPES.map((x) => (
                <option key={x} value={x}>
                  {t(`planTemplates:activityType.${x}`)}
                </option>
              ))}
            </select>
          </label>
          {field("title", t("plan.ops.field.title"))}
          {field("title_ar", t("editor.titleAr"), { rtl: true })}
          <label className={LABEL}>
            {t("plan.ops.field.anchor")}
            <select
              className={INPUT}
              value={a.anchor}
              onChange={(e) => onChange({ anchor: e.target.value as ActivityDraft["anchor"] })}
            >
              <option value="stage">{t("plan.ops.anchorStage")}</option>
              {moreAnchors || a.anchor !== "stage" ? (
                <>
                  <option value="start">{t("editor.anchorStart")}</option>
                  <option value="milestone">{t("editor.anchorMilestone")}</option>
                </>
              ) : null}
            </select>
          </label>
          {a.anchor === "stage" ? (
            <label className={LABEL}>
              {t("plan.ops.field.stage")}
              <select
                className={INPUT}
                value={a.stage_code ?? ""}
                onChange={(e) => onChange({ stage_code: e.target.value || null })}
              >
                <option value="">—</option>
                {stages.map((s) => (
                  <option key={s.code} value={s.code}>
                    {stageName(s, lang)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {a.anchor === "milestone" ? (
            <label className={LABEL}>
              {t("editor.milestone")}
              <select
                className={INPUT}
                value={a.milestone_code ?? ""}
                onChange={(e) => onChange({ milestone_code: e.target.value || null })}
              >
                <option value="">—</option>
                {milestones.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label className={LABEL}>
            {t("editor.offset")}
            <input
              className={INPUT}
              type="number"
              value={a.offset_days}
              onChange={(e) => onChange({ offset_days: Number(e.target.value) || 0 })}
            />
          </label>
          <label className={LABEL}>
            {t("editor.duration")}
            <input
              className={INPUT}
              type="number"
              min={1}
              value={a.duration_days}
              onChange={(e) =>
                onChange({ duration_days: Math.max(1, Number(e.target.value) || 1) })
              }
            />
          </label>
          <div className="sm:col-span-2 lg:col-span-4">
            <ActivityInputFields row={a} inputs={inputs} onChange={(patch) => onChange(patch)} />
          </div>
          {field("product_name", t("plan.ops.field.product_name"))}
          {field("product_name_ar", t("editor.productAr"), { rtl: true })}
          {field("dosage", t("plan.ops.field.dosage"))}
          {field("dosage_ar", t("editor.dosageAr"), { rtl: true })}
          {field("notes", t("plan.ops.field.notes"), { area: true })}
          {field("notes_ar", t("editor.notesAr"), { rtl: true, area: true })}
          <label className={LABEL}>
            {t("manual.source")}
            <input
              className={INPUT}
              placeholder={t("editor.sourceTreePlaceholder")}
              value={a.source_tree_code ?? ""}
              onChange={(e) => onChange({ source_tree_code: e.target.value || null })}
            />
          </label>
          <label className={LABEL}>
            {t("editor.evidence")}
            <select
              className={INPUT}
              value={a.evidence_tier ?? ""}
              onChange={(e) =>
                onChange({ evidence_tier: (e.target.value || null) as EvidenceTier | null })
              }
            >
              <option value="">—</option>
              {EVIDENCE.map((x) => (
                <option key={x} value={x}>
                  {t(`evidence.${x}`)}
                </option>
              ))}
            </select>
          </label>
          {/* D27: the sources this activity cites, keyed by manual and
              activity code so the link survives revisions. Renders nothing
              when there are none. */}
          {manualCode && a.code ? (
            <div className="sm:col-span-2 lg:col-span-4">
              <SourcesMarker
                entityType="plan_template_activity"
                entityKey={`${manualCode}/${a.code}`}
              />
            </div>
          ) : null}
          <div className="flex items-end sm:col-span-2 lg:col-span-2">
            <Button size="sm" variant="ghost" onClick={onRemove}>
              {t("editor.removeActivity")}
            </Button>
          </div>
        </div>
      </details>
    </li>
  );
}
