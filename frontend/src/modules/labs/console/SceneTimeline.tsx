// The scene strip — time as an axis, not a filter.
//
// Real acquisition days, newest last, with the cloudy ones still on the strip
// rather than quietly missing: a gap the reader can see and understand
// ("74% cloud") is worth far more than a shorter timeline that looks like
// data loss. Selecting a day moves the map, the grid and the legend together.
//
// Cloud is reported on two kinds of day, not one. A pass skipped ENTIRELY for
// cloud draws nothing and is struck through. A pass that succeeded under
// PARTIAL cloud draws most of the farm and leaves holes where the mask took
// the pixels, so it carries the same figure without the strike-through.
// Reporting only the first left the second looking like a rendering fault.
//
// The trailing "next pass" is an EXPECTATION derived from this farm's own
// recent cadence, never a promise — cloud decides whether a pass is usable,
// and the copy says so.
import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { FarmScene } from "@/api/imagery";

interface Props {
  scenes: readonly FarmScene[];
  selectedDate: string | null;
  onSelect: (sceneDate: string | null) => void;
  medianGapDays: number | null;
  loading: boolean;
  /** False when the API predates the farm-scenes route. */
  available: boolean;
}

/** A pass is "cloudy" when every block that tried was skipped for cloud. */
function isCloudy(s: FarmScene): boolean {
  return s.succeeded_count === 0 && s.skipped_cloud_count > 0;
}

function noReadingPct(s: FarmScene): number | null {
  if (s.no_reading_pct == null) return null;
  const n = Number(s.no_reading_pct);
  return Number.isFinite(n) ? Math.round(n) : null;
}

// Every farm loses a little of every pass. The index mask is cut at the farm
// boundary, so the edge pixels never carry a value and `no_reading_pct` sits
// at a small constant on a perfectly clear day — 2% on Green Farm [Demo-01],
// higher on a farm of many small blocks, and there is no one number that is
// right for all of them.
//
// So the floor is read off the farm's own history rather than hardcoded: the
// quietest pass in the strip is what this farm looks like with no weather in
// the way, and a day is worth flagging when it loses this much MORE than that.
const LOSS_OVER_FLOOR_PCT = 3;

// ...unless the loss is large on its own. Without this, a strip where every
// pass is cloudy has a high floor and flags nothing at all.
const LOSS_ALWAYS_FLAG_PCT = 15;

/** The farm's structural loss: the quietest pass on the strip. */
function lossFloor(scenes: readonly FarmScene[]): number | null {
  const vals = scenes.map(noReadingPct).filter((v): v is number => v !== null);
  return vals.length > 0 ? Math.min(...vals) : null;
}

function cloudPct(s: FarmScene): number | null {
  if (s.cloud_cover_pct == null) return null;
  const n = Number(s.cloud_cover_pct);
  return Number.isFinite(n) ? Math.round(n) : null;
}

