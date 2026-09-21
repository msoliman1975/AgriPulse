/**
 * Why one cell got the result it got.
 *
 * Three parts, laid out as the two rows the design asks for:
 *
 *   * **Top left** — the tree, read only, with the walk drawn and every node
 *     it did not touch dimmed. Editing is off because no `onAddNode`,
 *     `onMoveNode` or `onResetLayout` is passed; panning and zoom stay on,
 *     because a 74-node tree does not fit on half a screen.
 *   * **Top right** — one box per step, in walk order, each headed by what
 *     the node did and expandable to the values behind it.
 *   * **Bottom** — what turned the finding set into the card: the combination
 *     rule that matched, or the clauses composition joined.
 *
 * The component takes a walk and a layout and fetches nothing. That is what
 * lets one screen serve both sources: a dry run's fresh walk and a real run's
 * stored `node_path` normalise into the same `WalkStep[]` in `walkTrace.ts`,
 * and neither one is named here.
 *
 * Selection is shared between the two halves. Clicking a step selects its
 * node on the canvas and clicking a node scrolls to its step, because a path
 * through 40 nodes is unreadable if the picture and the list disagree about
 * where you are.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { localizedField } from "@/lib/localizedField";
import type { BetaWalkClause, BetaWalkRule } from "@/api/decisionTreesBeta";

import { BetaCanvas } from "./BetaCanvas";
import type { BetaLayoutResult } from "../lib/betaLayout";
import {
  formatValue,
  registeredDetail,
  walkHighlight,
  writtenValues,
  type WalkStep,
} from "../lib/walkTrace";
import { useFindingStatusLabel } from "../lib/useStatusLabel";

export interface WalkExplainerProps {
  /** The walk, already normalised. Empty means the walk recorded no steps. */
  steps: WalkStep[];
  /** The tree to draw. Null when the definition could not be resolved; the
   *  step list still reads on its own. */
  layout: BetaLayoutResult | null;
  /** The rule that wrote the text, when one matched. */
  rule?: BetaWalkRule | null;
  /** The clauses composition joined, when it composed. */
  composedFrom?: BetaWalkClause[] | null;
  /** The card text as the fold wrote it. */
  textEn?: string | null;
  textAr?: string | null;
  /** The finding codes. Empty is a healthy cell, not a missing answer. */
  identity?: string[];
  /** The walk's own failure, when it had one. */
  error?: string | null;
}

