// The one control that is always on screen: the play head, the index
// trend behind it, and a tick for every day that has datapoints.
//
// The draggable element is a real `<input type="range">`. An SVG with a
// pointer handler would look the same and be unreachable by keyboard,
// and this is the only way to move through the replay.

import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { TimelineDay } from "@/api/timeline";
import { Card } from "@/components/Card";

export interface TrendPoint {
  day: string;
  value: number;
}

interface Props {
  frames: readonly string[];
  index: number;
  onIndexChange: (index: number) => void;
  /** Day -> counts, for the ticks. Days with no events are absent. */
  days: Map<string, TimelineDay>;
  /** Acquisition days, so a reader can tell a real pass from a carried one. */
  passDays: ReadonlySet<string>;
  /** Farm or block mean of the drawn index, one point per day that has one. */
  trend: readonly TrendPoint[];
  playing: boolean;
  onTogglePlay: () => void;
  speed: number;
  onSpeedChange: (speed: number) => void;
  /** Formats a day key in the user's locale. */
  formatDay: (day: string) => string;
}

const TRACK_HEIGHT = 56;
const TREND_TOP = 6;
const TREND_HEIGHT = 26;
const TICK_TOP = TREND_TOP + TREND_HEIGHT + 4;

const SPEEDS: readonly number[] = [1, 2, 4, 8];

/** Tick colour per kind. One dot per day, coloured by its worst kind. */
const KIND_TONE: Record<string, string> = {
  alert: "#b24430", // ap-crit
  recommendation: "#c98a18", // ap-warn
  flag: "#c46b50", // ap-stage-harv
  visit: "#1f6f9a", // ap-accent
  signal: "#6c7268", // ap-muted
  activity: "#4f8e4a", // ap-good
  stage: "#8d4ab0", // ap-spray
};

// Which kind a day's dot takes when several land on it. Ordered worst
// first, so a day carrying an alert and a completed activity reads as the
// alert — the thing a reader is scrubbing to find.
const TONE_ORDER = ["alert", "flag", "recommendation", "visit", "stage", "signal", "activity"];

function dayTone(day: TimelineDay): string {
  for (const kind of TONE_ORDER) {
    if ((day.counts[kind as keyof typeof day.counts] ?? 0) > 0) {
      return KIND_TONE[kind] ?? "#6c7268";
    }
  }
  return "#6c7268";
}

