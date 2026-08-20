import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActionGuidance, ActionHorizon, TreePathStep } from "@/api/actionCenter";
import { Pill } from "@/components/Pill";

// Order matters and is not alphabetical: it is how soon the work is meant to
// happen. Rendering `long_term` above `immediate` would invert the advice.
const HORIZONS: readonly ActionHorizon[] = ["immediate", "short_term", "long_term", "monitoring"];

/**
 * The guidance a decision-tree leaf authored, by time horizon.
 *
 * Renders nothing when the leaf carried only a one-line summary, which is the
 * common case for older trees and for every alert.
 */
export function GuidanceList({
  actions,
  isAr,
}: {
  actions: Partial<Record<ActionHorizon, ActionGuidance[]>>;
  isAr: boolean;
}): ReactNode {
  const { t } = useTranslation("actionCenter");
  const present = HORIZONS.filter((h) => (actions[h]?.length ?? 0) > 0);
  if (present.length === 0) return null;
  return (
    <dl className="mt-2 flex flex-col gap-2 rounded-md border border-ap-line bg-ap-bg/40 p-3 text-meta">
      {present.map((horizon) => (
        <div key={horizon}>
          <dt className="font-semibold text-ap-ink">{t(`actionHorizon.${horizon}`)}</dt>
          <dd>
            <ul className="ms-3 list-disc text-ap-muted">
              {(actions[horizon] ?? []).map((line, i) => (
                <li key={i}>{isAr ? (line.text_ar ?? line.text_en) : line.text_en}</li>
              ))}
            </ul>
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Every step of the walk that produced a recommendation.
 *
 * The one-line "why" above this names the deciding condition. This is the rest
 * of it: which branches were tested, which way each went, and the numbers each
 * was compared against. It is what a user checks the finding against when they
 * disagree with it.
 */
export function TreePathList({ path, isAr }: { path: TreePathStep[]; isAr: boolean }): ReactNode {
  const { t } = useTranslation("actionCenter");
  if (path.length === 0) return null;
  return (
    <>
      <h4 className="mb-1.5 mt-2.5 text-meta font-bold uppercase tracking-wide text-ap-muted">
        {t("path.title")}
      </h4>
      <ol className="flex flex-col gap-1 rounded-md border border-ap-line bg-ap-bg/40 p-3 text-meta">
        {path.map((step, i) => {
          const label = (isAr ? (step.label_ar ?? step.label_en) : step.label_en) ?? null;
          const values = Object.entries(step.values);
          return (
            <li key={`${step.node_id}-${i}`} className="flex items-start gap-2">
              <span className="mt-0.5 flex-none text-ap-muted">{i + 1}.</span>
              <div className="flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-mono text-ap-ink">{step.node_id}</span>
                  {/* null is the leaf — the walk stopped here. Showing that as
                      "no match" reads as a failure, which is the opposite of
                      what a leaf means. */}
                  {step.matched === true ? (
                    <Pill kind="ok">{t("path.match")}</Pill>
                  ) : step.matched === false ? (
                    <Pill kind="neutral">{t("path.noMatch")}</Pill>
                  ) : (
                    <Pill kind="info">{t("path.leaf")}</Pill>
                  )}
                  {label === null ? null : <span className="text-ap-muted">— {label}</span>}
                </div>
                {values.length === 0 ? null : (
                  <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-ap-muted">
                    {values.map(([key, value]) => (
                      <span key={key}>
                        <span className="font-mono">{key}</span>={" "}
                        <span className="font-mono text-ap-ink">{String(value)}</span>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </>
  );
}
