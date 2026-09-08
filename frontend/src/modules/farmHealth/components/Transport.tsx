// The date axis: which day is shown, and how to move through the window.
//
// One frame per calendar day, including the days no sweep ran. The date
// stands on its own — Mohamed asked on 2026-09-07 to drop the line saying a
// value had been carried forward, because the screen shows the current
// state and when it was produced is a different question.

import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import {
  DEFAULT_RANGE,
  dateOf,
  frameMs,
  isoOf,
  windowLength,
  type DayWindow,
  type RangeId,
} from "../lib/window";

interface Props {
  win: DayWindow;
  /** Index into the window, 0 is the oldest day. */
  dayIndex: number;
  rangeId: RangeId;
  today: number;
  playing: boolean;
  speed: number;
  onDayIndex: (index: number) => void;
  onRange: (range: RangeId) => void;
  onCustom: (fromIso: string, toIso: string) => void;
  onPlay: () => void;
  onStop: () => void;
  onSpeed: (speed: number) => void;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function shortDate(day: number): string {
  const date = dateOf(day);
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}`;
}

export function Transport({
  win,
  dayIndex,
  rangeId,
  today,
  playing,
  speed,
  onDayIndex,
  onRange,
  onCustom,
  onPlay,
  onStop,
  onSpeed,
}: Props) {
  const { t, i18n } = useTranslation(["farmHealth"]);
  const days = windowLength(win);
  const last = days - 1;
  const currentDay = win.fromDay + dayIndex;
  const timer = useRef<number | null>(null);

  // The play loop lives here so the page does not re-arm it on every render.
  useEffect(() => {
    if (!playing) return undefined;
    const id = window.setInterval(() => {
      onDayIndex(dayIndex >= last ? last : dayIndex + 1);
      if (dayIndex >= last) onStop();
    }, frameMs(days, speed));
    timer.current = id;
    return () => {
      window.clearInterval(id);
      timer.current = null;
    };
  }, [playing, dayIndex, last, days, speed, onDayIndex, onStop]);

  const dateText = new Intl.DateTimeFormat(i18n.language, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(dateOf(currentDay));

  return (
    <div className="flex flex-wrap items-end gap-3 border-b border-ap-line bg-ap-bg px-4 py-2">
      <label className="flex flex-col gap-1">
        <span className="text-meta font-semibold uppercase tracking-wide text-ap-muted">
          {t("farmHealth:range.label")}
        </span>
        <select
          aria-label={t("farmHealth:range.label")}
          value={rangeId}
          onChange={(event) => onRange(event.target.value as RangeId)}
          className="rounded border border-ap-line bg-ap-panel px-2 py-1.5 text-sm"
        >
          <option value="30">{t("farmHealth:range.d30")}</option>
          <option value="90">{t("farmHealth:range.d90")}</option>
          <option value="365">{t("farmHealth:range.y1")}</option>
          <option value="custom">{t("farmHealth:range.custom")}</option>
        </select>
      </label>

      {/* Always visible, not only in custom mode: the window's own dates are
          worth reading, and editing one is how you ask for a custom range. */}
      <label className="flex flex-col gap-1">
        <span className="text-meta font-semibold uppercase tracking-wide text-ap-muted">
          {t("farmHealth:range.showing")}
        </span>
        <span className="flex items-center gap-2 text-sm text-ap-muted">
          <input
            type="date"
            aria-label={t("farmHealth:range.from")}
            value={isoOf(win.fromDay)}
            max={isoOf(today)}
            onChange={(event) => onCustom(event.target.value, isoOf(win.toDay))}
            className="rounded border border-ap-line bg-ap-panel px-2 py-1.5 text-sm text-ap-ink"
          />
          <span>{t("farmHealth:range.to")}</span>
          <input
            type="date"
            aria-label={t("farmHealth:range.toDate")}
            value={isoOf(win.toDay)}
            max={isoOf(today)}
            onChange={(event) => onCustom(isoOf(win.fromDay), event.target.value)}
            className="rounded border border-ap-line bg-ap-panel px-2 py-1.5 text-sm text-ap-ink"
          />
        </span>
      </label>

      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-label={t("farmHealth:transport.back")}
          onClick={() => {
            onStop();
            onDayIndex(Math.max(0, dayIndex - 1));
          }}
          className="h-8 w-8 rounded border border-ap-line bg-ap-panel"
        >
          &#8592;
        </button>
        <button
          type="button"
          aria-label={playing ? t("farmHealth:transport.pause") : t("farmHealth:transport.play")}
          onClick={() => (playing ? onStop() : onPlay())}
          className="h-8 w-10 rounded border border-ap-primary bg-ap-primary text-white"
        >
          {playing ? "❚❚" : "▶"}
        </button>
        <button
          type="button"
          aria-label={t("farmHealth:transport.forward")}
          onClick={() => {
            onStop();
            onDayIndex(Math.min(last, dayIndex + 1));
          }}
          className="h-8 w-8 rounded border border-ap-line bg-ap-panel"
        >
          &#8594;
        </button>
        <button
          type="button"
          disabled={dayIndex === last}
          onClick={() => {
            onStop();
            onDayIndex(last);
          }}
          className="rounded border border-ap-line bg-ap-panel px-3 py-1.5 text-sm disabled:opacity-45"
        >
          {t("farmHealth:transport.latest")}
        </button>
      </div>

      <div className="flex min-w-[12rem] flex-1 flex-col gap-1">
        <input
          type="range"
          aria-label={t("farmHealth:transport.date")}
          min={0}
          max={last}
          step={1}
          value={dayIndex}
          onChange={(event) => {
            onStop();
            onDayIndex(Number(event.target.value));
          }}
          className="w-full accent-ap-primary"
        />
        <span className="flex justify-between text-[10px] tabular-nums text-ap-muted">
          <span>{shortDate(win.fromDay)}</span>
          <span>{shortDate(win.toDay)}</span>
        </span>
      </div>

      <div className="flex gap-1" role="group" aria-label={t("farmHealth:transport.speed")}>
        {[1, 2, 4].map((mult) => (
          <button
            key={mult}
            type="button"
            aria-pressed={speed === mult}
            onClick={() => onSpeed(mult)}
            className={[
              "rounded border px-2 py-1 text-meta",
              speed === mult
                ? "border-ap-primary bg-ap-primary text-white"
                : "border-ap-line bg-ap-panel",
            ].join(" ")}
          >
            {mult}×
          </button>
        ))}
      </div>

      <div className="text-end">
        <div className="text-page-title font-semibold tabular-nums leading-8 text-ap-ink">
          {dateText}
        </div>
      </div>
    </div>
  );
}

export { DEFAULT_RANGE };
