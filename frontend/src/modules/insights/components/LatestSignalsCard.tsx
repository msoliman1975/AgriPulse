import { formatDistanceToNow, parseISO } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import type { SignalObservation } from "@/api/signals";
import { Skeleton } from "@/components/Skeleton";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useSignalObservations } from "@/queries/signals";

interface Props {
  farmId: string;
  limit?: number;
}

/** Compact list of the N most-recent signal observations on a farm.
 *
 * Lives next to the AlertsFeedCard on the dashboard so the operator
 * sees at-a-glance whether the field-team has been logging — and what
 * they've seen — without leaving the insights page.
 */
export function LatestSignalsCard({ farmId, limit = 5 }: Props): ReactNode {
  const navigate = useNavigate();
  const { t } = useTranslation("insights");
  const dateLocale = useDateLocale();
  const { data, isLoading, isError } = useSignalObservations({
    farm_id: farmId,
    limit,
  });
  return (
    <section className="rounded-xl border border-ap-line bg-ap-panel">
      <header className="flex items-center justify-between border-b border-ap-line px-4 py-2">
        <h2 className="text-sm font-semibold text-ap-ink">{t("latestSignals.heading")}</h2>
        <button
          type="button"
          onClick={() => navigate(`/signals/${farmId}`)}
          className="text-xs font-medium text-ap-primary hover:underline"
        >
          {t("latestSignals.logLink")}
        </button>
      </header>
      {isLoading ? (
        <div className="flex flex-col gap-2 p-4">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      ) : isError ? (
        <p className="p-4 text-sm text-ap-crit">{t("latestSignals.loadFailed")}</p>
      ) : !data || data.length === 0 ? (
        <p className="p-6 text-center text-xs text-ap-muted">{t("latestSignals.empty")}</p>
      ) : (
        <ul className="divide-y divide-ap-line">
          {data.map((o) => (
            <li key={o.id} className="flex items-center gap-2 px-4 py-2 text-sm">
              <span className="font-mono text-[11px] text-ap-muted">{o.signal_code}</span>
              <span className="font-medium text-ap-ink">{formatValue(o)}</span>
              <span className="ms-auto text-[11px] text-ap-muted">
                {formatDistanceToNow(parseISO(o.time), {
                  addSuffix: true,
                  locale: dateLocale,
                })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function formatValue(o: SignalObservation): string {
  if (o.value_numeric !== null) return o.value_numeric;
  if (o.value_categorical !== null) return o.value_categorical;
  if (o.value_event !== null) return o.value_event;
  if (o.value_boolean !== null) return String(o.value_boolean);
  if (o.value_geopoint) return `${o.value_geopoint.latitude}, ${o.value_geopoint.longitude}`;
  return "—";
}
