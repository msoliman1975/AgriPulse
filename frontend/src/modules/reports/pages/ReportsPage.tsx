import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { SegmentedControl } from "@/components/SegmentedControl";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { hasCapability, useClaims, useServedGrants } from "@/rbac/useCapability";

import { DateRangePicker } from "../components/DateRangePicker";
import { defaultRange, type DateRange } from "../dateRange";
import { REPORTS } from "../registry";

export function ReportsPage(): ReactNode {
  const { t } = useTranslation("reports");
  const farmId = useActiveFarmId();
  const claims = useClaims();
  // Read once here rather than per report: `useCapability` is a hook and the
  // catalog length is data-driven, so a hook-per-report would break the rules
  // of hooks. Passing the served grants keeps this in step with a runtime
  // permission change instead of resolving against the bundled mirror.
  const served = useServedGrants();
  const [range, setRange] = useState<DateRange>(() => defaultRange());

  // Capability-filter the catalog against the active farm.
  const available = useMemo(
    () =>
      farmId ? REPORTS.filter((r) => hasCapability(claims, r.capability, { farmId }, served)) : [],
    [claims, farmId, served],
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const activeId = selectedId ?? available[0]?.id ?? null;
  const active = available.find((r) => r.id === activeId) ?? null;

  if (!farmId) {
    return (
      <Page width="standard">
        <div className="py-12 text-center">
          <PageHeader title={t("title")} />
          <p className="mt-2 text-sm text-ap-muted">{t("pickFarm")}</p>
        </div>
      </Page>
    );
  }

  return (
    <Page>
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
    </Page>
  );
}
