// The operation manual, laid out the way an agronomist reads it: a ribbon of
// phenology stages across the season, then each stage week by week (Week 1,
// Week 2 … no dates until a plan gives a start), each week with every task
// active in it: a repeating task says how many times it falls that week, a
// task done once over several weeks is listed in each of them. A row opens to
// product, dosage, notes, source and evidence. Read-only here.

import clsx from "clsx";

import { Card } from "@/components/Card";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { OperationManual } from "@/api/agriOperation";
import type { PlanTemplateActivity } from "@/api/planTemplates";
import { localizedField } from "@/lib/localizedField";
import { STAGE_COLORS, stageName, TYPE_CLASS } from "../lib/manualStyle";
import { manualWeeks, type ManualWeekTask } from "../lib/manualWeeks";
import { repeatLabel } from "../lib/repeat";
import { seasonLayout, stripEvidenceTags, type StageWindow } from "../lib/weeks";

interface ManualViewProps {
  manual: OperationManual;
  /** Which variety's calendar to lay the weeks out on (crop path). */
  varietyPath?: string | null;
}

export function ManualView({ manual, varietyPath }: ManualViewProps): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const lang = i18n.language;
  const [stageFilter, setStageFilter] = useState<string | null>(null);

  const variety =
    manual.varieties.find((v) => v.path === varietyPath) ?? manual.varieties[0] ?? null;
  const stages = variety?.stages.length ? variety.stages : manual.stages;
  const perennial = variety?.is_perennial ?? manual.is_perennial;
  const layout = useMemo(() => seasonLayout(stages, perennial), [stages, perennial]);
  const colorOf = (code: string): string =>
    STAGE_COLORS[
      Math.max(
        0,
        layout.windows.findIndex((w) => w.code === code),
      ) % STAGE_COLORS.length
    ];

  const plan = useMemo(() => manualWeeks(layout, manual.activities), [layout, manual.activities]);

  if (manual.activities.length === 0) {
    return <p className="text-sm text-ap-muted">{t("manual.noActivities")}</p>;
  }

  const visible = (code: string): boolean => stageFilter === null || stageFilter === code;

  return (
    <div className="flex flex-col gap-4">
      {layout.windows.length > 0 ? (
        <StageRibbon
          layout={layout.windows}
          total={layout.totalWeeks}
          colorOf={colorOf}
          lang={lang}
        />
      ) : null}

      <div className="flex flex-wrap gap-2" role="group" aria-label={t("manual.filterStages")}>
        <FilterButton active={stageFilter === null} onClick={() => setStageFilter(null)}>
          {t("manual.allStages")}
        </FilterButton>
        {plan.groups
          .flatMap((g) => (g.window ? [g.window] : []))
          .map((w) => (
            <FilterButton
              key={w.code}
              active={stageFilter === w.code}
              onClick={() => setStageFilter(w.code)}
            >
              <span className={clsx("inline-block h-2.5 w-2.5 rounded-sm", colorOf(w.code))} />
              {stageName(w.stage, lang)}
            </FilterButton>
          ))}
      </div>

      {plan.groups
        .filter((g) => (g.window ? visible(g.window.code) : stageFilter === null))
        .map((g) => {
          const w = g.window;
          const from = g.weeks[0]?.week ?? 1;
          const to = g.weeks[g.weeks.length - 1]?.week ?? from;
          return (
            <Card
              as="section"
              key={w?.code ?? "other-weeks"}
              noPadding
              title={
                w ? (
                  <span className="inline-flex items-center gap-2">
                    <span className={clsx("h-4 w-1.5 rounded-sm", colorOf(w.code))} aria-hidden />
                    {stageName(w.stage, lang)}
                  </span>
                ) : (
                  t("manual.otherWeeks")
                )
              }
              actions={
                <span className="text-xs text-ap-muted">{t("manual.weeks", { from, to })}</span>
              }
            >
              <ol>
                {g.weeks.map((wk) => (
                  <li key={wk.week} className="border-b border-ap-line last:border-b-0">
                    <div className="flex items-baseline gap-3 bg-ap-bg px-4 py-1.5">
                      <h4 className="text-sm font-semibold text-ap-ink">
                        {t("manual.weekN", { n: wk.week })}
                      </h4>
                      <span className="ms-auto text-xs text-ap-muted">
                        {wk.tasks.length === 0
                          ? t("manual.noTasksThisWeek")
                          : t("manual.weekTasks", { count: wk.tasks.length })}
                      </span>
                    </div>
                    {wk.tasks.length > 0 ? (
                      <ul>
                        {wk.tasks.map((task) => (
                          <ActivityRow
                            key={task.activity.id}
                            activity={task.activity}
                            when={whenThisWeek(task, t)}
                            muted={task.timesThisWeek === 0}
                            stage={
                              layout.windows.find((x) => x.code === task.activity.stage_code) ??
                              null
                            }
                          />
                        ))}
                      </ul>
                    ) : null}
                  </li>
                ))}
              </ol>
            </Card>
          );
        })}

      {plan.unplaced.length > 0 && stageFilter === null ? (
        <Card as="section" noPadding title={t("manual.fromStart")}>
          <p className="border-b border-ap-line px-4 py-2 text-xs text-ap-muted">
            {t("manual.fromStartHint")}
          </p>
          <ul>
            {plan.unplaced.map((a) => (
              <ActivityRow
                key={a.id}
                activity={a}
                when={repeatLabel(a.repeat_count, a.repeat_unit, t)}
                stage={null}
              />
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}

function FilterButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}): ReactNode {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium",
        active
          ? "border-ap-primary bg-ap-primary text-white"
          : "border-ap-line bg-ap-panel text-ap-ink hover:bg-ap-bg",
      )}
    >
      {children}
    </button>
  );
}

