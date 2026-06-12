import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { PageHeader } from "@/components/PageHeader";
import { SegmentedControl } from "@/components/SegmentedControl";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { hasCapability, useClaims } from "@/rbac/useCapability";

import { DateRangePicker } from "../components/DateRangePicker";
import { defaultRange, type DateRange } from "../dateRange";
import { REPORTS } from "../registry";

export function ReportsPage(): ReactNode {
  const { t } = useTranslation("reports");
  const farmId = useActiveFarmId();
  const claims = useClaims();
  const [range, setRange] = useState<DateRange>(() => defaultRange());

  // Capability-filter the catalog against the active farm. Done once
  // from the decoded claims (not a hook-per-report) so the list stays
  // dynamic without breaking the rules-of-hooks.
  const available = useMemo(
    () => (farmId ? REPORTS.filter((r) => hasCapability(claims, r.capability, { farmId })) : []),
    [claims, farmId],
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const activeId = selectedId ?? available[0]?.id ?? null;
  const active = available.find((r) => r.id === activeId) ?? null;

  if (!farmId) {
    return (
      <div className="mx-auto max-w-3xl py-12 text-center">
        <h1 className="text-xl font-semibold text-ap-ink">{t("title")}</h1>
        <p className="mt-2 text-sm text-ap-muted">{t("pickFarm")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-5 p-4">
      <PageHeader title={t("title")} subtitle={t("subtitle")} />

      {available.length === 0 ? (
        <p className="rounded-xl border border-dashed border-ap-line bg-ap-panel/50 py-12 text-center text-sm text-ap-muted">
          {t("empty")}
        </p>
      ) : (
        <>
          <div className="print-hide flex flex-wrap items-center justify-between gap-3">
            <SegmentedControl
              ariaLabel={t("selectorLabel")}
              value={activeId ?? ""}
              onChange={setSelectedId}
              items={available.map((r) => ({
                value: r.id,
                label: t(`catalog.${r.id}.title`),
              }))}
            />
            <DateRangePicker value={range} onChange={setRange} />
          </div>

          {active ? (
            <active.Component farmId={farmId} since={range.since} until={range.until} />
          ) : null}
        </>
      )}
    </div>
  );
}
