import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { listBlocks, type Block } from "@/api/blocks";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";

interface Props {
  farmId: string;
}

export function LandUnitHealthTable({ farmId }: Props): ReactNode {
  const { t } = useTranslation("insights");
  const navigate = useNavigate();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["blocks", "list", farmId] as const,
    queryFn: () => listBlocks(farmId),
    enabled: Boolean(farmId),
  });
  const blocks = data?.items ?? [];

  return (
    <section
      aria-labelledby="land-unit-heading"
      className="rounded-xl border border-ap-line bg-ap-panel"
    >
      <header className="flex items-baseline justify-between p-4 pb-2">
        <h2
          id="land-unit-heading"
          className="text-sm font-semibold uppercase tracking-wider text-ap-muted"
        >
          {t("landUnits.title")}
        </h2>
        <button
          type="button"
          onClick={() => navigate(`/farms/${farmId}`)}
          className="text-xs font-medium text-ap-primary hover:underline"
        >
          {t("landUnits.manage")}
        </button>
      </header>
      <div className="overflow-x-auto">
        {isLoading ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </div>
        ) : isError ? (
          <p className="p-4 text-sm text-ap-crit">{t("landUnits.loadFailed")}</p>
        ) : blocks.length === 0 ? (
          <p className="p-6 text-center text-sm text-ap-muted">{t("landUnits.empty")}</p>
        ) : (
          <table className="w-full text-start text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-ap-muted">
              <tr>
                <th className="px-4 py-2 text-start font-semibold">{t("landUnits.col.name")}</th>
                <th className="px-4 py-2 text-start font-semibold">{t("landUnits.col.type")}</th>
                <th className="px-4 py-2 text-start font-semibold">{t("landUnits.col.area")}</th>
                <th className="px-4 py-2 text-start font-semibold">{t("landUnits.col.status")}</th>
                <th className="px-4 py-2 text-end font-semibold">{t("landUnits.col.action")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ap-line">
              {blocks.map((b) => (
                <Row key={b.id} block={b} farmId={farmId} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

function Row({ block: b, farmId }: { block: Block; farmId: string }): ReactNode {
  const { t } = useTranslation("insights");
  const navigate = useNavigate();
  const status: "ok" | "neutral" = b.is_active ? "ok" : "neutral";
  const statusLabel = b.is_active ? t("landUnits.status.active") : t("landUnits.status.inactive");
  return (
    <tr className="hover:bg-ap-line/20">
      <td className="px-4 py-2">
        <div className="text-ap-ink">{b.name ?? b.code}</div>
        <div className="text-[11px] text-ap-muted">
          {b.code}
          {b.irrigation_system ? ` · ${b.irrigation_system}` : ""}
        </div>
      </td>
      <td className="px-4 py-2 text-ap-muted">{t(`unitType.${b.unit_type}`)}</td>
      <td className="px-4 py-2 text-ap-muted">
        {b.area_value.toFixed(1)} {b.area_unit}
      </td>
      <td className="px-4 py-2">
        <Pill kind={status}>{statusLabel}</Pill>
      </td>
      <td className="px-4 py-2 text-end">
        <button
          type="button"
          onClick={() => navigate(`/board/${farmId}?lane=${b.id}`)}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
        >
          {t("landUnits.plan")}
        </button>
      </td>
    </tr>
  );
}
