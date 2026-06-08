// Scientific-provenance panel (KB P1-A).
//
// Renders the `evidence:` + `transferability:` blocks a knowledge-base
// tree carries inside its compiled JSON — evidence-quality grade, the
// authoritative citations behind the rule, an explicit uncertainty note,
// and the per-region (Egypt / Middle East / global) suitability scores.
//
// Display-only: the evaluator never reads these. The panel renders
// nothing when a tree declares neither block, so legacy trees are
// unaffected.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Pill, type PillKind } from "@/components/Pill";
import type {
  TreeCitation,
  TreeEvidence,
  TreeTransferability,
} from "@/api/decisionTrees";

interface ProvenancePanelProps {
  evidence: TreeEvidence | null;
  transferability: TreeTransferability | null;
}

// Both an evidence-confidence grade and a transferability grade map onto
// the same visual scale: stronger = greener, weaker = redder.
const GRADE_KIND: Record<string, PillKind> = {
  very_high: "ok",
  high: "ok",
  medium: "warn",
  low: "crit",
  not_applicable: "neutral",
};

const REGION_ORDER: Array<keyof TreeTransferability> = [
  "egypt",
  "middle_east",
  "global",
];

export function ProvenancePanel({
  evidence,
  transferability,
}: ProvenancePanelProps): ReactNode {
  const { t } = useTranslation("decisionTrees");

  if (!evidence && !transferability) return null;

  return (
    <section className="rounded-md border border-ap-line bg-ap-panel p-4 text-sm">
      <h2 className="mb-3 text-sm font-semibold text-ap-ink">
        {t("viewer.provenance.title")}
      </h2>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {evidence ? (
          <EvidenceSection evidence={evidence} />
        ) : null}
        {transferability ? (
          <TransferabilitySection transferability={transferability} />
        ) : null}
      </div>
    </section>
  );
}

function EvidenceSection({ evidence }: { evidence: TreeEvidence }): ReactNode {
  const { t } = useTranslation("decisionTrees");
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-ap-muted">
          {t("viewer.provenance.confidence")}
        </span>
        <Pill kind={GRADE_KIND[evidence.confidence] ?? "neutral"}>
          {t(`viewer.provenance.grade.${evidence.confidence}`)}
        </Pill>
      </div>

      {evidence.notes ? (
        <p className="max-w-prose text-xs italic text-ap-muted">
          {evidence.notes}
        </p>
      ) : null}

      {evidence.citations.length > 0 ? (
        <div>
          <p className="mb-1 text-xs font-medium text-ap-muted">
            {t("viewer.provenance.sources")}
          </p>
          <ul className="flex flex-col gap-1.5">
            {evidence.citations.map((c, i) => (
              <CitationRow key={i} citation={c} />
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function CitationRow({ citation }: { citation: TreeCitation }): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const href = citation.doi
    ? `https://doi.org/${citation.doi}`
    : (citation.url ?? null);
  return (
    <li className="text-xs text-ap-ink">
      <Pill kind="neutral" className="mr-1.5 align-middle">
        {t(`viewer.provenance.sourceType.${citation.source_type}`)}
      </Pill>
      {href ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer noopener"
          className="text-ap-accent underline decoration-dotted underline-offset-2 hover:decoration-solid"
        >
          {citation.title}
        </a>
      ) : (
        <span>{citation.title}</span>
      )}
      {citation.year ? (
        <span className="ml-1 text-ap-muted">({citation.year})</span>
      ) : null}
    </li>
  );
}

function TransferabilitySection({
  transferability,
}: {
  transferability: TreeTransferability;
}): ReactNode {
  const { t } = useTranslation("decisionTrees");
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs font-medium text-ap-muted">
        {t("viewer.provenance.transferability")}
      </p>
      <dl className="flex flex-col gap-1">
        {REGION_ORDER.map((region) => {
          const grade = transferability[region];
          return (
            <div key={region} className="flex items-center justify-between gap-2">
              <dt className="text-xs text-ap-ink">
                {t(`viewer.provenance.region.${region}`)}
              </dt>
              <dd>
                {grade ? (
                  <Pill kind={GRADE_KIND[grade] ?? "neutral"}>
                    {t(`viewer.provenance.grade.${grade}`)}
                  </Pill>
                ) : (
                  <span className="text-xs text-ap-muted">—</span>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}
