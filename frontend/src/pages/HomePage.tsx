import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { listFarms } from "@/api/farms";

export function HomePage(): ReactNode {
  const { t } = useTranslation("common");
  // Redirect to /insights/<first-farm-id> when the user has at least one
  // farm — that's the AgriPulse landing convention. Pre-FarmDM users with
  // no farms see the legacy welcome card.
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
      <h1 className="text-2xl font-semibold text-ap-ink">{t("home.welcome")}</h1>
      <p className="mt-2 text-ap-muted">{t("home.comingSoon")}</p>
    </div>
  );
}
