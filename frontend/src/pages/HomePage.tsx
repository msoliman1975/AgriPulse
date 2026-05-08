import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { listFarms } from "@/api/farms";
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
      <div className="card max-w-2xl" role="status">
        <p className="text-slate-600">{t("actions.loading")}</p>
      </div>
    );
  }
  if (!isError && data && data.items.length > 0) {
    return <Navigate to={`/insights/${data.items[0].id}`} replace />;
  }
  return (
    <div className="card max-w-2xl">
      <h1 className="text-2xl font-semibold text-ap-ink">
        {canCreateFarm ? t("home.noFarmsTitle") : t("home.welcome")}
      </h1>
      <p className="mt-2 text-ap-muted">
        {canCreateFarm ? t("home.noFarmsBody") : t("home.comingSoon")}
      </p>
      {canCreateFarm ? (
        <Link
          to="/farms/new"
          className="mt-4 inline-flex items-center rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary"
        >
          {t("home.createFirstFarm")}
        </Link>
      ) : null}
    </div>
  );
}
