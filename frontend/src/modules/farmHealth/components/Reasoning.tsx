// Why this area is this colour.
//
// It expands inside the area card rather than opening a dialog. Mohamed
// asked for that on 2026-09-07: a modal put the reasoning somewhere you had
// to leave to look at the map again.
//
// The walk comes from GET /blocks/{id}/verdicts/{vid}/reasoning, which is
// gated the way the verdict reads are. `/decision-tree-traces` holds the
// same walk and is gated on decision_tree.read, which five of the eight
// roles do not have — so pointing this at the author's endpoint would 403
// every reader the screen is for.

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { getVerdictReasoning } from "@/api/farmHealth";
import { walkRows } from "../lib/walk";

interface Props {
  blockId: string;
  verdictId: string;
  farmId: string;
  leafNodeId: string;
  kind: string;
  statusCode: string;
}

export function Reasoning({ blockId, verdictId, farmId, leafNodeId, kind, statusCode }: Props) {
  const { t, i18n } = useTranslation(["farmHealth"]);
  const arabic = i18n.language.startsWith("ar");
  // Closed by default: the paragraph above answers the question, and the
  // grid is for the reader who wants to check a number in it.
  const [stepsOpen, setStepsOpen] = useState(false);

  const query = useQuery({
    queryKey: ["verdict-reasoning", blockId, verdictId],
    queryFn: () => getVerdictReasoning(blockId, verdictId, farmId),
    // The walk behind a verdict never changes; only a new sweep makes a new
    // one, and that is a new verdict id.
    staleTime: Infinity,
  });

  if (query.isPending) {
    return <p className="text-sm text-ap-muted">{t("farmHealth:reasoning.loading")}</p>;
  }
  if (query.isError || !query.data) {
    return (
      <p className="text-sm text-ap-crit" role="alert">
        {t("farmHealth:reasoning.failed")}
      </p>
    );
  }

  const data = query.data;
  if (!data.reasoning_available) {
    // Retention prunes eval runs and their traces. The verdict outlives its
    // walk, and saying so is different from showing an empty list, which
    // reads as "the tree did nothing".
    return <p className="text-sm text-ap-muted">{t("farmHealth:reasoning.pruned")}</p>;
  }

  const rows = walkRows(data.node_path, arabic);
  const narrative = arabic ? data.narrative_ar : data.narrative_en;

  return (
    <div className="grid gap-3">
      {/* The paragraph is what a reader reads. The grid below it is the same
          facts as a table, kept for whoever is auditing a threshold — it was
          the only thing here, and it made "why is this block green" a puzzle
          the reader had to assemble. */}
      {narrative ? (
        <p className="max-w-prose text-sm leading-relaxed text-ap-ink">{narrative}</p>
      ) : null}

      <div>
        <button
          type="button"
          aria-expanded={stepsOpen}
          onClick={() => setStepsOpen((was) => !was)}
          className="text-meta font-medium text-ap-accent underline underline-offset-4"
        >
          {stepsOpen ? t("farmHealth:reasoning.hideSteps") : t("farmHealth:reasoning.showSteps")}
        </button>
      </div>

      {stepsOpen ? (
      <>
      <span className="text-meta font-semibold uppercase tracking-wide text-ap-muted">
        {t("farmHealth:reasoning.steps")}
      </span>
      <ol className="grid gap-1.5">
        {rows.map((row, index) => (
          <li
            key={`${row.nodeId}-${index}`}
            className="grid grid-cols-[1.5rem_minmax(0,1fr)_auto] items-start gap-3 rounded border border-ap-line bg-ap-panel px-3 py-2"
          >
            <span className="text-sm tabular-nums text-ap-muted">{index + 1}</span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-ap-ink">{row.question}</span>
              {row.read !== null || row.test !== null ? (
                <span className="mt-0.5 block break-words text-meta tabular-nums text-ap-muted">
                  {row.read !== null ? t("farmHealth:reasoning.read", { read: row.read }) : null}
                  {row.read !== null && row.test !== null ? "  │  " : null}
                  {row.test !== null ? t("farmHealth:reasoning.test", { test: row.test }) : null}
                </span>
              ) : null}
            </span>
            <span
              className={[
                "text-meta font-semibold uppercase tracking-wide",
                row.matched ? "text-ap-primary" : "text-ap-muted",
              ].join(" ")}
            >
              {row.matched ? t("farmHealth:reasoning.yes") : t("farmHealth:reasoning.no")}
            </span>
          </li>
        ))}
      </ol>
      </>
      ) : null}

      <div className="grid gap-1 rounded border border-ap-primary bg-ap-primary-soft px-3 py-2">
        <span className="text-sm font-semibold text-ap-primary">
          {t("farmHealth:reasoning.leaf", { leaf: leafNodeId, kind, status: statusCode })}
        </span>
      </div>
    </div>
  );
}
