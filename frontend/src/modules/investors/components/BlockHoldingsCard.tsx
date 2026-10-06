import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { getBlockHoldings } from "@/api/investors";
import { Card } from "@/components/Card";
import { LinkButton } from "@/components/LinkButton";
import { Pill } from "@/components/Pill";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { localizedName } from "@/lib/localizedField";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";
import { useCapability } from "@/rbac/useCapability";
import { HOLDING_STATUS_PILL, blockHoldingsKey, errorText, formatPct } from "../lib";
import { HoldingsMap } from "./HoldingsMap";

interface Props {
  farmId: string;
  blockId: string;
}

/** Holdings section of the block page: map, sold/unsold split, and the list. */
export function BlockHoldingsCard({ farmId, blockId }: Props): JSX.Element | null {
  const { t, i18n } = useTranslation("investors");
  const navigate = useNavigate();
  const canRead = useCapability("holding.read", { farmId });
  const canManage = useCapability("holding.manage", { farmId });

  const q = useQuery({
    queryKey: blockHoldingsKey(farmId, blockId),
    queryFn: () => getBlockHoldings(farmId, blockId),
    enabled: canRead,
  });

  if (!canRead) return null;

  return (
    <Card
      title={t("block.title")}
      actions={
        canManage && q.data?.eligible ? (
          <LinkButton to={`/farms/${farmId}/blocks/${blockId}/holdings/new`}>
            {t("block.add")}
          </LinkButton>
        ) : null
      }
    >
      <p className="text-sm text-ap-muted">{t("block.subtitle")}</p>
      {q.isLoading ? (
        <p className="mt-3 text-sm text-ap-muted">…</p>
      ) : q.isError || !q.data ? (
        <p role="alert" className="mt-3 text-sm text-ap-crit">
          {errorText(q.error)}
        </p>
      ) : (
        <div className="mt-3 flex flex-col gap-3">
          {!q.data.eligible && q.data.ineligible_reason ? (
            <p className="rounded-md bg-ap-warn-soft p-2 text-sm text-ap-warn">
              {q.data.ineligible_reason}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-4 text-sm">
            <span>
              <span className="text-ap-muted">{t("block.sold")}: </span>
              <AreaDisplay areaM2={Number(q.data.sold_area_m2)} />
            </span>
            <span>
              <span className="text-ap-muted">{t("block.unsold")}: </span>
              <AreaDisplay areaM2={Number(q.data.unsold_area_m2)} />
            </span>
            <span className="text-ap-muted">
              {t("block.count", { count: q.data.holdings.length })}
            </span>
          </div>
          {q.data.holdings.length > 0 ? (
            <>
              <HoldingsMap
                block={q.data.boundary}
                holdings={q.data.holdings}
                onSelect={(id) => navigate(`/farms/${farmId}/holdings/${id}`)}
              />
              <Table>
                <Thead>
                  <Tr>
                    <Th>{t("col.code")}</Th>
                    <Th>{t("col.name")}</Th>
                    <Th>{t("col.area")}</Th>
                    <Th>{t("col.share")}</Th>
                    <Th>{t("col.status")}</Th>
                    <Th>{t("col.owner")}</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {q.data.holdings.map((h) => (
                    <Tr key={h.id}>
                      <Td>
                        <Link
                          className="font-mono text-ap-primary hover:underline"
                          to={`/farms/${farmId}/holdings/${h.id}`}
                        >
                          {h.code}
                        </Link>
                      </Td>
                      <Td>{localizedName(i18n.language, h.name, h.name_ar)}</Td>
                      <Td>
                        <AreaDisplay areaM2={Number(h.area_m2)} fractionDigits={2} />
                      </Td>
                      <Td>{formatPct(h.share_pct, i18n.language)}%</Td>
                      <Td>
                        <Pill kind={HOLDING_STATUS_PILL[h.status]}>
                          {t(`holdingStatus.${h.status}`)}
                        </Pill>
                      </Td>
                      <Td>
                        {h.current_owner
                          ? localizedName(
                              i18n.language,
                              h.current_owner.investor_name,
                              h.current_owner.investor_name_ar,
                            )
                          : "—"}
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </>
          ) : (
            <p className="text-sm text-ap-muted">{t("block.empty")}</p>
          )}
        </div>
      )}
    </Card>
  );
}
