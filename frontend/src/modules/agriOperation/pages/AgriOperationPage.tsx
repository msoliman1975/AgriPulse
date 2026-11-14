// Agri Operation: operation manuals and the farm's saved plans built from
// them. Replaces the Plan board's Apply template dialog for farms.
// docs/proposals/agri-operation-build-plan.md

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/EmptyState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useCapability } from "@/rbac/useCapability";
import { CatalogTab } from "../components/CatalogTab";

export function AgriOperationPage(): ReactNode {
  const farmId = useActiveFarmId() ?? null;
  const { t } = useTranslation("agriOperation");
  const canRead = useCapability("plan_template.read", { farmId: farmId ?? undefined });
  const [manualId, setManualId] = useState<string | null>(null);

  return (
    <Page>
      <PageHeader title={t("title")} subtitle={t("subtitle")} />
      {!farmId ? (
        <EmptyState message={t("pickFarm")} />
      ) : !canRead ? (
        <EmptyState message={t("noAccess")} />
      ) : (
        <CatalogTab farmId={farmId} manualId={manualId} onManualChange={setManualId} />
      )}
    </Page>
  );
}
