import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { listBlocks, type Block } from "@/api/blocks";
import { Card } from "@/components/Card";
import { localizedName } from "@/lib/localizedField";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";

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
    <Card noPadding aria-labelledby="land-unit-heading">
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
          <Table>
            <Thead className="text-[11px]">
              <Tr>
                <Th>{t("landUnits.col.name")}</Th>
                <Th>{t("landUnits.col.type")}</Th>
                <Th>{t("landUnits.col.area")}</Th>
                <Th>{t("landUnits.col.status")}</Th>
                <Th className="text-end">{t("landUnits.col.action")}</Th>
              </Tr>
            </Thead>
            <Tbody>
              {blocks.map((b) => (
                <Row key={b.id} block={b} farmId={farmId} />
              ))}
            </Tbody>
          </Table>
        )}
      </div>
    </Card>
  );
}

function Row({ block: b, farmId }: { block: Block; farmId: string }): ReactNode {
  const { t, i18n } = useTranslation("insights");
  const navigate = useNavigate();
  const status: "ok" | "neutral" = b.is_active ? "ok" : "neutral";
  const statusLabel = b.is_active ? t("landUnits.status.active") : t("landUnits.status.inactive");
  return (
    <Tr className="hover:bg-ap-line/20">
      <Td>
        <div className="text-ap-ink">
          {localizedName(i18n.language, b.name ?? b.code, b.name_ar)}
        </div>
        <div className="text-[11px] text-ap-muted">
          {b.code}
          {b.irrigation_system ? ` · ${b.irrigation_system}` : ""}
        </div>
      </Td>
      <Td>{t(`unitType.${b.unit_type}`)}</Td>
      <Td>
        {b.area_value.toFixed(1)} {b.area_unit}
      </Td>
      <Td>
        <Pill kind={status}>{statusLabel}</Pill>
      </Td>
      <Td className="text-end">
        <button
          type="button"
          onClick={() => navigate(`/board/${farmId}?lane=${b.id}`)}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
        >
          {t("landUnits.plan")}
        </button>
      </Td>
    </Tr>
  );
}
