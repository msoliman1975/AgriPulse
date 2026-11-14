// The calendar step: one lane per block, one column per day, every activity a
// bar on the date the server resolved (decision C2). Drag a bar, use the arrow
// keys on it, or select it and type a date to move it; a moved bar carries a
// dot and can be reset to its default day (C4 keeps the move after saving).

import clsx from "clsx";
import { useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { AllocationBlockSchedule, AllocatedActivityPreview } from "@/api/agriOperation";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { localizedField } from "@/lib/localizedField";
import { addDays, daysBetween } from "../lib/planDraft";
import { TYPE_CLASS } from "../lib/manualStyle";

const DAY_PX = 9;
const BAR_DAYS = 3;
const LANE_HEAD_PX = 168;

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
  const rtl = i18n.dir() === "rtl";
  const [selected, setSelected] = useState<{ blockId: string; key: string } | null>(null);

  const range = useMemo(() => {
    const dates = blocks.flatMap((b) => [
      b.start_date,
      ...b.activities.map((a) => a.scheduled_date),
    ]);
    if (dates.length === 0) return null;
    const sorted = [...dates].sort();
    const from = sorted[0] ?? "";
    const to = addDays(sorted[sorted.length - 1] ?? from, 7);
    return { from, days: Math.max(7, daysBetween(from, to)) };
  }, [blocks]);

  if (!range) return <p className="text-sm text-ap-muted">{t("plan.calendar.empty")}</p>;

  const weeks = Math.ceil(range.days / 7);
  const selectedActivity = selected
    ? blocks
        .find((b) => b.block_id === selected.blockId)
        ?.activities.find((a) => a.activity_key === selected.key)
    : undefined;

  return (
    <div className="flex flex-col gap-3">
      <Card noPadding className="overflow-x-auto" dir="ltr">
        <div style={{ width: LANE_HEAD_PX + range.days * DAY_PX }}>
          <div className="flex border-b border-ap-line">
            <div style={{ width: LANE_HEAD_PX }} className="shrink-0" />
            {Array.from({ length: weeks }, (_, w) => (
              <div
                key={w}
                style={{ width: DAY_PX * 7 }}
                className="shrink-0 border-s border-ap-line py-1 text-center text-meta text-ap-muted"
              >
                {shortDate(addDays(range.from, w * 7), i18n.language)}
              </div>
            ))}
          </div>
          {blocks.map((b) => (
            <div key={b.block_id} className="flex border-b border-ap-line last:border-b-0">
              <div
                style={{ width: LANE_HEAD_PX }}
                className="shrink-0 border-e border-ap-line px-3 py-2"
                dir={rtl ? "rtl" : "ltr"}
              >
                <div className="truncate text-sm font-semibold text-ap-ink">
                  {blockLabel(b.block_id, b.block_code)}
                </div>
                <div className="text-meta text-ap-muted">
                  {t("plan.calendar.starts", { date: shortDate(b.start_date, i18n.language) })}
                </div>
              </div>
              <div
                className="relative h-14 shrink-0"
                style={{
                  width: range.days * DAY_PX,
                  backgroundImage: `repeating-linear-gradient(90deg, #e8e5db 0 1px, transparent 1px ${DAY_PX * 7}px)`,
                }}
              >
                {b.activities.map((a, i) => (
                  <Bar
                    key={a.activity_key}
                    activity={a}
                    lane={i % 3}
                    offsetDays={daysBetween(range.from, a.scheduled_date)}
                    maxDays={range.days - BAR_DAYS}
                    selected={selected?.blockId === b.block_id && selected.key === a.activity_key}
                    readOnly={readOnly}
                    rtl={rtl}
                    onSelect={() => setSelected({ blockId: b.block_id, key: a.activity_key })}
                    onMoveDays={(delta) => onMove(b.block_id, a.activity_key, moveTo(a, delta))}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </Card>

      <p className="text-xs text-ap-muted">
        {readOnly ? t("plan.calendar.readOnlyHint") : t("plan.calendar.hint")}
      </p>

      {selected && selectedActivity ? (
        <BarEditor
          activity={selectedActivity}
          blockName={blockLabel(selected.blockId, null)}
          readOnly={readOnly}
          onSet={(date) => onMove(selected.blockId, selected.key, date)}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  );
}

/** The override to store for a move: none when the bar lands back on its default day. */
function moveTo(a: AllocatedActivityPreview, deltaDays: number): string | null {
  const next = addDays(a.scheduled_date, deltaDays);
  return next === a.default_date ? null : next;
}

function shortDate(iso: string, lang: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString(lang === "ar" ? "ar-EG" : "en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

function Bar({
  activity,
  lane,
  offsetDays,
  maxDays,
  selected,
  readOnly,
  rtl,
  onSelect,
  onMoveDays,
}: {
  activity: AllocatedActivityPreview;
  lane: number;
  offsetDays: number;
  maxDays: number;
  selected: boolean;
  readOnly?: boolean;
  rtl: boolean;
  onSelect: () => void;
  onMoveDays: (delta: number) => void;
}): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const drag = useRef<{ x: number; moved: boolean } | null>(null);
  const [dx, setDx] = useState(0);
  const title =
    localizedField(i18n.language, activity.title, activity.title_ar) ??
    t(`planTemplates:activityType.${activity.activity_type}`);
  const left = Math.max(0, Math.min(maxDays, offsetDays)) * DAY_PX + dx;

  return (
    <button
      type="button"
      className={clsx(
        "absolute h-4 rounded-sm border text-[0px] focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary",
        TYPE_CLASS[activity.activity_type] ?? "bg-ap-line",
        selected ? "border-ap-ink" : "border-transparent",
        readOnly ? "cursor-default" : "cursor-grab active:cursor-grabbing",
      )}
      style={{ left, top: 6 + lane * 15, width: BAR_DAYS * DAY_PX }}
      aria-label={t("plan.calendar.barLabel", {
        title,
        date: activity.scheduled_date,
        moved: activity.date_overridden ? t("plan.calendar.moved") : "",
      })}
      title={`${title} · ${activity.scheduled_date}`}
      onClick={() => {
        if (drag.current?.moved) return;
        onSelect();
      }}
      onKeyDown={(e) => {
        if (readOnly) return;
        if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
          e.preventDefault();
          const forward = e.key === "ArrowRight" ? 1 : -1;
          onMoveDays(rtl ? -forward : forward);
        }
      }}
      onPointerDown={(e) => {
        if (readOnly) return;
        drag.current = { x: e.clientX, moved: false };
        e.currentTarget.setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (!drag.current) return;
        const delta = e.clientX - drag.current.x;
        if (Math.abs(delta) > 3) drag.current.moved = true;
        setDx(delta);
      }}
      onPointerUp={() => {
        if (!drag.current) return;
        const days = Math.round(dx / DAY_PX);
        const moved = drag.current.moved;
        setDx(0);
        if (moved && days !== 0) onMoveDays(days);
        // Let the click handler see that this was a drag, then clear.
        window.setTimeout(() => {
          drag.current = null;
        }, 0);
      }}
    >
      {activity.date_overridden ? (
        <span className="absolute -end-1 -top-1 h-2 w-2 rounded-full bg-ap-ink" aria-hidden />
      ) : null}
    </button>
  );
}

function BarEditor({
  activity,
  blockName,
  readOnly,
  onSet,
  onClose,
}: {
  activity: AllocatedActivityPreview;
  blockName: string;
  readOnly?: boolean;
  onSet: (date: string | null) => void;
  onClose: () => void;
}): ReactNode {
  const { t, i18n } = useTranslation("agriOperation");
  const title =
    localizedField(i18n.language, activity.title, activity.title_ar) ??
    t(`planTemplates:activityType.${activity.activity_type}`);
  return (
    <Card className="flex flex-wrap items-end gap-3">
      <div className="min-w-0 flex-1 text-sm text-ap-ink">
        {t("plan.calendar.selected", { title, block: blockName })}
        <div className="text-xs text-ap-muted">
          {t("plan.calendar.defaultDay", { date: activity.default_date })}
        </div>
      </div>
      <label className="flex flex-col gap-1 text-xs font-semibold text-ap-muted">
        {t("plan.calendar.date")}
        <input
          type="date"
          className="rounded-md border border-ap-line px-2 py-1 text-sm text-ap-ink"
          value={activity.scheduled_date}
          disabled={readOnly}
          onChange={(e) => {
            const v = e.target.value;
            if (v) onSet(v === activity.default_date ? null : v);
          }}
        />
      </label>
      {!readOnly ? (
        <Button
          variant="secondary"
          size="sm"
          disabled={!activity.date_overridden}
          onClick={() => onSet(null)}
        >
          {t("plan.calendar.reset")}
        </Button>
      ) : null}
      <Button variant="ghost" size="sm" onClick={onClose}>
        {t("plan.calendar.close")}
      </Button>
    </Card>
  );
}
