import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  ObserverOverview,
  ObserverStage,
  ProblemScene,
  SceneProblem,
  StageVerdict,
} from "@/api/observer";
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
 *
 * Selecting a tile opens what that stage actually counts. The numbers are
 * meaningless without it: "Acquired 21" reads as a score until you know the
 * denominator is discovered-minus-skipped, and nothing on the screen said so.
 */

const TONE: Record<StageVerdict, string> = {
  ok: "bg-ap-primary-soft/50 border-ap-primary/30",
  warn: "bg-ap-warn-soft/50 border-ap-warn/30",
  bad: "bg-ap-crit-soft/50 border-ap-crit/30",
  info: "bg-ap-surface border-ap-line",
  not_applicable: "bg-ap-line/20 border-ap-line",
};

/** Which stage each kind of problem belongs under. */
const PROBLEM_STAGE: Record<SceneProblem, string> = {
  failed: "acquired",
  in_flight: "acquired",
  skipped: "discovered",
  no_aggregates: "indices",
};

const PROBLEM_TONE: Record<SceneProblem, "crit" | "warn" | "info" | "neutral"> = {
  failed: "crit",
  in_flight: "info",
  skipped: "neutral",
  no_aggregates: "warn",
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
      title={t(`observer.stageWhat.${stage.key}`, { defaultValue: "" })}
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

/**
 * What the selected stage counts, in words, plus the rows behind any
 * shortfall.
 *
 * The rows matter more than the sentence. The old ribbon said "2 scenes were
 * discovered but never downloaded — check the provider errors in the scene
 * list", and on the farm that prompted this there were no provider errors:
 * both scenes were still `running`, requested hours earlier and stuck. A
 * diagnosis that names the wrong cause is worse than one that names none.
 */
function StageDetail({
  stage,
  problems,
}: {
  stage: ObserverStage;
  problems: ProblemScene[];
}): ReactNode {
  const { t, i18n } = useTranslation("admin");
  const mine = problems.filter((p) => PROBLEM_STAGE[p.problem] === stage.key);

  return (
    <div className="mt-3 rounded-md border border-ap-line bg-ap-bg/40 p-3">
      <p className="text-xs font-semibold text-ap-ink">
        {t(`observer.stage.${stage.key}`, { defaultValue: stage.label })}
      </p>
      <p className="mt-1 text-xs text-ap-muted">
        {t(`observer.stageWhat.${stage.key}`, {
          defaultValue: t("observer.stageWhat.generic"),
        })}
      </p>
      {stage.expected !== null ? (
        <p className="mt-1 text-xs text-ap-muted">
          {t(`observer.stageDenominator.${stage.key}`, { defaultValue: "" })}
        </p>
      ) : (
        <p className="mt-1 text-xs text-ap-muted">{t("observer.noDenominator")}</p>
      )}

      {mine.length > 0 ? (
        <div className="mt-3">
          <p className="mb-1 text-[0.6875rem] font-semibold uppercase tracking-wide text-ap-muted">
            {t("observer.problems.title", { count: mine.length })}
          </p>
          <ul className="divide-y divide-ap-line text-xs">
            {mine.map((p) => (
              <li key={p.job_id} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-1.5">
                <Pill kind={PROBLEM_TONE[p.problem]}>{t(`observer.problems.${p.problem}`)}</Pill>
                <span className="tabular-nums text-ap-muted">
                  {new Date(p.scene_datetime).toLocaleDateString(i18n.language, {
                    dateStyle: "medium",
                  })}
                </span>
                <span className="font-mono text-[0.6875rem] text-ap-ink">{p.scene_id}</span>
                {p.label ? <span className="text-ap-muted">· {p.label}</span> : null}
                {/* The cause, inline. This is the whole point of the panel. */}
                {p.error_code ? (
                  <span className="font-mono text-ap-crit">{p.error_code}</span>
                ) : (
                  <span className="text-ap-muted">
                    {t(`observer.problems.noError.${p.problem}`, { defaultValue: "" })}
                  </span>
                )}
                {p.error_message ? (
                  <span className="w-full break-words text-[0.6875rem] text-ap-muted">
                    {p.error_message}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
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
  const selected = overview.stages.find((s) => s.key === selectedStage) ?? null;
  const problems = overview.problems ?? [];
  const flagged = overview.stages.filter((s) => s.verdict === "warn" || s.verdict === "bad");

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

      <p className="mt-2 text-[0.6875rem] text-ap-muted">{t("observer.ribbon.hint")}</p>

      {/*
        A flagged stage keeps its warning ON SCREEN, not behind a click.
        Click-to-explain is for the stages that are fine and whose numbers
        still need defining; a stage that is actually short of output has to
        say so at a glance, or the ribbon stops being a monitor.
      */}
      {flagged.length > 0 ? (
        <div className="mt-3 space-y-2">
          {flagged.map((stage) => (
            <p
              key={stage.key}
              className={clsx(
                "border-s-2 ps-3 text-xs",
                stage.verdict === "bad"
                  ? "border-ap-crit text-ap-ink"
                  : "border-ap-warn text-ap-ink",
              )}
            >
              {t(`observer.diagnosis.${stage.key}`, {
                defaultValue: t("observer.diagnosis.generic"),
                count: stage.shortfall ?? 0,
                expected: stage.expected ?? 0,
              })}{" "}
              <button
                type="button"
                className="text-ap-accent underline"
                onClick={() => onSelectStage(selectedStage === stage.key ? null : stage.key)}
              >
                {t("observer.ribbon.showScenes")}
              </button>
            </p>
          ))}
        </div>
      ) : null}

      {selected ? <StageDetail stage={selected} problems={problems} /> : null}

      {overview.calc_versions.length > 1 ? (
        <p className="mt-3 border-s-2 border-ap-warn ps-3 text-xs">
          <Pill kind="warn">{t("observer.mixedCalcVersions")}</Pill>
        </p>
      ) : null}
    </Card>
  );
}
