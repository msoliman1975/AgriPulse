import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { getFarmHoldingsMap, type HoldingStatus } from "@/api/investors";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { queryState } from "@/components/asyncState";
import { localizedName } from "@/lib/localizedField";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";
import { useCapability } from "@/rbac/useCapability";
import { DeleteHoldingButton } from "../components/DeleteHoldingButton";
import { FarmHoldingsMap } from "../components/FarmHoldingsMap";
import { HOLDING_STATUS_PILL, formatPct } from "../lib";

const STATUSES: HoldingStatus[] = ["draft", "available", "sold"];
const SELECT_CLASS = "rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink";

/** /investments/holdings/:farmId — the top-bar farm's blocks and holdings, map and list. */
export function HoldingsPage(): JSX.Element {
  const { t, i18n } = useTranslation("investors");
  const navigate = useNavigate();
  const { farmId = "" } = useParams<{ farmId: string }>();
  const canManage = useCapability("holding.manage", { farmId });

  const mapQ = useQuery({
    queryKey: ["holdings", "farm-map", farmId],
    queryFn: () => getFarmHoldingsMap(farmId),
    enabled: Boolean(farmId),
  });

  const [blockFilter, setBlockFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<HoldingStatus | "">("");
  const [ownerFilter, setOwnerFilter] = useState("");

  const owners = useMemo(() => {
    const seen = new Map<string, string>();
    for (const h of mapQ.data?.holdings ?? []) {
      const o = h.current_owner;
      if (o && !seen.has(o.investor_id)) {
        seen.set(
          o.investor_id,
          `${o.investor_code} · ${localizedName(i18n.language, o.investor_name, o.investor_name_ar)}`,
        );
      }
    }
    return [...seen.entries()];
  }, [mapQ.data, i18n.language]);

  const rows = useMemo(
    () =>
      (mapQ.data?.holdings ?? []).filter(
        (h) =>
          (!blockFilter || h.block_id === blockFilter) &&
          (!statusFilter || h.status === statusFilter) &&
          (!ownerFilter || h.current_owner?.investor_id === ownerFilter),
      ),
    [mapQ.data, blockFilter, statusFilter, ownerFilter],
  );

  const blocks = mapQ.data?.blocks ?? [];
  const filtered = Boolean(blockFilter || statusFilter || ownerFilter);

  return (
    <Page width="wide">
      <PageHeader
        title={t("holdingsPage.title")}
        subtitle={t("holdingsPage.subtitle")}
        actions={
          canManage && farmId ? (
            <Button onClick={() => navigate(`/investments/holdings/${farmId}/new`)}>
              {t("holdingsPage.new")}
            </Button>
          ) : null
        }
      />
      <AsyncBoundary
        state={queryState(mapQ)}
        errorMessage={t("error.load")}
        isEmpty={() => false}
        empty={null}
      >
        {(data) => (
          <div className="flex flex-col gap-4">
            <Card>
              <FarmHoldingsMap
                blocks={data.blocks}
                holdings={data.holdings}
                selectedBlockId={blockFilter || null}
                onBlockClick={setBlockFilter}
                onHoldingClick={(id) => navigate(`/investments/holdings/${data.farm_id}/${id}`)}
              />
              <p className="mt-2 text-xs text-ap-muted">{t("holdingsPage.mapHelp")}</p>
            </Card>

            <div className="flex flex-wrap items-center gap-2">
              <select
                aria-label={t("holdingsPage.block")}
                className={SELECT_CLASS}
                value={blockFilter}
                onChange={(e) => setBlockFilter(e.target.value)}
              >
                <option value="">{t("holdingsPage.allBlocks")}</option>
                {blocks.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.code}
                  </option>
                ))}
              </select>
              <select
                aria-label={t("col.status")}
                className={SELECT_CLASS}
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as HoldingStatus | "")}
              >
                <option value="">{t("holdingsPage.allStatuses")}</option>
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {t(`holdingStatus.${s}`)}
                  </option>
                ))}
              </select>
              <select
                aria-label={t("col.owner")}
                className={SELECT_CLASS}
                value={ownerFilter}
                onChange={(e) => setOwnerFilter(e.target.value)}
              >
                <option value="">{t("holdingsPage.allInvestors")}</option>
                {owners.map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </div>

            <Card noPadding>
              {rows.length === 0 ? (
                <p className="p-4 text-sm text-ap-muted">
                  {filtered ? t("holdingsPage.emptyFiltered") : t("holdingsPage.empty")}
                </p>
              ) : (
                <Table>
                  <Thead>
                    <Tr>
                      <Th>{t("col.code")}</Th>
                      <Th>{t("col.name")}</Th>
                      <Th>{t("col.block")}</Th>
                      <Th>{t("col.area")}</Th>
                      <Th>{t("col.share")}</Th>
                      <Th>{t("col.status")}</Th>
                      <Th>{t("col.owner")}</Th>
                      {canManage ? <Th>{t("holdingsPage.actions")}</Th> : null}
                    </Tr>
                  </Thead>
                  <Tbody>
                    {rows.map((h) => (
                      <Tr key={h.id}>
                        <Td>
                          <Link
                            className="font-mono text-ap-primary hover:underline"
                            to={`/investments/holdings/${h.farm_id}/${h.id}`}
                          >
                            {h.code}
                          </Link>
                        </Td>
                        <Td>{localizedName(i18n.language, h.name, h.name_ar)}</Td>
                        <Td className="font-mono">{h.block_code ?? "—"}</Td>
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
                          {h.current_owner ? (
                            <Link
                              className="hover:underline"
                              to={`/investments/investors/${farmId}/${h.current_owner.investor_id}`}
                            >
                              {h.current_owner.investor_code} ·{" "}
                              {localizedName(
                                i18n.language,
                                h.current_owner.investor_name,
                                h.current_owner.investor_name_ar,
                              )}
                            </Link>
                          ) : (
                            "—"
                          )}
                          {h.current_owner && h.current_owner.other_farm_holdings > 0 ? (
                            <span className="ms-2 text-xs text-ap-muted">
                              {t("farmContext.otherFarmsShort", {
                                count: h.current_owner.other_farm_holdings,
                              })}
                            </span>
                          ) : null}
                        </Td>
                        {canManage ? (
                          <Td>
                            {h.has_ownership_history ? (
                              <span
                                className="text-xs text-ap-muted"
                                title={t("holdingsPage.cannotDelete")}
                              >
                                —
                              </span>
                            ) : (
                              <DeleteHoldingButton farmId={farmId} holdingId={h.id} code={h.code} />
                            )}
                          </Td>
                        ) : null}
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              )}
            </Card>
          </div>
        )}
      </AsyncBoundary>
    </Page>
  );
}
