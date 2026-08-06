import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { PixelExplain } from "@/api/observer";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";

/**
 * "Explain this pixel" — bands in, mask verdict, formula, value out.
 *
 * Everything rendered here is transmitted by the backend, including the
 * formula text (which comes from `indices_catalog`) and the substituted
 * expression. Nothing about the calculation is reconstructed client-side,
 * because a second implementation of the maths is a second thing that can
 * disagree with the pipeline.
 */

function fmt(v: number | null | undefined, digits = 4): string {
  return v === null || v === undefined ? "—" : v.toFixed(digits);
}

export function PixelInspector({
  data,
  isPending,
  error,
  selectedIndex,
}: {
  data: PixelExplain | undefined;
  isPending: boolean;
  error: unknown;
  selectedIndex: string;
}): ReactNode {
  const { t } = useTranslation("admin");

  if (error) {
    return (
      <Card title={t("observer.pixel.title")}>
        <p className="text-sm text-ap-crit">{t("observer.pixel.error")}</p>
      </Card>
    );
  }
  if (isPending && !data) return <Skeleton className="h-72 w-full" />;
  if (!data) {
    return (
      <Card title={t("observer.pixel.title")}>
        <EmptyState message={t("observer.pixel.clickPrompt")} />
      </Card>
    );
  }

  const index = data.indices[selectedIndex];
  const unavailable = data.unavailable_indices[selectedIndex];

  return (
    <Card
      title={t("observer.pixel.title")}
      actions={
        <Pill kind="info">{t("observer.pixel.coords", { row: data.row, col: data.col })}</Pill>
      }
    >
      <div className="space-y-4 text-sm">
        <section>
          <p className="mb-1 text-[0.6875rem] font-semibold uppercase tracking-wide text-ap-muted">
            {t("observer.pixel.bands")}
          </p>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-0.5 font-mono text-xs sm:grid-cols-3">
            {Object.entries(data.band_values).map(([band, value]) => (
              <div key={band} className="flex justify-between gap-2">
                <dt className="text-ap-muted">{band}</dt>
                <dd className="font-semibold tabular-nums">{fmt(value)}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section>
          <p className="mb-1 text-[0.6875rem] font-semibold uppercase tracking-wide text-ap-muted">
            {t("observer.pixel.masking")}
          </p>
          {data.masking_available ? (
            <p className="text-xs">
              SCL = <strong>{data.scl_value}</strong> ({data.scl_label}) →{" "}
              {data.masked ? (
                <span className="font-semibold text-ap-crit">{t("observer.pixel.masked")}</span>
              ) : (
                <span className="font-semibold text-ap-primary">
                  {t("observer.pixel.notMasked")}
                </span>
              )}
            </p>
          ) : (
            /*
             * No SCL band means no cloud masking ran at all, which makes this
             * scene's valid-pixel share incomparable to one from a product
             * that does mask. Saying "n/a" is the honest answer; showing
             * "not masked" would imply a decision nobody made.
             */
            <p className="text-xs text-ap-muted">{t("observer.pixel.noMaskBand")}</p>
          )}
          <p className="mt-1 text-xs">
            {data.inside_aoi ? t("observer.pixel.insideAoi") : t("observer.pixel.outsideAoi")}
          </p>
        </section>

        <section>
          <p className="mb-1 text-[0.6875rem] font-semibold uppercase tracking-wide text-ap-muted">
            {t("observer.pixel.formula", { index: selectedIndex.toUpperCase() })}
          </p>
          {unavailable ? (
            <p className="text-xs text-ap-muted">
              {t("observer.pixel.unavailable", { reason: unavailable })}
            </p>
          ) : index ? (
            <pre className="whitespace-pre-wrap rounded bg-ap-bg/60 p-3 font-mono text-xs leading-relaxed">
              {index.formula_text}
              {index.substituted ? `\n= ${index.substituted}` : ""}
              {index.raw_value !== null ? `\n= ${fmt(index.raw_value)}` : ""}
            </pre>
          ) : null}

          {index?.excluded_reason ? (
            <p className="mt-2 border-s-2 border-ap-warn ps-3 text-xs">
              {t("observer.pixel.excluded", { reason: index.excluded_reason })}
            </p>
          ) : index ? (
            <p className="mt-2 text-xs text-ap-muted">{t("observer.pixel.contributes")}</p>
          ) : null}
        </section>
      </div>
    </Card>
  );
}
