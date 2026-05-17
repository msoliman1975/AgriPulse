import { formatDistanceToNow, parseISO } from "date-fns";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import type {
  Recommendation,
  RecommendationSeverity,
  RecommendationState,
  TreePathStepDTO,
} from "@/api/recommendations";
import { Pill } from "@/components/Pill";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Skeleton } from "@/components/Skeleton";
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

export function RecommendationsPage(): ReactNode {
  const farmId = useActiveFarmId();
  const { t } = useTranslation("recommendations");
  const [tab, setTab] = useState<RecommendationState | "all">("open");
  const canAct = useCapability("recommendation.act", { farmId });

  const params = tab === "all" ? { farm_id: farmId } : { farm_id: farmId, state: tab };
  const { data, isLoading, isError } = useRecommendations(params);
  const transition = useTransitionRecommendation();

  if (!farmId) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ap-ink">{t("page.title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("page.subtitle")}</p>
        </div>
        <SegmentedControl
          ariaLabel={t("tabsLabel")}
          items={STATE_TAB_VALUES.map((v) => ({ value: v, label: t(`tabs.${v}`) }))}
          value={tab}
          onChange={(v) => setTab(v)}
        />
      </header>

      <div className="rounded-xl border border-ap-line bg-ap-panel">
        {isLoading ? (
          <div className="flex flex-col gap-2 p-4">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : isError ? (
          <p className="p-4 text-sm text-ap-crit">{t("page.loadFailed")}</p>
        ) : !data || data.length === 0 ? (
          <p className="p-12 text-center text-sm text-ap-muted">
            {tab === "open" ? t("page.emptyOpen") : t("page.empty")}
          </p>
        ) : (
          <ul className="divide-y divide-ap-line">
            {data.map((r) => (
              <Row
                key={r.id}
                rec={r}
                canAct={canAct}
                onApply={() =>
                  transition.mutate({
                    recommendationId: r.id,
                    payload: { apply: true },
                  })
                }
                onDismiss={() =>
                  transition.mutate({
                    recommendationId: r.id,
                    payload: { dismiss: true },
                  })
                }
                onDefer={(until) =>
                  transition.mutate({
                    recommendationId: r.id,
                    payload: { defer_until: until },
                  })
                }
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

interface RowProps {
  rec: Recommendation;
  canAct: boolean;
  onApply: () => void;
  onDismiss: () => void;
  onDefer: (until: string) => void;
}

function Row({ rec, canAct, onApply, onDismiss, onDefer }: RowProps): ReactNode {
  const { t, i18n } = useTranslation("recommendations");
  const dateLocale = useDateLocale();
  const [expanded, setExpanded] = useState(false);
  const isTerminal =
    rec.state === "applied" || rec.state === "dismissed" || rec.state === "expired";
  const isAr = i18n.language === "ar";
  // Pick the localized recommendation text written by the decision-tree
  // YAML at evaluation time. Fall back to text_en when ar is missing.
  const localizedText = isAr ? (rec.text_ar ?? rec.text_en) : rec.text_en;
  return (
    <li className="flex items-start gap-3 p-4">
      <div
        aria-hidden="true"
        className={`h-12 w-1 flex-none rounded-full ${
          rec.severity === "critical"
            ? "bg-ap-crit"
            : rec.severity === "warning"
              ? "bg-ap-warn"
              : "bg-ap-accent"
        }`}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-ap-ink">{localizedText}</span>
          <Pill kind={SEV_KIND[rec.severity]}>{t(`severity.${rec.severity}`)}</Pill>
          <Pill kind={stateKind(rec.state)}>{t(`state.${rec.state}`)}</Pill>
          <Pill kind="neutral">{rec.action_type}</Pill>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-ap-muted">
          <span className="font-mono">
            {rec.tree_code}
            <span className="text-ap-muted/70">·v{rec.tree_version}</span>
          </span>
          <span>·</span>
          <span>
            {formatDistanceToNow(parseISO(rec.created_at), { addSuffix: true, locale: dateLocale })}
          </span>
          <span>·</span>
          <span>{t("row.confidence", { percent: confidencePercent(rec.confidence) })}</span>
          {rec.valid_until ? (
            <>
              <span>·</span>
              <span>
                {t("row.expiresIn", {
                  when: formatDistanceToNow(parseISO(rec.valid_until), {
                    addSuffix: true,
                    locale: dateLocale,
                  }),
                })}
              </span>
            </>
          ) : null}
          {rec.deferred_until && rec.state === "deferred" ? (
            <>
              <span>·</span>
              <span>
                {t("row.deferredUntil", {
                  when: formatDistanceToNow(parseISO(rec.deferred_until), {
                    addSuffix: true,
                    locale: dateLocale,
                  }),
                })}
              </span>
            </>
          ) : null}
        </div>
        <button
          type="button"
          onClick={() => setExpanded((s) => !s)}
          className="mt-2 text-[11px] font-medium text-ap-primary hover:underline"
        >
          {expanded ? t("row.explainHide") : t("row.explainShow")}
        </button>
        {expanded ? <TreePath path={rec.tree_path} /> : null}
      </div>
      <div className="flex flex-none flex-col items-end gap-1.5">
        {!isTerminal && canAct ? (
          <div className="flex gap-1">
            <button
              type="button"
              onClick={onDismiss}
              className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
            >
              {t("actions.dismiss")}
            </button>
            {rec.state === "open" ? (
              <button
                type="button"
                onClick={() => onDefer(defaultDeferUntil())}
                className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
                title={t("actions.defer24Title")}
              >
                {t("actions.defer24")}
              </button>
            ) : null}
            <button
              type="button"
              onClick={onApply}
              className="rounded-md bg-ap-primary px-2 py-1 text-xs font-medium text-white hover:bg-ap-primary/90"
            >
              {t("actions.apply")}
            </button>
          </div>
        ) : null}
      </div>
    </li>
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