export function Scrubber({
  frames,
  index,
  onIndexChange,
  days,
  passDays,
  trend,
  playing,
  onTogglePlay,
  speed,
  onSpeedChange,
  formatDay,
}: Props): ReactNode {
  const { t } = useTranslation("timeline");
  const count = frames.length;

  // The trend is drawn in the track's own coordinate space, 0..100 wide, so
  // the SVG scales with the container without a resize observer.
  const trendPath = useMemo(() => {
    if (count < 2 || trend.length < 2) return null;
    const position = new Map(frames.map((f, i) => [f, i]));
    const points = trend
      .map((p) => ({ i: position.get(p.day), value: p.value }))
      .filter((p): p is { i: number; value: number } => p.i !== undefined);
    if (points.length < 2) return null;
    const values = points.map((p) => p.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    // A flat series would divide by zero and, worse, would draw a line at
    // the top of the band as if it were a high reading. Centre it instead.
    const span = max - min;
    const y = (v: number): number =>
      span === 0 ? TREND_TOP + TREND_HEIGHT / 2 : TREND_TOP + (1 - (v - min) / span) * TREND_HEIGHT;
    return points
      .map((p, n) => `${n === 0 ? "M" : "L"}${(p.i / (count - 1)) * 100},${y(p.value)}`)
      .join(" ");
  }, [trend, frames, count]);

  const current = frames[index] ?? null;
  const currentDay = current ? days.get(current) : undefined;

  if (count === 0) {
    return (
      <Card className="px-4 py-3 text-sm text-ap-muted" noPadding>
        {t("scrubber.noWindow")}
      </Card>
    );
  }

  return (
    <Card className="px-3 py-2" noPadding>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onTogglePlay}
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-ap-line text-ap-ink hover:bg-ap-bg"
          aria-label={playing ? t("scrubber.pause") : t("scrubber.play")}
        >
          {playing ? <PauseGlyph /> : <PlayGlyph />}
        </button>

        <div className="relative min-w-0 flex-1" style={{ height: TRACK_HEIGHT }}>
          <svg
            className="pointer-events-none absolute inset-0 h-full w-full"
            viewBox={`0 0 100 ${TRACK_HEIGHT}`}
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            {/* Index trend. Vector-effect keeps the stroke 1px wide even
                though the viewBox is stretched horizontally — without it a
                90-day window draws a hairline and a 7-day one draws a slab. */}
            {trendPath ? (
              <path
                d={trendPath}
                fill="none"
                stroke="#4f8e4a"
                strokeWidth={1.5}
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
            {/* Acquisition days: a faint upright, so a reader can tell a
                frame that has its own image from one carrying an older
                pass forward. */}
            {frames.map((f, i) =>
              passDays.has(f) ? (
                <line
                  key={`p-${f}`}
                  x1={(i / Math.max(count - 1, 1)) * 100}
                  x2={(i / Math.max(count - 1, 1)) * 100}
                  y1={TREND_TOP}
                  y2={TREND_TOP + TREND_HEIGHT}
                  stroke="#e8e5db"
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                />
              ) : null,
            )}
            {/* Event ticks. */}
            {frames.map((f, i) => {
              const d = days.get(f);
              if (!d) return null;
              return (
                <circle
                  key={`t-${f}`}
                  cx={(i / Math.max(count - 1, 1)) * 100}
                  cy={TICK_TOP + 4}
                  r={3}
                  fill={dayTone(d)}
                  // A circle in a stretched viewBox becomes an ellipse.
                  // Counter-scaling per tick is not expressible, so the
                  // marks are drawn as small as they can be and read as
                  // dashes on a wide window, which is honest enough.
                  vectorEffect="non-scaling-stroke"
                />
              );
            })}
            {/* Play head. */}
            <line
              x1={(index / Math.max(count - 1, 1)) * 100}
              x2={(index / Math.max(count - 1, 1)) * 100}
              y1={0}
              y2={TRACK_HEIGHT}
              stroke="#1f2420"
              strokeWidth={2}
              vectorEffect="non-scaling-stroke"
            />
          </svg>

          {/* The real control. Transparent track, so the SVG behind it is
              what the reader sees, and a visible thumb so the grab target
              is obvious. */}
          <input
            type="range"
            min={0}
            max={count - 1}
            step={1}
            value={index}
            onChange={(e) => onIndexChange(Number(e.target.value))}
            className="absolute inset-x-0 bottom-0 w-full cursor-pointer appearance-none bg-transparent"
            aria-label={t("scrubber.dayAria")}
            aria-valuetext={current ? formatDay(current) : undefined}
          />
        </div>

        <div className="w-40 shrink-0 text-right">
          <div className="text-sm font-medium text-ap-ink">
            {current ? formatDay(current) : "—"}
          </div>
          <div className="text-xs text-ap-muted">
            {currentDay
              ? t("scrubber.eventCount", { count: currentDay.total })
              : t("scrubber.noEvents")}
          </div>
        </div>

        <label className="shrink-0 text-xs text-ap-muted">
          <span className="sr-only">{t("scrubber.speed")}</span>
          <select
            value={speed}
            onChange={(e) => onSpeedChange(Number(e.target.value))}
            className="rounded border border-ap-line bg-ap-panel px-1.5 py-1 text-xs text-ap-ink"
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s}x
              </option>
            ))}
          </select>
        </label>
      </div>
    </Card>
  );
}

function PlayGlyph(): ReactNode {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseGlyph(): ReactNode {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M6 5h4v14H6zm8 0h4v14h-4z" />
    </svg>
  );
}
