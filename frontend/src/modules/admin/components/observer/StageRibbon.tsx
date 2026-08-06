import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ObserverOverview, ObserverStage, StageVerdict } from "@/api/observer";
import { Card } from "@/components/Card";
import { Pill } from "@/components/Pill";

/**
 * The pipeline stage ribbon.
 *
 * The verdicts are computed server-side, next to the SQL that produced the
 * denominators — deciding that "402 of 402 cell aggregates" is healthy while
 * "118 of 215 trend days" is not requires knowing which populations those
 * denominators measure, and a frontend that re-derived it would drift the
 * first time one changed. This component renders the judgement; it does not
 * make it.
 */

const TONE: Record<StageVerdict, string> = {
  ok: "bg-ap-primary-soft/50 border-ap-primary/30",
  warn: "bg-ap-warn-soft/50 border-ap-warn/30",
  bad: "bg-ap-crit-soft/50 border-ap-crit/30",
  info: "bg-ap-surface border-ap-line",
  not_applicable: "bg-ap-line/20 border-ap-line",
};

function StageCard({
  stage,
  onSelect,
  selected,
}: {
  stage: ObserverStage;
  onSelect?: () => void;
  selected: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const label = t(`observer.stage.${stage.key}`, { defaultValue: stage.label });

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={clsx(
        "min-w-[8.5rem] flex-1 border p-3 text-start transition first:rounded-s-md last:rounded-e-md",
        "-ms-px first:ms-0 hover:brightness-[0.98] focus:outline-none focus-visible:ring-2",
        "focus-visible:ring-ap-primary",
        TONE[stage.verdict],
        selected && "ring-2 ring-ap-primary ring-offset-1",
      )}
    >
      <div className="text-[0.6875rem] font-semibold uppercase tracking-wide text-ap-muted">
        {label}
      </div>
      <div className="mt-0.5 text-xl font-semibold tabular-nums">
        {stage.count.toLocaleString()}
      </div>
      <StageSubline stage={stage} />
    </button>
  );
}

function StageSubline({ stage }: { stage: ObserverStage }): ReactNode {
  const { t } = useTranslation("admin");

  // "0 of 0" is not a failure — it is a stage that was never going to
  // produce anything, and saying so is the whole reason the denominator is
  // computed from governing grid configs rather than from the scene count.
  if (stage.verdict === "not_applicable") {
    return (
      <div className="mt-0.5 text-[0.6875rem] text-ap-muted">{t("observer.notApplicable")}</div>
    );
  }
  if (stage.expected === null) {
    return null;
  }
  const pct = stage.expected > 0 ? Math.round((stage.count / stage.expected) * 100) : 100;
  return (
    <div className="mt-0.5 text-[0.6875rem] text-ap-muted">
      {t("observer.ofExpected", { pct, expected: stage.expected.toLocaleString() })}
      {stage.shortfall ? (
        <span className="ms-1 font-semibold text-ap-crit">−{stage.shortfall.toLocaleString()}</span>
      ) : null}
    </div>
  );
}

/** Plain-language reading of what a flagged stage means. */
function stageDiagnosis(stage: ObserverStage): string | null {
  if (stage.verdict !== "warn" && stage.verdict !== "bad") return null;
  return stage.key;
}

export function StageRibbon({
  overview,
  selectedStage,
  onSelectStage,
}: {
  overview: ObserverOverview;
  selectedStage: string | null;
  onSelectStage: (key: string | null) => void;
}): ReactNode {
  const { t } = useTranslation("admin");
  const flagged = overview.stages.filter((s) => stageDiagnosis(s) !== null);

  return (
    <Card
      title={t("observer.ribbon.title")}
      actions={
        <span className="text-xs text-ap-muted">
          {t("observer.ribbon.blocks", { count: overview.block_count })}
        </span>
      }
    >
      <div className="flex overflow-x-auto pb-1">
        {overview.stages.map((stage) => (
          <StageCard
            key={stage.key}
            stage={stage}
            selected={selectedStage === stage.key}
            onSelect={() => onSelectStage(selectedStage === stage.key ? null : stage.key)}
          />
        ))}
      </div>

      <div className="mt-3 space-y-2">
        {flagged.map((stage) => (
          <p
            key={stage.key}
            className={clsx(
              "border-s-2 ps-3 text-xs",
              stage.verdict === "bad" ? "border-ap-crit text-ap-ink" : "border-ap-warn text-ap-ink",
            )}
          >
            {t(`observer.diagnosis.${stage.key}`, {
              defaultValue: t("observer.diagnosis.generic"),
              count: stage.shortfall ?? 0,
              expected: stage.expected ?? 0,
            })}
          </p>
        ))}

        {overview.trend_product_ambiguous ? (
          <p className="border-s-2 border-ap-accent ps-3 text-xs text-ap-muted">
            {t("observer.trendAmbiguous")}
          </p>
        ) : null}

        {overview.consumers_are_window_proxy ? (
          <p className="text-[0.6875rem] text-ap-muted">{t("observer.consumersProxy")}</p>
        ) : null}

        {overview.calc_versions.length > 1 ? (
          <p className="border-s-2 border-ap-warn ps-3 text-xs">
            <Pill kind="warn">{t("observer.mixedCalcVersions")}</Pill>
          </p>
        ) : null}
      </div>
    </Card>
  );
}
