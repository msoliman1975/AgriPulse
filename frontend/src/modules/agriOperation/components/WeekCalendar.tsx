// The calendar step, stage by stage and week by week: every week from the
// plan's first task to its last, with its dates and every task active in it.
// A repeating task appears once per time ("2 of 8"), each in the week the
// manual recommends; pick the exact day with the date field. Weeks a task's
// window covers without a time in them list it too, without a date field. A moved task keeps its new date
// after saving (C4) and can go back to the manual's date.

import clsx from "clsx";
import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { AllocationBlockSchedule } from "@/api/agriOperation";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { localizedField } from "@/lib/localizedField";
import {
  calendarWeeks,
  groupWeeksByStage,
  type CalendarItem,
  type CalendarSpanItem,
} from "../lib/calendarWeeks";
import { repeatLabel } from "../lib/repeat";
import { TYPE_CLASS } from "../lib/manualStyle";

interface WeekCalendarProps {
  blocks: AllocationBlockSchedule[];
  blockLabel: (blockId: string, fallback: string | null) => string;
  readOnly?: boolean;
  onMove: (blockId: string, activityKey: string, date: string | null) => void;
}

export function WeekCalendar({
  blocks,
  blockLabel,
  readOnly,
  onMove,
}: WeekCalendarProps): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const lang = i18n.language;
  const groups = useMemo(
    () => groupWeeksByStage(calendarWeeks(blocks), blocks[0]?.stages),
    [blocks],
  );
  const manyBlocks = blocks.length > 1;

  if (groups.length === 0) {
    return <p className="text-sm text-ap-muted">{t("plan.calendar.empty")}</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-ap-muted">
        {readOnly ? t("plan.calendar.readOnlyHint") : t("plan.calendar.hint")}
      </p>
      {groups.map((g, gi) => {
        const name = g.stage
          ? (localizedField(lang, g.stage.name_en, g.stage.name_ar) ?? g.stage.code)
          : t("plan.calendar.otherWeeks");
        const first = g.weeks[0];
        const last = g.weeks[g.weeks.length - 1];
        return (
          <Card
            as="section"
            key={`${g.stage?.code ?? "other"}-${gi}`}
            noPadding
            title={name}
            actions={
              first && last ? (
                <span className="text-xs text-ap-muted">
                  {t("plan.calendar.stageWeeks", { from: first.number, to: last.number })}
                </span>
              ) : null
            }
          >
            <ol>
              {g.weeks.map((w) => {
                const range = t("plan.calendar.weekRange", {
                  from: shortDate(w.from, lang),
                  to: shortDate(w.to, lang),
                });
                const label = t("plan.calendar.week", { n: w.number });
                const count = w.items.length + w.spans.length;
                return (
                  <li
                    key={w.number}
                    aria-label={`${label}, ${range}`}
                    className="border-b border-ap-line last:border-b-0"
                  >
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 bg-ap-bg px-4 py-2">
                      <span className="text-sm font-semibold text-ap-ink">{label}</span>
                      <span className="text-xs text-ap-muted">{range}</span>
                      <span className="ms-auto text-xs text-ap-muted">
                        {count === 0
                          ? t("plan.calendar.noTasks")
                          : t("plan.calendar.weekTasks", { count })}
                      </span>
                    </div>
                    {count > 0 ? (
                      <ul>
                        {w.items.map((it) => (
                          <TaskRow
                            key={`${it.blockId}:${it.activity.activity_key}`}
                            item={it}
                            blockName={manyBlocks ? blockLabel(it.blockId, it.blockCode) : null}
                            readOnly={readOnly}
                            onSet={(date) => onMove(it.blockId, it.activity.activity_key, date)}
                          />
                        ))}
                        {w.spans.map((sp) => (
                          <SpanRow
                            key={`${sp.blockId}:${sp.activity.activity_key}:span`}
                            item={sp}
                            blockName={manyBlocks ? blockLabel(sp.blockId, sp.blockCode) : null}
                          />
                        ))}
                      </ul>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </Card>
        );
      })}
    </div>
  );
}

/** A task whose window covers this week with no time falling in it: shown
 *  for completeness, dated in the week its time falls in. */
function SpanRow({
  item,
  blockName,
}: {
  item: CalendarSpanItem;
  blockName: string | null;
}): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const a = item.activity;
  const title =
    localizedField(i18n.language, a.title, a.title_ar) ??
    t(`planTemplates:activityType.${a.activity_type}`);
  const repeats = (a.occurrences ?? 1) > 1;
  const meta = [
    blockName,
    repeats
      ? repeatLabel(a.repeat_count, a.repeat_unit, t)
      : t("plan.calendar.onceInWeeks", { from: item.firstWeek, to: item.lastWeek }),
    item.nextDate
      ? t(repeats ? "plan.calendar.nextOn" : "plan.calendar.plannedOn", {
          date: shortDate(item.nextDate, i18n.language),
        })
      : null,
  ].filter(Boolean);
  return (
    <li className="flex flex-wrap items-center gap-3 border-t border-ap-line px-4 py-2 opacity-70 first:border-t-0">
      <span
        className={clsx(
          "shrink-0 rounded px-2 py-0.5 text-meta font-semibold",
          TYPE_CLASS[a.activity_type] ?? "bg-ap-line text-ap-ink",
        )}
      >
        {t(`planTemplates:activityType.${a.activity_type}`)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm text-ap-ink">{title}</span>
        <span className="block text-xs text-ap-muted">{meta.join(" · ")}</span>
      </span>
    </li>
  );
}

function TaskRow({
  item,
  blockName,
  readOnly,
  onSet,
}: {
  item: CalendarItem;
  blockName: string | null;
  readOnly?: boolean;
  onSet: (date: string | null) => void;
}): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const a = item.activity;
  const title =
    localizedField(i18n.language, a.title, a.title_ar) ??
    t(`planTemplates:activityType.${a.activity_type}`);
  const occurrences = a.occurrences ?? 1;
  const meta = [
    blockName,
    occurrences > 1
      ? t("plan.calendar.occurrence", { n: a.occurrence ?? 1, total: occurrences })
      : null,
    repeatLabel(a.repeat_count, a.repeat_unit, t),
    a.date_overridden ? t("plan.calendar.defaultDay", { date: a.default_date }) : null,
  ].filter(Boolean);
  return (
    <li className="flex flex-wrap items-center gap-3 border-t border-ap-line px-4 py-2 first:border-t-0">
      <span
        className={clsx(
          "shrink-0 rounded px-2 py-0.5 text-meta font-semibold",
          TYPE_CLASS[a.activity_type] ?? "bg-ap-line text-ap-ink",
        )}
      >
        {t(`planTemplates:activityType.${a.activity_type}`)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-ap-ink">
          {title}
          {a.date_overridden ? (
            <span className="ms-2 text-xs font-normal text-ap-muted">
              {t("plan.calendar.moved")}
            </span>
          ) : null}
        </span>
        {meta.length > 0 ? (
          <span className="block text-xs text-ap-muted">{meta.join(" · ")}</span>
        ) : null}
      </span>
      <input
        type="date"
        className="rounded-md border border-ap-line px-2 py-1 text-sm text-ap-ink"
        aria-label={t("plan.calendar.dateFor", { title })}
        value={a.scheduled_date}
        disabled={readOnly}
        onChange={(e) => {
          const v = e.target.value;
          if (v) onSet(v === a.default_date ? null : v);
        }}
      />
      {!readOnly && a.date_overridden ? (
        <Button variant="ghost" size="sm" onClick={() => onSet(null)}>
          {t("plan.calendar.reset")}
        </Button>
      ) : null}
    </li>
  );
}

function shortDate(iso: string, lang: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString(lang === "ar" ? "ar-EG" : "en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}
