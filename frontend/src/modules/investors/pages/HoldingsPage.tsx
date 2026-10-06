import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { listFarms } from "@/api/farms";
import { getFarmHoldingsMap, type HoldingStatus } from "@/api/investors";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { Toolbar } from "@/components/Toolbar";
import { queryState } from "@/components/asyncState";
import { localizedName } from "@/lib/localizedField";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";
import { useCapability } from "@/rbac/useCapability";
import { FarmHoldingsMap } from "../components/FarmHoldingsMap";
import { HOLDING_STATUS_PILL, formatPct } from "../lib";

const STATUSES: HoldingStatus[] = ["draft", "available", "sold"];
const SELECT_CLASS = "rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink";

/** /investments/holdings?farm=… — one farm's blocks and holdings, map and list. */
export function HoldingsPage(): JSX.Element {
  const { t, i18n } = useTranslation("investors");
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const canManage = useCapability("holding.manage");

  const farmsQ = useQuery({
    queryKey: ["farms", "list-tenant"],
    queryFn: () => listFarms({ limit: 100 }),
    staleTime: 60_000,
  });
  const farmId = params.get("farm") ?? farmsQ.data?.items[0]?.id ?? null;

  const mapQ = useQuery({
    queryKey: ["holdings", "farm-map", farmId],
    queryFn: () => getFarmHoldingsMap(farmId ?? ""),
    enabled: Boolean(farmId),
  });

  const [blockFilter, setBlockFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<HoldingStatus | "">("");
  const [ownerFilter, setOwnerFilter] = useState("");
  const [picking, setPicking] = useState(false);
  const [pickedBlock, setPickedBlock] = useState<string | null>(null);

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
  const picked = blocks.find((b) => b.id === pickedBlock) ?? null;
  const filtered = Boolean(blockFilter || statusFilter || ownerFilter);

  const changeFarm = (id: string): void => {
    setParams({ farm: id });
    setBlockFilter("");
    setOwnerFilter("");
    setPicking(false);
    setPickedBlock(null);
  };

  return (
    <Page width="wide">
      <PageHeader
        title={t("holdingsPage.title")}
        subtitle={t("holdingsPage.subtitle")}
        actions={
          canManage && farmId ? (
            <Button
              onClick={() => {
                setPicking(true);
                setPickedBlock(null);
              }}
            >
              {t("holdingsPage.new")}
            </Button>
          ) : null
        }
      />
      <Toolbar
        right={
          <label className="flex items-center gap-2 text-sm">
            <span className="text-ap-muted">{t("holdingsPage.farm")}</span>
            <select
              className={SELECT_CLASS}
              value={farmId ?? ""}
              onChange={(e) => changeFarm(e.target.value)}
            >
              {(farmsQ.data?.items ?? []).map((f) => (
                <option key={f.id} value={f.id}>
                  {localizedName(i18n.language, f.name, f.name_ar)}
                </option>
              ))}
            </select>
          </label>
        }
      />

      {!farmId && farmsQ.isSuccess ? (
        <EmptyState message={t("holdingsPage.noFarms")} action={null} />
      ) : (
        <AsyncBoundary
          state={queryState(mapQ)}
          errorMessage={t("error.load")}
          isEmpty={() => false}
          empty={null}
        >
          {(data) => (
            <div className="flex flex-col gap-4">
              {picking ? (
                <Card title={t("holdingsPage.pickBlockTitle")}>
                  <p className="text-sm text-ap-muted">{t("holdingsPage.pickBlockHelp")}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <select
                      aria-label={t("holdingsPage.block")}
                      className={SELECT_CLASS}
                      value={pickedBlock ?? ""}
                      onChange={(e) => setPickedBlock(e.target.value || null)}
                    >
                      <option value="">{t("holdingsPage.block")}</option>
                      {blocks.map((b) => (
                        <option key={b.id} value={b.id}>
                          {b.code}
                          {b.name ? ` · ${localizedName(i18n.language, b.name, b.name_ar)}` : ""}
                        </option>
                      ))}
                    </select>
                    <Button
                      disabled={!picked || !picked.eligible}
                      onClick={() =>
                        navigate(`/investments/holdings/${data.farm_id}/blocks/${picked?.id}/new`)
                      }
                    >
                      {t("holdingsPage.continue")}
                    </Button>
                    <Button variant="ghost" onClick={() => setPicking(false)}>
                      {t("holdingsPage.cancel")}
                    </Button>
                  </div>
                  {picked && !picked.eligible ? (
                    <p className="mt-2 text-sm text-ap-warn">
                      {t("holdingsPage.blockNotEligible")}
                    </p>
                  ) : null}
                </Card>
              ) : null}

              <Card>
                <FarmHoldingsMap
                  blocks={data.blocks}
                  holdings={data.holdings}
                  selectedBlockId={picking ? pickedBlock : blockFilter || null}
                  onBlockClick={(id) => (picking ? setPickedBlock(id) : setBlockFilter(id))}
                  onHoldingClick={
                    picking
                      ? undefined
                      : (id) => navigate(`/investments/holdings/${data.farm_id}/${id}`)
                  }
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
                                to={`/investments/investors/${h.current_owner.investor_id}`}
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
                          </Td>
                        </Tr>
                      ))}
                    </Tbody>
                  </Table>
                )}
              </Card>
            </div>
          )}
        </AsyncBoundary>
      )}
    </Page>
  );
}
