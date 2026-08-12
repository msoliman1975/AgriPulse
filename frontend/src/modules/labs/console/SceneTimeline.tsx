// The scene strip — time as an axis, not a filter.
//
// Real acquisition days, newest last, with the cloudy ones still on the strip
// rather than quietly missing: a gap the reader can see and understand
// ("74% cloud") is worth far more than a shorter timeline that looks like
// data loss. Selecting a day moves the map, the grid and the legend together.
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

  const fmtDay = useMemo(
    () => new Intl.DateTimeFormat(i18n.language, { day: "2-digit", month: "short" }),
    [i18n.language],
  );
  const fmtFull = useMemo(
    () => new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" }),
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
              return (
                <button
                  key={s.scene_date}
                  ref={selected ? selectedRef : undefined}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => onSelect(selected ? null : s.scene_date)}
                  title={
                    cloudy
                      ? t("timeline.cloudyOn", {
                          date: fmtFull.format(new Date(`${s.scene_date}T00:00:00Z`)),
                          pct: pct ?? "—",
                        })
                      : t("timeline.passOn", {
                          date: fmtFull.format(new Date(`${s.scene_date}T00:00:00Z`)),
                          count: s.succeeded_count,
                        })
                  }
                  className={
                    "flex-none rounded-md border px-1.5 py-1 text-center transition-colors " +
                    (selected
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
                  <span className="mt-0.5 block text-[10px] leading-none text-ap-muted">
                    {cloudy ? `☁ ${pct ?? "—"}%` : `${s.succeeded_count}`}
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