export function WalkExplainer({
  steps,
  layout,
  rule = null,
  composedFrom = null,
  textEn = null,
  textAr = null,
  identity = [],
  error = null,
}: WalkExplainerProps): ReactNode {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const isAr = i18n.language === "ar";
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [showAllSteps, setShowAllSteps] = useState(false);
  const [canvasHeight, setCanvasHeight] = useState(420);

  const highlight = useMemo(() => walkHighlight(steps), [steps]);

  // A tree that writes six variables early gives six boxes that say nothing
  // an agronomist wants to read. They are still part of the walk, so they are
  // hidden rather than dropped, and the toggle says how many.
  const hiddenCount = steps.filter((s) => s.kind === "set").length;
  const shown = showAllSteps ? steps : steps.filter((s) => s.kind !== "set");

  return (
    <div className="flex flex-col gap-4">
      {error ? (
        <StatusBanner kind="crit">
          {t("explainer.walkFailed", {
            node: highlight.errorNodeId ?? t("explainer.noNode"),
          })}
          <span className="block font-mono text-meta">{error}</span>
        </StatusBanner>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(280px,2fr)]">
        <div className="flex min-w-0 flex-col gap-2">
          {layout === null ? (
            <StatusBanner kind="info">{t("explainer.noTree")}</StatusBanner>
          ) : (
            <BetaCanvas
              layout={layout}
              selectedNodeId={selectedNodeId}
              onSelectNode={setSelectedNodeId}
              pathNodeIds={highlight.nodes}
              pathEdgeKeys={highlight.edges}
              rejectedNodeIds={
                highlight.errorNodeId === null ? undefined : new Set([highlight.errorNodeId])
              }
              height={canvasHeight}
              onHeightChange={setCanvasHeight}
            />
          )}
          <p className="text-meta text-ap-muted">{t("explainer.canvasHint")}</p>
        </div>

        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="text-sm font-medium text-ap-ink">
              {t("explainer.stepsTitle", { count: steps.length })}
            </h3>
            {hiddenCount > 0 ? (
              <button
                type="button"
                onClick={() => setShowAllSteps((v) => !v)}
                className="text-meta text-ap-accent underline"
              >
                {showAllSteps
                  ? t("explainer.hideSetSteps")
                  : t("explainer.showSetSteps", { count: hiddenCount })}
              </button>
            ) : null}
          </div>
          <ol className="flex max-h-[32rem] flex-col gap-1.5 overflow-y-auto pe-1">
            {shown.map((step, index) => (
              <StepBox
                key={`${step.nodeId}-${index}`}
                step={step}
                position={steps.indexOf(step) + 1}
                selected={step.nodeId === selectedNodeId}
                onSelect={() => setSelectedNodeId(step.nodeId)}
              />
            ))}
          </ol>
          {steps.length === 0 ? (
            <p className="text-sm text-ap-muted">{t("explainer.noSteps")}</p>
          ) : null}
        </div>
      </div>

      <TextSource
        rule={rule}
        composedFrom={composedFrom}
        textEn={textEn}
        textAr={textAr}
        identity={identity}
        errored={error !== null}
        isAr={isAr}
      />
    </div>
  );
}

// ---- One step ---------------------------------------------------------

interface StepBoxProps {
  step: WalkStep;
  position: number;
  selected: boolean;
  onSelect: () => void;
}

function StepBox({ step, position, selected, onSelect }: StepBoxProps): ReactNode {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLLIElement | null>(null);

  // The canvas and the list share one selection, so a node clicked on the
  // picture has to bring its box into view.
  //
  // Called through an optional call, not a plain one. jsdom implements no
  // `scrollIntoView` at all, so a plain call throws inside an effect and takes
  // the whole component down in every test that selects a step.
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView?.({ block: "nearest" });
  }, [selected]);

  const label = localizedField(i18n.language, step.labelEn, step.labelAr);
  const detail = detailRows(step, t("explainer.noReading"));

  return (
    <li
      ref={ref}
      className={
        "rounded-lg border text-xs " +
        (selected ? "border-ap-accent bg-ap-accent/5" : "border-ap-line bg-ap-panel")
      }
    >
      <button
        type="button"
        onClick={() => {
          onSelect();
          setOpen((v) => !v);
        }}
        className="flex w-full items-start gap-2 p-2 text-start"
      >
        <span className="mt-0.5 w-5 shrink-0 text-meta text-ap-muted">{position}</span>
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="text-meta uppercase text-ap-muted">
              {t(`canvas.kind.${step.kind}`, { defaultValue: step.kind })}
            </span>
            <StepResult step={step} />
          </span>
          <span className="text-ap-ink">{label || t("explainer.unlabelled")}</span>
          <span dir="ltr" className="font-mono text-[10px] text-ap-muted">
            {step.nodeId}
          </span>
        </span>
      </button>
      {open && detail.length > 0 ? (
        <dl className="border-t border-ap-line px-2 py-1.5">
          {detail.map((row) => (
            <div key={row.label} className="flex justify-between gap-2 py-0.5">
              <dt dir="ltr" className="font-mono text-[10px] text-ap-muted">
                {row.label}
              </dt>
              <dd dir="ltr" className="font-mono text-[10px] text-ap-ink">
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </li>
  );
}

/** The header's result word: what this node answered or did. */
function StepResult({ step }: { step: WalkStep }): ReactNode {
  const { t } = useTranslation("decisionTreesBeta");
  const registered = registeredDetail(step);

  if (step.kind === "condition" && step.matched !== null) {
    return (
      <Pill kind={step.matched ? "ok" : "neutral"}>
        {step.matched ? t("explainer.yes") : t("explainer.no")}
      </Pill>
    );
  }
  if (registered !== null) {
    return (
      <span className="flex flex-wrap items-center gap-1">
        <Pill kind="warn">
          <span dir="ltr">{registered.code}</span>
        </Pill>
        {registered.severity ? (
          <span className="text-meta text-ap-muted">
            {t(`severity.${registered.severity}`, { defaultValue: registered.severity })}
          </span>
        ) : null}
        {/* A repeat register keeps one finding, and only counts when it
            raised the severity. Without this the same code twice reads as
            double-counting. */}
        {registered.repeat ? (
          <span className="text-meta text-ap-muted">
            {registered.raised ? t("explainer.raised") : t("explainer.repeat")}
          </span>
        ) : null}
      </span>
    );
  }
  if (step.kind === "switch") {
    const chosen = step.detail?.case;
    return (
      <Pill kind="neutral">
        {typeof chosen === "number"
          ? t("canvas.edge.case", { position: chosen + 1 })
          : t("canvas.edge.default")}
      </Pill>
    );
  }
  if (step.kind === "set") {
    const names = Object.keys(writtenValues(step));
    return (
      <span dir="ltr" className="font-mono text-[10px] text-ap-muted">
        {names.join(", ")}
      </span>
    );
  }
  if (step.kind === "stop") {
    return <Pill kind="neutral">{t("explainer.endOfWalk")}</Pill>;
  }
  return null;
}

/** What the expanded box shows, per kind. */
function detailRows(step: WalkStep, absent: string): { label: string; value: string }[] {
  if (step.kind === "set") {
    return Object.entries(writtenValues(step)).map(([name, value]) => ({
      label: name,
      value: formatValue(value, absent),
    }));
  }
  return Object.entries(step.values).map(([name, value]) => ({
    label: name,
    value: formatValue(value, absent),
  }));
}

// ---- What wrote the text ----------------------------------------------

interface TextSourceProps {
  rule: BetaWalkRule | null;
  composedFrom: BetaWalkClause[] | null;
  textEn: string | null;
  textAr: string | null;
  identity: string[];
  errored: boolean;
  isAr: boolean;
}

function TextSource({
  rule,
  composedFrom,
  textEn,
  textAr,
  identity,
  errored,
  isAr,
}: TextSourceProps): ReactNode {
  const { t } = useTranslation("decisionTreesBeta");
  const statusLabel = useFindingStatusLabel();
  const text = (isAr ? textAr : textEn) || textEn;

  if (errored) {
    // A walk that errored never reached a stop node, so the tree never said
    // it was finished and there is no card to explain.
    return (
      <section className="rounded-lg border border-ap-line p-3">
        <h3 className="text-sm font-medium text-ap-ink">{t("explainer.resultTitle")}</h3>
        <p className="mt-1 text-sm text-ap-muted">{t("explainer.noCardErrored")}</p>
      </section>
    );
  }

  if (identity.length === 0) {
    return (
      <section className="rounded-lg border border-ap-line p-3">
        <h3 className="text-sm font-medium text-ap-ink">{t("explainer.resultTitle")}</h3>
        <p className="mt-1 text-sm text-ap-muted">{t("explainer.noFindings")}</p>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-2 rounded-lg border border-ap-line p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-ap-ink">{t("explainer.resultTitle")}</h3>
        <span dir="ltr" className="flex flex-wrap gap-1 font-mono text-xs">
          {identity.map((code) => (
            <span key={code} className="rounded bg-ap-line/60 px-1.5 py-0.5 text-ap-ink">
              {code}
            </span>
          ))}
        </span>
      </div>

      {rule !== null ? (
        <div className="flex flex-col gap-1.5">
          <p className="flex flex-wrap items-center gap-2 text-sm text-ap-ink">
            <Pill kind="ok">{t("explainer.ruleMatched")}</Pill>
            <span dir="ltr" className="font-mono text-xs">
              {rule.code ?? t("explainer.ruleUnnamed")}
            </span>
            {rule.status ? (
              <span className="text-meta text-ap-muted">{statusLabel(rule.status)}</span>
            ) : null}
            {rule.action_type ? (
              <span className="text-meta text-ap-muted">
                {t(`actionType.${rule.action_type}`, { defaultValue: rule.action_type })}
              </span>
            ) : null}
          </p>
          <p dir="ltr" className="text-sm text-ap-ink">
            {rule.text_en}
          </p>
          {rule.text_ar ? (
            <p dir="rtl" className="text-sm text-ap-ink">
              {rule.text_ar}
            </p>
          ) : null}
        </div>
      ) : null}

      {composedFrom !== null && composedFrom.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <p className="flex items-center gap-2 text-sm text-ap-ink">
            <Pill kind="neutral">{t("explainer.composed")}</Pill>
            <span className="text-meta text-ap-muted">{t("explainer.composedHelp")}</span>
          </p>
          <ol className="flex flex-col gap-1">
            {composedFrom.map((clause) => (
              <li key={clause.code} className="flex flex-wrap items-baseline gap-2 text-sm">
                <span dir="ltr" className="font-mono text-xs text-ap-muted">
                  {clause.code}
                </span>
                <span dir={isAr ? "rtl" : "ltr"} className="text-ap-ink">
                  {(isAr ? clause.clause_ar : clause.clause_en) || clause.clause_en || "—"}
                </span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {text ? (
        <p dir={isAr ? "rtl" : "ltr"} className="rounded-md bg-ap-bg/60 p-2 text-sm text-ap-ink">
          {text}
        </p>
      ) : null}
    </section>
  );
}
