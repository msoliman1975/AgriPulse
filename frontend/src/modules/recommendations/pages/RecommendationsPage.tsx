import { formatDistanceToNow, parseISO } from "date-fns";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import type {
  ActionHorizon,
  Recommendation,
  RecommendationActions,
  RecommendationSeverity,
  RecommendationState,
  TreePathStepDTO,
} from "@/api/recommendations";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { LinkButton } from "@/components/LinkButton";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { cellLabel } from "@/lib/cellLabel";
import { SegmentedControl } from "@/components/SegmentedControl";
import { RowList } from "@/components/RowList";
import { queryState } from "@/components/asyncState";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useCapability } from "@/rbac/useCapability";
import { useRecommendations, useTransitionRecommendation } from "@/queries/recommendations";

const STATE_TAB_VALUES: ReadonlyArray<RecommendationState | "all"> = [
  "open",
  "deferred",
  "applied",
  "dismissed",
  "all",
];

const SEV_KIND: Record<RecommendationSeverity, "info" | "warn" | "crit"> = {
  info: "info",
  warning: "warn",
  critical: "crit",
};

const SEV_RAIL: Record<RecommendationSeverity, string> = {
  info: "bg-ap-accent",
  warning: "bg-ap-warn",
  critical: "bg-ap-crit",
};

export function RecommendationsPage(): ReactNode {
  const farmId = useActiveFarmId();
  const { t, i18n } = useTranslation("recommendations");
  const dateLocale = useDateLocale();
  const [tab, setTab] = useState<RecommendationState | "all">("open");
  const canAct = useCapability("recommendation.act", { farmId });
  const isAr = i18n.language === "ar";

  const params = tab === "all" ? { farm_id: farmId } : { farm_id: farmId, state: tab };
  const recommendations = useRecommendations(params);
  const transition = useTransitionRecommendation();

  if (!farmId) {
    return <Navigate to="/" replace />;
  }

  const ago = (iso: string): string =>
    formatDistanceToNow(parseISO(iso), { addSuffix: true, locale: dateLocale });

  return (
    <Page>
      <PageHeader
        title={t("page.title")}
        subtitle={t("page.subtitle")}
        actions={
          <>
            <SegmentedControl
              ariaLabel={t("tabsLabel")}
              items={STATE_TAB_VALUES.map((v) => ({ value: v, label: t(`tabs.${v}`) }))}
              value={tab}
              onChange={(v) => setTab(v)}
            />
            {/* F-8: give applied recommendations a direct path to the board
                instead of stranding the user after "Apply". */}
            <LinkButton variant="secondary" to={`/board/${farmId}`}>
              {t("actions.openInPlan")}
            </LinkButton>
          </>
        }
      />

      <RowList<Recommendation>
        state={queryState(recommendations)}
        filtered={tab !== "all"}
        rowKey={(rec) => rec.id}
        rail={(rec) => SEV_RAIL[rec.severity]}
        errorMessage={t("page.loadFailed")}
        title={(rec) => (
          <>
            {isAr ? (rec.text_ar ?? rec.text_en) : rec.text_en}
            <Pill kind={SEV_KIND[rec.severity]}>{t(`severity.${rec.severity}`)}</Pill>
            <Pill kind={stateKind(rec.state)}>{t(`state.${rec.state}`)}</Pill>
            <Pill kind="neutral">{t(`recAction.${rec.action_type}`)}</Pill>
            {cellLabel(rec.cell_row, rec.cell_col) ? (
              <Pill kind="neutral">
                {t("row.zone", { zone: cellLabel(rec.cell_row, rec.cell_col) })}
              </Pill>
            ) : null}
          </>
        )}
        meta={(rec) => (
          <>
            <span className="font-mono">
              {rec.tree_code}
              <span className="text-ap-muted/70">·v{rec.tree_version}</span>
            </span>
            <span>·</span>
            <span>{ago(rec.created_at)}</span>
            <span>·</span>
            <span>{t("row.confidence", { percent: confidencePercent(rec.confidence) })}</span>
            {rec.valid_until ? (
              <>
                <span>·</span>
                <span>{t("row.expiresIn", { when: ago(rec.valid_until) })}</span>
              </>
            ) : null}
            {rec.deferred_until && rec.state === "deferred" ? (
              <>
                <span>·</span>
                <span>{t("row.deferredUntil", { when: ago(rec.deferred_until) })}</span>
              </>
            ) : null}
          </>
        )}
        extra={(rec) => <Explain rec={rec} />}
        actions={(rec) => {
          const isTerminal =
            rec.state === "applied" || rec.state === "dismissed" || rec.state === "expired";
          return (
            <div className="flex flex-col items-end gap-1.5">
              {!isTerminal && canAct ? (
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() =>
                      transition.mutate({ recommendationId: rec.id, payload: { dismiss: true } })
                    }
                  >
                    {t("actions.dismiss")}
                  </Button>
                  {rec.state === "open" ? (
                    <Button
                      size="sm"
                      variant="secondary"
                      title={t("actions.defer24Title")}
                      onClick={() =>
                        transition.mutate({
                          recommendationId: rec.id,
                          payload: { defer_until: defaultDeferUntil() },
                        })
                      }
                    >
                      {t("actions.defer24")}
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    onClick={() =>
                      transition.mutate({ recommendationId: rec.id, payload: { apply: true } })
                    }
                  >
                    {t("actions.apply")}
                  </Button>
                </div>
              ) : null}
              {rec.state === "applied" ? (
                <LinkButton size="sm" variant="ghost" to={`/board/${farmId}`}>
                  {t("actions.openInPlan")}
                </LinkButton>
              ) : null}
            </div>
          );
        }}
        empty={<EmptyState message={t("page.empty")} action={null} />}
        noResults={
          <EmptyState
            message={tab === "open" ? t("page.emptyOpen") : t("page.empty")}
            action={
              tab === "all" ? null : (
                <Button variant="secondary" onClick={() => setTab("all")}>
                  {t("tabs.all")}
                </Button>
              )
            }
          />
        }
      />
    </Page>
  );
}

/**
 * The per-row explainability toggle. Owns its own open state, so it stays a
 * component rather than an inline render inside the RowList slot.
 */
function Explain({ rec }: { rec: Recommendation }): ReactNode {
  const { t } = useTranslation("recommendations");
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setExpanded((s) => !s)}
        className="mt-2 text-[11px] font-medium text-ap-primary hover:underline"
      >
        {expanded ? t("row.explainHide") : t("row.explainShow")}
      </button>
      {expanded ? (
        <>
          <ActionsList actions={rec.actions} />
          <TreePath path={rec.tree_path} />
        </>
      ) : null}
    </>
  );
}

