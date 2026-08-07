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
          <div
            className="flex h-40 items-end gap-[3px]"
            role="img"
            aria-label={t("observer.histogram.title")}
          >
            {buckets.map((b) => (
              <div
                key={b.bucket}
                className="flex min-w-[6px] flex-1 flex-col justify-end gap-px"
                title={SEGMENTS.filter((s) => b[s.key] > 0)
                  .map((s) => `${t(`observer.histogram.legend.${s.key}`)}: ${b[s.key]}`)
                  .join(" · ")}
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
            {buckets.map((b, i) => (
              <span
                key={b.bucket}
                className="min-w-[6px] flex-1 text-center text-[0.625rem] text-ap-muted"
              >
                {i % Math.ceil(buckets.length / 8 || 1) === 0
                  ? labelFor(b.bucket, bucket, i18n.language)
                  : ""}
              </span>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ap-muted">
            {SEGMENTS.map((s) => (
              <span key={s.key} className="inline-flex items-center gap-1.5">
                <span className={clsx("inline-block h-2.5 w-2.5 rounded-sm", s.cls)} />
                {t(`observer.histogram.legend.${s.key}`)}
              </span>
            ))}
          </div>
        </>
      )}
    </Card>
  );
}
