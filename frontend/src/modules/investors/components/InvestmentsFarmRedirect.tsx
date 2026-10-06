import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import { listFarms } from "@/api/farms";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/Skeleton";

/**
 * A bare Investments path (no farm in it) goes to the same section for the
 * first farm. After that the farm in the top bar decides, as everywhere else.
 */
export function InvestmentsFarmRedirect({
  section,
}: {
  section: "overview" | "holdings" | "investors";
}): JSX.Element {
  const { t } = useTranslation("investors");
  const farms = useQuery({
    queryKey: ["farms", "list-tenant"],
    queryFn: () => listFarms({ limit: 100 }),
    staleTime: 60_000,
  });
  if (farms.isLoading) return <Skeleton className="m-6 h-32 rounded-xl" />;
  const first = farms.data?.items[0]?.id;
  if (!first) return <EmptyState message={t("farmContext.noFarms")} action={null} />;
  return <Navigate to={`/investments/${section}/${first}`} replace />;
}