// 4-horizon structured guidance (KB P1-B). Rendered above the
// explainability path when a recommendation carries an `actions` block;
// renders nothing for recommendations whose leaf had only a summary.
const ACTION_HORIZONS: readonly ActionHorizon[] = [
  "immediate",
  "short_term",
  "long_term",
  "monitoring",
];

function ActionsList({ actions }: { actions: RecommendationActions }): ReactNode {
  const { t, i18n } = useTranslation("recommendations");
  const isAr = i18n.language === "ar";
  const present = ACTION_HORIZONS.filter((h) => (actions[h]?.length ?? 0) > 0);
  if (present.length === 0) return null;
  return (
    <dl className="mt-2 flex flex-col gap-2 rounded-md border border-ap-line bg-ap-bg/40 p-3 text-[11px]">
      {present.map((horizon) => (
        <div key={horizon}>
          <dt className="font-semibold text-ap-ink">{t(`actionHorizon.${horizon}`)}</dt>
          <dd>
            <ul className="ms-3 list-disc text-ap-muted">
              {(actions[horizon] ?? []).map((item, i) => (
                <li key={i}>{isAr ? (item.text_ar ?? item.text_en) : item.text_en}</li>
              ))}
            </ul>
          </dd>
        </div>
      ))}
    </dl>
  );
}

function TreePath({ path }: { path: TreePathStepDTO[] }): ReactNode {
  const { t, i18n } = useTranslation("recommendations");
  const isAr = i18n.language === "ar";
  return (
    <ol className="mt-2 flex flex-col gap-1 rounded-md border border-ap-line bg-ap-bg/40 p-3 text-[11px]">
      {path.map((step, i) => {
        const label = (isAr ? (step.label_ar ?? step.label_en) : step.label_en) ?? null;
        return (
          <li key={`${step.node_id}-${i}`} className="flex items-start gap-2">
            <span className="mt-0.5 flex-none text-ap-muted">{i + 1}.</span>
            <div className="flex-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-ap-ink">{step.node_id}</span>
                {step.matched === true ? (
                  <Pill kind="ok">{t("path.match")}</Pill>
                ) : step.matched === false ? (
                  <Pill kind="neutral">{t("path.noMatch")}</Pill>
                ) : (
                  <Pill kind="info">{t("path.leaf")}</Pill>
                )}
                {label ? <span className="text-ap-muted">— {label}</span> : null}
              </div>
              {step.values && Object.keys(step.values).length > 0 ? (
                <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-ap-muted">
                  {Object.entries(step.values).map(([k, v]) => (
                    <span key={k}>
                      <span className="font-mono">{k}</span>={" "}
                      <span className="font-mono text-ap-ink">{String(v)}</span>
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function stateKind(state: RecommendationState): "ok" | "neutral" | "crit" | "info" {
  if (state === "applied") return "ok";
  if (state === "dismissed" || state === "expired") return "neutral";
  if (state === "open") return "crit";
  return "info";
}

function confidencePercent(value: string): number {
  const n = Number.parseFloat(value);
  if (Number.isNaN(n)) return 0;
  return Math.round(n * 100);
}

function defaultDeferUntil(): string {
  // Defer 24h. We expose a single shortcut for now; a richer date
  // picker can replace this when the UX needs it.
  const t = new Date();
  t.setUTCHours(t.getUTCHours() + 24);
  return t.toISOString();
}