export function StageRibbon({
  layout,
  total,
  colorOf,
  lang,
}: {
  layout: StageWindow[];
  total: number;
  colorOf: (code: string) => string;
  lang: string;
}): ReactNode {
  const { t } = useTranslation("agriOperation");
  return (
    <div>
      <div
        className="flex h-9 w-full overflow-hidden rounded-md border border-ap-line"
        role="img"
        aria-label={t("manual.ribbonLabel", { weeks: total })}
      >
        {layout.map((w) => {
          const span = w.endWeek - w.startWeek + 1;
          const pct = (span / total) * 100;
          return (
            <div
              key={w.code}
              className={clsx("flex items-center overflow-hidden px-1.5", colorOf(w.code))}
              style={{ width: `${pct}%` }}
              title={`${stageName(w.stage, lang)} · ${t("manual.weeks", { from: w.startWeek, to: w.endWeek })}`}
            >
              {pct > 8 ? (
                <span className="truncate text-meta font-semibold text-ap-ink">
                  {stageName(w.stage, lang)}
                </span>
              ) : null}
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex justify-between text-meta text-ap-muted">
        <span>{t("manual.weekShort", { n: 1 })}</span>
        <span>{t("manual.weekShort", { n: total })}</span>
      </div>
    </div>
  );
}

function anchorText(
  activity: PlanTemplateActivity,
  stage: StageWindow | null,
  lang: string,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string {
  const offset = activity.offset_days ?? 0;
  if (activity.anchor === "stage" && stage) {
    const name = stageName(stage.stage, lang);
    return offset === 0
      ? t("manual.anchorStage", { stage: name })
      : t("manual.anchorStageOffset", { stage: name, days: offset > 0 ? `+${offset}` : offset });
  }
  if (activity.anchor === "milestone") return t("manual.anchorMilestone", { days: offset });
  return t("manual.anchorStart", { days: offset });
}

/** How a task sits in one week: how many times it falls there, that it falls
 *  in other weeks of its window, or that it is done once somewhere in it. */
function whenThisWeek(
  task: ManualWeekTask,
  t: (key: string, opts?: Record<string, unknown>) => string,
): string | null {
  const a = task.activity;
  if (task.timesThisWeek !== null) {
    const rate = repeatLabel(a.repeat_count, a.repeat_unit, t);
    return task.timesThisWeek > 0
      ? [t("manual.timesThisWeek", { count: task.timesThisWeek }), rate].filter(Boolean).join(" · ")
      : t("manual.notThisWeek", { rate });
  }
  if (task.lastWeek > task.firstWeek) {
    return t("manual.onceInWeeks", { from: task.firstWeek, to: task.lastWeek });
  }
  return null;
}

function ActivityRow({
  activity,
  when,
  muted,
  stage,
}: {
  activity: PlanTemplateActivity;
  when: string | null;
  muted?: boolean;
  stage: StageWindow | null;
}): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const lang = i18n.language;
  const title =
    localizedField(lang, activity.title ?? null, activity.title_ar) ??
    t(`planTemplates:activityType.${activity.activity_type}`);
  const product = localizedField(lang, activity.product_name, activity.product_name_ar);
  const dosage = localizedField(lang, activity.dosage, activity.dosage_ar);
  const notes = stripEvidenceTags(localizedField(lang, activity.notes, activity.notes_ar));
  return (
    <li className={clsx("border-t border-ap-line", muted && "opacity-60")}>
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-2.5 hover:bg-ap-bg">
          <span
            className={clsx(
              "shrink-0 rounded px-2 py-0.5 text-meta font-semibold",
              TYPE_CLASS[activity.activity_type] ?? "bg-ap-line text-ap-ink",
            )}
          >
            {t(`planTemplates:activityType.${activity.activity_type}`)}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-ap-ink">{title}</span>
            <span className="block truncate text-xs text-ap-muted">
              {[when, anchorText(activity, stage, lang, t)].filter(Boolean).join(" · ")}
            </span>
          </span>
          <span
            aria-hidden
            className="text-ap-muted transition-transform group-open:rotate-90 rtl:rotate-180 rtl:group-open:rotate-90"
          >
            ›
          </span>
        </summary>
        <dl className="grid gap-2 bg-ap-bg px-4 py-3 text-sm sm:grid-cols-[8rem_1fr]">
          {product ? (
            <>
              <dt className="text-xs font-semibold text-ap-muted">{t("manual.product")}</dt>
              <dd className="text-ap-ink">{product}</dd>
            </>
          ) : null}
          {dosage ? (
            <>
              <dt className="text-xs font-semibold text-ap-muted">{t("manual.dosage")}</dt>
              <dd className="text-ap-ink">{dosage}</dd>
            </>
          ) : null}
          {notes ? (
            <>
              <dt className="text-xs font-semibold text-ap-muted">{t("manual.notes")}</dt>
              <dd className="text-ap-ink">{notes}</dd>
            </>
          ) : null}
          <dt className="text-xs font-semibold text-ap-muted">{t("manual.source")}</dt>
          <dd className="flex flex-wrap items-center gap-2 text-ap-ink">
            {activity.source_tree_code
              ? t("manual.sourceTree", { code: activity.source_tree_code })
              : t("manual.sourceManual")}
            {activity.evidence_tier ? (
              <span className="rounded bg-ap-primary-soft px-1.5 py-0.5 text-meta font-semibold text-ap-primary">
                {t(`evidence.${activity.evidence_tier}`)}
              </span>
            ) : null}
          </dd>
        </dl>
      </details>
    </li>
  );
}
