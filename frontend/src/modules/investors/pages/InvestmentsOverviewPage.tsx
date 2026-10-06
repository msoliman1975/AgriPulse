import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { getInvestmentsOverview } from "@/api/investors";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Card } from "@/components/Card";
import { KPICard } from "@/components/KPICard";
import { KPIRow } from "@/components/KPIRow";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { queryState } from "@/components/asyncState";
import { localizedName } from "@/lib/localizedField";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";

/** /investments/overview/:farmId — the selected farm's investments. */
export function InvestmentsOverviewPage(): JSX.Element {
  const { farmId = "" } = useParams<{ farmId: string }>();
  const { t, i18n } = useTranslation("investors");
  const q = useQuery({
    queryKey: ["investments", "overview", farmId],
    queryFn: () => getInvestmentsOverview(farmId),
    enabled: Boolean(farmId),
  });

  return (
    <Page>
      <PageHeader title={t("overview.title")} subtitle={t("overview.subtitle")} />
      <AsyncBoundary
        state={queryState(q)}
        errorMessage={t("error.load")}
        isEmpty={() => false}
        empty={null}
      >
        {(o) => (
          <div className="flex flex-col gap-6">
            <KPIRow columns={4}>
              <KPICard title={t("overview.kpiInvestors")} value={o.investors} />
              <KPICard
                title={t("overview.kpiSold")}
                value={o.farm.sold}
                hint={`${t("overview.kpiForSale")}: ${o.farm.for_sale}`}
              />
              <KPICard
                title={t("overview.kpiAreaSold")}
                value={<AreaDisplay areaM2={Number(o.farm.area_sold_m2)} />}
              />
              <KPICard
                title={t("overview.kpiAreaNotSold")}
                value={<AreaDisplay areaM2={Number(o.farm.area_not_sold_m2)} />}
              />
            </KPIRow>
            {o.all_farms.farms > 1 ? (
              <p className="text-sm text-ap-muted">
                {t("farmContext.allFarms", {
                  farms: o.all_farms.farms,
                  sold: o.all_farms.sold,
                })}{" "}
                · <AreaDisplay areaM2={Number(o.all_farms.area_sold_m2)} />
              </p>
            ) : null}

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