export function SceneTimeline({
  scenes,
  selectedDate,
  onSelect,
  medianGapDays,
  loading,
  available,
}: Props): ReactNode {
  const { t, i18n } = useTranslation("farmConsole");
  const scrollRef = useRef<HTMLDivElement>(null);
  const selectedRef = useRef<HTMLButtonElement>(null);

  // Oldest first, so the strip reads left-to-right as time moves forward
  // (and right-to-left under RTL, which the browser handles for us).
  const ordered = useMemo(() => [...scenes].reverse(), [scenes]);
  const floor = useMemo(() => lossFloor(scenes), [scenes]);

  // Formatted in UTC, deliberately. `scene_date` is a DATE, not an instant —
  // the day the satellite passed over, which the api derives as
  // `(scene_datetime AT TIME ZONE 'UTC')::date`. Reading it back through the
  // viewer's timezone turns midnight UTC into the evening before for anyone
  // west of Greenwich, and the whole strip slides a day: a user on a
  // negative-offset clock read the 15 Aug pass as "14 Aug" and reasonably
  // concluded the console was showing them the wrong scene. An acquisition
  // day is the same day in Cairo and in Honolulu.
  const fmtDay = useMemo(
    () =>
      new Intl.DateTimeFormat(i18n.language, {
        day: "2-digit",
        month: "short",
        timeZone: "UTC",
      }),
    [i18n.language],
  );
  const fmtFull = useMemo(
    () => new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium", timeZone: "UTC" }),
    [i18n.language],
  );

  // Centre the selection. `scrollIntoView` rather than arithmetic on
  // scrollLeft, which is negative in some engines under RTL.
  //
  // Feature-detected: jsdom does not implement it, and neither do some
  // embedded webviews. Centring is a nicety — throwing here would take the
  // whole console down with it.
  useEffect(() => {
    const el = selectedRef.current;
    if (typeof el?.scrollIntoView === "function") {
      el.scrollIntoView({ inline: "center", block: "nearest" });
    }
  }, [selectedDate, ordered.length]);

  const nextPass = useMemo(() => {
    if (!medianGapDays || ordered.length === 0) return null;
    const last = ordered[ordered.length - 1];
    const d = new Date(`${last.scene_date}T00:00:00Z`);
    if (Number.isNaN(d.getTime())) return null;
    d.setUTCDate(d.getUTCDate() + Math.round(medianGapDays));
    return d;
  }, [medianGapDays, ordered]);

  // Nothing to show is not the same as nothing to say.
  if (!available || (!loading && ordered.length === 0)) {
    return (
      <div className="flex h-[46px] flex-none items-center gap-2 border-t border-ap-line bg-ap-panel px-3">
        <span className="text-meta text-ap-muted">
          {available ? t("timeline.empty") : t("timeline.unavailable")}
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-none items-stretch border-t border-ap-line bg-ap-panel">
      <div
        ref={scrollRef}
        role="listbox"
        aria-label={t("timeline.label")}
        className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto px-2 py-1.5"
      >
        {loading && ordered.length === 0
          ? Array.from({ length: 10 }, (_, i) => (
              <div
                key={i}
                className="h-[38px] w-[58px] flex-none animate-pulse rounded-md bg-ap-line/50"
              />
            ))
          : ordered.map((s) => {
              const selected = s.scene_date === selectedDate;
              const cloudy = isCloudy(s);
              const pct = cloudPct(s);
              // Ingested but never processed: the raw scene was fetched and
              // the jobs read "succeeded", but no index raster was ever
              // computed, so picking this pass draws nothing. Older api
              // versions omit the field — treat unknown as processed rather
              // than greying out a whole timeline on a stale deploy.
              // Cloud is the more specific explanation and keeps its own
              // treatment: a reader who sees "☁ 91%" knows both that there is
              // nothing to draw and why, where a grey dash would lose the why.
              const unprocessed = s.computed_count === 0 && !cloudy;
              // A pass that succeeded can still carry cloud over PART of the
              // farm. The mask drops those pixels, so the cells above them
              // draw as "no reading" while the rest of the map paints
              // normally — and until now the strip said nothing about it. On
              // Green Farm [Demo-01] the 2026-08-18 pass left 84 of
              // AG-R02-C02's 224 cells with no value, which reads as a broken
              // map rather than as weather.
              //
              // Measured with `no_reading_pct`, NOT with the chip's other
              // figure `cloud_cover_pct`. That one describes the whole
              // satellite tile: on this farm it calls 2026-08-17 the cloudier
              // of the two days (13.24% against 6.50%) when 08-17 lost 2.04%
              // of the farm and 08-18 lost 8.17%. It ranks them backwards.
              const loss = noReadingPct(s);
              const partlyCloudy =
                !cloudy &&
                !unprocessed &&
                loss !== null &&
                (loss >= LOSS_ALWAYS_FLAG_PCT ||
                  (floor !== null && loss - floor >= LOSS_OVER_FLOOR_PCT));
              return (
                <button
                  key={s.scene_date}
                  ref={selected ? selectedRef : undefined}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => onSelect(selected ? null : s.scene_date)}
                  disabled={unprocessed}
                  title={
                    cloudy
                      ? t("timeline.cloudyOn", {
                          date: fmtFull.format(new Date(`${s.scene_date}T00:00:00Z`)),
                          pct: pct ?? "—",
                        })
                      : unprocessed
                        ? t("timeline.unprocessedOn", {
                            date: fmtFull.format(new Date(`${s.scene_date}T00:00:00Z`)),
                          })
                        : partlyCloudy
                          ? t("timeline.partlyCloudyOn", {
                              date: fmtFull.format(new Date(`${s.scene_date}T00:00:00Z`)),
                              count: s.succeeded_count,
                              pct: loss ?? "—",
                            })
                          : t("timeline.passOn", {
                              date: fmtFull.format(new Date(`${s.scene_date}T00:00:00Z`)),
                              count: s.succeeded_count,
                            })
                  }
                  data-unprocessed={unprocessed || undefined}
                  className={
                    "flex-none rounded-md border px-1.5 py-1 text-center transition-colors " +
                    (unprocessed
                      ? "cursor-not-allowed border-transparent opacity-40"
                      : selected
                        ? "border-ap-primary bg-ap-primary-soft"
                        : "border-transparent hover:bg-ap-bg")
                  }
                >
                  <span
                    className={
                      "block whitespace-nowrap text-meta font-semibold tabular-nums " +
                      (cloudy
                        ? "text-ap-muted/60 line-through"
                        : selected
                          ? "text-ap-primary"
                          : "text-ap-ink")
                    }
                  >
                    {fmtDay.format(new Date(`${s.scene_date}T00:00:00Z`))}
                  </span>
                  <span
                    className={
                      "mt-0.5 block text-[10px] leading-none " +
                      (partlyCloudy ? "text-ap-warn" : "text-ap-muted")
                    }
                  >
                    {cloudy
                      ? `☁ ${pct ?? "—"}%`
                      : partlyCloudy
                        ? `☁ ${loss ?? "—"}%`
                        : unprocessed
                          ? "—"
                          : `${s.succeeded_count}`}
                  </span>
                </button>
              );
            })}
      </div>

      {nextPass ? (
        <div className="flex flex-none flex-col justify-center border-s border-ap-line bg-ap-bg px-3 py-1">
          <span className="whitespace-nowrap text-[10px] font-bold uppercase tracking-wide text-ap-muted">
            {t("timeline.nextPass")}
          </span>
          <span
            className="whitespace-nowrap text-meta font-bold tabular-nums text-ap-ink"
            title={t("timeline.nextPassHint")}
          >
            ≈ {fmtFull.format(nextPass)}
          </span>
        </div>
      ) : null}
    </div>
  );
}
