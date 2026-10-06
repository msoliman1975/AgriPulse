import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { getInvestmentsOverview } from "@/api/investors";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { KPICard } from "@/components/KPICard";
import { KPIRow } from "@/components/KPIRow";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { queryState } from "@/components/asyncState";
import { localizedName } from "@/lib/localizedField";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";

/** /investments — counts and areas across all farms, and the latest sales. */
export function InvestmentsOverviewPage(): JSX.Element {
  const { t, i18n } = useTranslation("investors");
  const q = useQuery({ queryKey: ["investments", "overview"], queryFn: getInvestmentsOverview });

  return (
    <Page>
      <PageHeader title={t("overview.title")} subtitle={t("overview.subtitle")} />
      <AsyncBoundary
        state={queryState(q)}
        errorMessage={t("error.load")}
        isEmpty={(o) => o.farms.length === 0}
        empty={<EmptyState message={t("overview.empty")} action={null} />}
      >
        {(o) => (
          <div className="flex flex-col gap-6">
            <KPIRow columns={4}>
              <KPICard title={t("overview.kpiInvestors")} value={o.investors} />
              <KPICard
                title={t("overview.kpiSold")}
                value={o.sold}
                hint={`${t("overview.kpiForSale")}: ${o.for_sale}`}
              />
              <KPICard
                title={t("overview.kpiAreaSold")}
                value={<AreaDisplay areaM2={Number(o.area_sold_m2)} />}
              />
              <KPICard
                title={t("overview.kpiAreaNotSold")}
                value={<AreaDisplay areaM2={Number(o.area_not_sold_m2)} />}
              />
            </KPIRow>

            <Card title={t("overview.farmsTitle")} noPadding>
              <Table>
                <Thead>
                  <Tr>
                    <Th>{t("overview.colFarm")}</Th>
                    <Th>{t("overview.colHoldings")}</Th>
                    <Th>{t("overview.colSold")}</Th>
                    <Th>{t("overview.colForSale")}</Th>
                    <Th>{t("overview.colAreaSold")}</Th>
                    <Th>{t("overview.colAreaNotSold")}</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {o.farms.map((f) => (
                    <Tr key={f.farm_id}>
                      <Td>
                        <Link
                          className="text-ap-primary hover:underline"
                          to={`/investments/holdings?farm=${f.farm_id}`}
                        >
                          {localizedName(i18n.language, f.farm_name, f.farm_name_ar)}
                        </Link>
                      </Td>
                      <Td>{f.holdings}</Td>
                      <Td>{f.sold}</Td>
                      <Td>{f.for_sale}</Td>
                      <Td>
                        <AreaDisplay areaM2={Number(f.area_sold_m2)} />
                      </Td>
                      <Td>
                        <AreaDisplay areaM2={Number(f.area_not_sold_m2)} />
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </Card>

            <Card title={t("overview.recentTitle")}>
              {o.recent.length === 0 ? (
                <p className="text-sm text-ap-muted">{t("overview.recentEmpty")}</p>
              ) : (
                <ul className="flex flex-col gap-2 text-sm">
                  {o.recent.map((r) => {
                    const investor = `${r.investor_code} · ${localizedName(
                      i18n.language,
                      r.investor_name,
                      r.investor_name_ar,
                    )}`;
                    return (
                      <li key={r.id} className="flex flex-wrap items-baseline gap-x-3">
                        <span className="w-24 text-ap-muted">{r.start_date}</span>
                        <Link
                          className="text-ap-primary hover:underline"
                          to={`/investments/holdings/${r.farm_id}/${r.holding_id}`}
                        >
                          {r.previous_investor_code
                            ? t("overview.recentTransfer", {
                                holding: r.holding_code,
                                from: r.previous_investor_code,
                                to: investor,
                              })
                            : t("overview.recentNew", { holding: r.holding_code, investor })}
                        </Link>
                        <span className="text-ap-muted">({t(`acquiredBy.${r.acquired_by}`)})</span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>
          </div>
        )}
      </AsyncBoundary>
    </Page>
  );
}
