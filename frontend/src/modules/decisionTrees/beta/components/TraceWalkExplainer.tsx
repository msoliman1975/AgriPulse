/**
 * The walk explainer over a real run's stored trace.
 *
 * The other half of the same screen. `WalkExplainerPanel` walks a cell now,
 * for an author reading a dry run; this reads what the sweep already walked
 * and wrote to `decision_tree_eval_traces.node_path` at the time. Both hand
 * the same `WalkStep[]` to the same `WalkExplainer`.
 *
 * **Nothing is fetched for the walk.** It is on the trace row. The one read
 * here is the tree itself, to draw: a trace carries `tree_code` and
 * `tree_version`, never a definition, and the beta tree read is where the
 * definition lives. When that read fails — a reader without
 * `decision_tree.read`, a code that is not a beta tree — the layout is null
 * and the step list still reads on its own.
 *
 * **The rule is named, or it is not, and the difference is a date.** A trace
 * row's `matched_rule` is `FoldedCard.rule_code`, which was null on every row
 * written before the compiler carried a rule's code. An old row says a rule
 * matched without naming it, which is the truth about that row.
 */

import { useMemo, type ReactNode } from "react";

import type { EvalTraceDetail } from "@/api/decisionTrees";
import { useBetaTrees, useBetaTree } from "@/queries/decisionTreesBeta";

import { WalkExplainer } from "./WalkExplainer";
import { layoutBetaTree } from "../lib/betaLayout";
import { registeredDetail, walkStepsFromTrace } from "../lib/walkTrace";

export interface TraceWalkExplainerProps {
  trace: EvalTraceDetail;
}

export function TraceWalkExplainer({ trace }: TraceWalkExplainerProps): ReactNode {
  const steps = useMemo(() => walkStepsFromTrace(trace.node_path), [trace.node_path]);

  // The tree list is a small cached read and is what turns a code into an id;
  // the detail read is what carries the versions and their definitions.
  const trees = useBetaTrees();
  const isBeta = (trees.data ?? []).some((row) => row.code === trace.tree_code);
  const treeQ = useBetaTree(isBeta ? trace.tree_code : undefined);

  const layout = useMemo(() => {
    const version = (treeQ.data?.versions ?? []).find((v) => v.version === trace.tree_version);
    return version ? layoutBetaTree(version.definition) : null;
  }, [treeQ.data, trace.tree_version]);

  // A trace row written before the fold columns were exposed carries none.
  // The register steps of the walk say the same thing, so the finding set is
  // derived from them rather than left empty.
  const identity = useMemo(() => {
    if (trace.finding_set && trace.finding_set.length > 0) return trace.finding_set;
    const codes = new Set<string>();
    for (const step of steps) {
      const registered = registeredDetail(step);
      if (registered !== null) codes.add(registered.code);
    }
    return [...codes].sort();
  }, [trace.finding_set, steps]);

  return (
    <WalkExplainer
      steps={steps}
      layout={layout}
      rule={
        trace.matched_rule === null || trace.matched_rule === undefined
          ? null
          : {
              code: trace.matched_rule,
              codes: identity,
              text_en: null,
              text_ar: null,
              status: null,
              action_type: null,
            }
      }
      identity={identity}
      error={trace.error}
    />
  );
}
