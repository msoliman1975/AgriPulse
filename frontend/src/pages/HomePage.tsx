import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { listFarms } from "@/api/farms";
import { Card } from "@/components/Card";
import { LinkButton } from "@/components/LinkButton";
import { Page } from "@/components/Page";
import { useCapability } from "@/rbac/useCapability";

export function HomePage(): ReactNode {
  const { t } = useTranslation("common");
  const canCreateFarm = useCapability("farm.create");
  // Redirect to /insights/<first-farm-id> when the user has at least one
  // farm — that's the AgriPulse landing convention. Pre-FarmDM users with
  // no farms see the empty-state card with a Create CTA (when they have
  // farm.create) or a coming-soon message.
  const { data, isLoading, isError } = useQuery({
    queryKey: ["farms", "list", "home-redirect"] as const,
    queryFn: () => listFarms(),
    staleTime: 60_000,
  });
  if (isLoading) {
    return (
      <Page width="standard">
        <Card className="max-w-2xl" role="status">
          <p className="text-ap-muted">{t("actions.loading")}</p>
        </Card>
      </Page>
    );
  }
  if (!isError && data && data.items.length > 0) {
    return <Navigate to={`/insights/${data.items[0].id}`} replace />;
  }
  return (
    <Page width="standard">
      <Card className="max-w-2xl">
        <h2 className="text-2xl font-semibold text-ap-ink">
          {canCreateFarm ? t("home.noFarmsTitle") : t("home.welcome")}
        </h2>
        <p className="mt-2 text-ap-muted">
          {canCreateFarm ? t("home.noFarmsBody") : t("home.comingSoon")}
        </p>
        {canCreateFarm ? (
          <LinkButton to="/labs/map?create=farm" className="mt-4">
            {t("home.createFirstFarm")}
          </LinkButton>
        ) : null}
      </Card>
    </Page>
  );
}
