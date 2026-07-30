import { formatDistanceToNow, parseISO } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import type { Alert, AlertSeverity } from "@/api/alerts";
import { DataPendingChip } from "@/components/DataPendingChip";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useDateLocale } from "@/hooks/useDateLocale";
import { localizedField } from "@/lib/localizedField";
import { useAlerts } from "@/queries/alerts";

interface Props {
  farmId: string;
}

const SEV_KIND: Record<AlertSeverity, "info" | "warn" | "crit"> = {
  info: "info",
  warning: "warn",
  critical: "crit",
};

export function AlertsFeedCard({ farmId }: Props): ReactNode {
  const { t } = useTranslation("insights");
  const navigate = useNavigate();
  // Scope to the farm — an unscoped list is tenant-wide, so the feed showed
  // other farms' alerts whose "Resolve" jumps to a lane this board lacks.
  const { data, isLoading, isError } = useAlerts({ farm_id: farmId, status: "open" });

  return (
    <section
      aria-labelledby="alerts-feed-heading"
      className="rounded-xl border border-ap-line bg-ap-panel p-4"
    >
      <header className="flex items-baseline justify-between">
        <h2
          id="alerts-feed-heading"
          className="text-sm font-semibold uppercase tracking-wider text-ap-muted"
        >
          {t("alertsFeed.title")}
        </h2>
        <button
          type="button"
          onClick={() => navigate(`/alerts/${farmId}`)}
          className="text-xs font-medium text-ap-primary hover:underline"
        >
          {t("alertsFeed.viewAll")}
        </button>
      </header>
      <div className="mt-3 flex flex-col divide-y divide-ap-line">
        {isLoading ? (
          <div className="space-y-2 py-2">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : isError ? (
          <p className="py-3 text-sm text-ap-crit">{t("alertsFeed.loadFailed")}</p>
        ) : !data || data.length === 0 ? (
          <p className="py-6 text-center text-sm text-ap-muted">{t("alertsFeed.empty")}</p>
        ) : (
          data.slice(0, 6).map((a) => <AlertRow key={a.id} alert={a} farmId={farmId} />)
        )}
      </div>
    </section>
  );
}

function AlertRow({ alert: a, farmId }: { alert: Alert; farmId: string }): ReactNode {
  const { t, i18n } = useTranslation("insights");
  const dateLocale = useDateLocale();
  const navigate = useNavigate();
  const diagnosis = localizedField(i18n.language, a.diagnosis_en, a.diagnosis_ar);
  const prescription = localizedField(i18n.language, a.prescription_en, a.prescription_ar);
  const goResolve = () => {
    if (a.prescription_activity_id) {
      navigate(`/board/${farmId}?activity=${a.prescription_activity_id}&lane=${a.block_id}`);
    } else {
      navigate(`/board/${farmId}?lane=${a.block_id}`);
    }
  };
  return (
    <div className="flex items-start gap-3 py-3">
      <div
        aria-hidden="true"
        className={`h-9 w-1 flex-none rounded-full ${
          a.severity === "critical"
            ? "bg-ap-crit"
            : a.severity === "warning"
              ? "bg-ap-warn"
              : "bg-ap-accent"
        }`}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-ap-ink">
            {diagnosis ?? a.rule_code}
          </span>
          <Pill kind={SEV_KIND[a.severity]}>{t(`severity.${a.severity}`)}</Pill>
        </div>
        {prescription ? (
          <p className="line-clamp-2 text-xs text-ap-muted">{prescription}</p>
        ) : null}
        <div className="mt-1 flex items-center gap-2 text-[11px] text-ap-muted">
          <span className="font-mono">{a.rule_code}</span>
          <span>·</span>
          <span>
            {formatDistanceToNow(parseISO(a.created_at), { addSuffix: true, locale: dateLocale })}
          </span>
          {!a.prescription_activity_id ? (
            <>
              <span>·</span>
              <DataPendingChip>{t("alertsFeed.noPrescription")}</DataPendingChip>
            </>
          ) : null}
        </div>
      </div>
      <button
        type="button"
        onClick={goResolve}
        className="flex-none rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
      >
        {t("alertsFeed.resolve")}
      </button>
    </div>
  );
}
