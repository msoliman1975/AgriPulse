import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { HistogramBucket, HistogramBucketSize } from "@/api/observer";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { SegmentedControl } from "@/components/SegmentedControl";

/**
 * Scene counts per time bucket, stacked by outcome.
 *
 * `computed` and `acquiredOnly` are separate segments on purpose. A job
 * whose download succeeded and whose index computation died still reads
 * `succeeded` in `imagery_ingestion_jobs`, so a histogram keyed on job
 * status alone would paint that scene green — which is how a dead compute
 * task went unnoticed for a week.
 */

// Enough room for a "Jun 14"-style label under every bar. Below this the
// axis has to start dropping dates, which is what made a daily window
// unreadable.
const MIN_BUCKET_PX = 34;

const SEGMENTS = [
  { key: "computed", cls: "bg-ap-primary" },
  { key: "acquired_only", cls: "bg-ap-accent" },
  { key: "skipped", cls: "bg-ap-warn" },
  { key: "failed", cls: "bg-ap-crit" },
  { key: "pending", cls: "bg-ap-line" },
] as const;

function labelFor(iso: string, bucket: HistogramBucketSize, locale: string): string {
  const d = new Date(iso);
  if (bucket === "month") {
    return d.toLocaleDateString(locale, { month: "short", year: "2-digit" });
  }
  return d.toLocaleDateString(locale, { month: "short", day: "numeric" });
}

export function SceneHistogram({
  buckets,
  bucket,
  onBucketChange,
  isLoading,
}: {
  buckets: HistogramBucket[];
  bucket: HistogramBucketSize;
  onBucketChange: (b: HistogramBucketSize) => void;
  isLoading: boolean;
}): ReactNode {
  const { t, i18n } = useTranslation("admin");
  const max = Math.max(1, ...buckets.map((b) => b.total));

  return (
    <Card
      title={t("observer.histogram.title")}
      actions={
        <SegmentedControl
          ariaLabel={t("observer.histogram.bucketLabel")}
          value={bucket}
          onChange={onBucketChange}
          items={[
            { value: "day", label: t("observer.histogram.day") },
            { value: "week", label: t("observer.histogram.week") },
            { value: "month", label: t("observer.histogram.month") },
          ]}
        />
      }
    >
      {!isLoading && buckets.length === 0 ? (
        <EmptyState message={t("observer.histogram.empty")} />
      ) : (
        <>
          {/*
            Every bucket gets its own label. The old ribbon thinned them to
            roughly eight across the whole axis, so a 53-day window showed a
            date about once a week and a reader could not tell which bar was
            which day. Bars now carry a minimum width and the chart scrolls
            inside its own container rather than compressing to fit — the
            axis stays readable at any window length.
          */}
          <div className="overflow-x-auto pb-1">
            <div style={{ minWidth: `${buckets.length * MIN_BUCKET_PX}px` }}>
              <div
                className="flex h-40 items-end gap-[3px]"
                role="img"
                aria-label={t("observer.histogram.title")}
              >
                {buckets.map((b) => (
                  <div
                    key={b.bucket}
                    className="flex flex-1 flex-col justify-end gap-px"
                    style={{ minWidth: `${MIN_BUCKET_PX - 3}px` }}
                    title={`${labelFor(b.bucket, bucket, i18n.language)} — ${SEGMENTS.filter(
                      (s) => b[s.key] > 0,
                    )
                      .map((s) => `${t(`observer.histogram.legend.${s.key}`)}: ${b[s.key]}`)
                      .join(" · ")}`}
                  >
                    {SEGMENTS.map((s) => {
                      const n = b[s.key];
                      if (!n) return null;
                      return (
                        <div
                          key={s.key}
                          className={clsx("rounded-t-sm", s.cls)}
                          style={{ height: `${(n / max) * 140}px` }}
                        />
                      );
                    })}
                  </div>
                ))}
              </div>
              <div className="mt-1 flex gap-[3px] border-t border-ap-line pt-1">
                {buckets.map((b) => (
                  <span
                    key={b.bucket}
                    className="flex-1 text-center text-[0.625rem] leading-tight text-ap-muted"
                    style={{ minWidth: `${MIN_BUCKET_PX - 3}px` }}
                  >
                    {labelFor(b.bucket, bucket, i18n.language)}
                  </span>
                ))}
              </div>
            </div>
          </div>
          {/*
            The legend named five outcomes and explained none of them.
            "Acquired, no aggregates" in particular is the single most
            important bar on this chart — it is a scene that downloaded and
            then failed silently — and the label alone does not say that.
          */}
          <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 text-xs sm:grid-cols-2">
            {SEGMENTS.map((s) => (
              <div key={s.key} className="flex items-baseline gap-1.5">
                <span
                  className={clsx("mt-1 inline-block h-2.5 w-2.5 shrink-0 rounded-sm", s.cls)}
                />
                <dt className="shrink-0 font-medium text-ap-ink">
                  {t(`observer.histogram.legend.${s.key}`)}
                </dt>
                <dd className="text-ap-muted">{t(`observer.histogram.legendWhat.${s.key}`)}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
    </Card>
  );
}
