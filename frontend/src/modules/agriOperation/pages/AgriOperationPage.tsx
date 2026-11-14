// Agri Operation: operation manuals and the farm's saved plans built from
// them. Replaces the Plan board's Apply template dialog for farms.
// docs/proposals/agri-operation-build-plan.md

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/EmptyState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { SegmentedControl } from "@/components/SegmentedControl";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useCapability } from "@/rbac/useCapability";
import { CatalogTab } from "../components/CatalogTab";
import { PlanTab } from "../components/PlanTab";

type Tab = "catalog" | "plan";

export function AgriOperationPage(): ReactNode {
  const farmId = useActiveFarmId() ?? null;
  const { t } = useTranslation("agriOperation");
  const scope = { farmId: farmId ?? undefined };
  const canRead = useCapability("plan_template.read", scope);
  const canPlan = useCapability("plan_allocation.read", scope);
  const [tab, setTab] = useState<Tab>("catalog");
  const [manualId, setManualId] = useState<string | null>(null);

  return (
    <Page>
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          canPlan ? (
            <SegmentedControl<Tab>
              ariaLabel={t("tabs.label")}
              value={tab}
              onChange={setTab}
              items={[
                { value: "catalog", label: t("tabs.catalog") },
                { value: "plan", label: t("tabs.plan") },
              ]}
            />
          ) : null
        }
      />
      {!farmId ? (
        <EmptyState message={t("pickFarm")} />
      ) : !canRead ? (
        <EmptyState message={t("noAccess")} />
      ) : tab === "plan" && canPlan ? (
        <PlanTab farmId={farmId} manualId={manualId} onPickManual={() => setTab("catalog")} />
      ) : (
        <CatalogTab farmId={farmId} manualId={manualId} onManualChange={setManualId} />
      )}
    </Page>
  );
}
