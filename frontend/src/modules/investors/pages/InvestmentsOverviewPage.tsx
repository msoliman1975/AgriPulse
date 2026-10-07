import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import {
  getFarmHoldingsMap,
  getInvestmentsOverview,
  listFarmInvestors,
  type FarmHoldingsMap,
  type FarmInvestor,
  type Holding,
} from "@/api/investors";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Card } from "@/components/Card";
import { KPICard } from "@/components/KPICard";
import { KPIRow } from "@/components/KPIRow";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { queryState } from "@/components/asyncState";
import { localizedName } from "@/lib/localizedField";
import { AreaDisplay } from "@/modules/farms/components/AreaDisplay";
import { HOLDING_STATUS_COLOR, INVESTOR_STATUS_PILL, formatPct } from "../lib";

/** The undrawn part of the land bar. */
const UNDRAWN_COLOR = "#e2e8f0";

function pct(part: number, whole: number): number {
  return whole > 0 ? (100 * part) / whole : 0;
}

function sumArea(rows: Holding[]): number {
  return rows.reduce((s, h) => s + Number(h.area_m2), 0);
}

/** Trees in the rows, and how many rows have no tree count typed. */
function sumTrees(rows: Holding[]): { trees: number; unknown: number } {
  let trees = 0;
  let unknown = 0;
  for (const h of rows) {
    if (h.tree_count === null) unknown += 1;
    else trees += h.tree_count;
  }
  return { trees, unknown };
}

export interface OverviewFigures {
  blockArea: number;
  sold: Holding[];
  forSale: Holding[];
  draft: Holding[];
  areaSold: number;
  areaForSale: number;
  areaDraft: number;
  areaUndrawn: number;
  owners: Array<{
    investor: FarmInvestor;
    holdings: Holding[];
    area: number;
    trees: number;
    since: string | null;
  }>;
  withoutHolding: FarmInvestor[];
  blocks: Array<{
    id: string;
    code: string;
    area: number;
    holdings: number;
    sold: number;
    forSale: number;
    draft: number;
    areaSold: number;
  }>;
  blocksWithout: number;
}

/** Everything the page shows that the overview route does not count itself. */
export function overviewFigures(map: FarmHoldingsMap, investors: FarmInvestor[]): OverviewFigures {
  const holdings = map.holdings.filter((h) => h.archived_at === null);
  const sold = holdings.filter((h) => h.current_owner !== null);
  const forSale = holdings.filter((h) => h.current_owner === null && h.status === "available");
  const draft = holdings.filter((h) => h.current_owner === null && h.status === "draft");
  // Same rule as the server: only blocks a holding can be drawn on.
  const blockArea = map.blocks.filter((b) => b.eligible).reduce((s, b) => s + Number(b.area_m2), 0);
  const drawn = sumArea(holdings);

  const byOwner = new Map<string, Holding[]>();
  for (const h of sold) {
    const id = h.current_owner?.investor_id ?? "";
    byOwner.set(id, [...(byOwner.get(id) ?? []), h]);
  }
  const owners = investors
    .filter((i) => byOwner.has(i.id))
    .map((investor) => {
      const own = byOwner.get(investor.id) ?? [];
      const since = own
        .map((h) => h.current_owner?.since ?? "")
        .filter(Boolean)
        .sort()[0];
      return {
        investor,
        holdings: own,
        area: sumArea(own),
        trees: sumTrees(own).trees,
        since: since ?? null,
      };
    })
    .sort((a, b) => b.area - a.area);

  const blocks = map.blocks
    .map((b) => {
      const here = holdings.filter((h) => h.block_id === b.id);
      const soldHere = here.filter((h) => h.current_owner !== null);
      return {
        id: b.id,
        code: b.code,
        area: Number(b.area_m2),
        holdings: here.length,
        sold: soldHere.length,
        forSale: here.filter((h) => h.current_owner === null && h.status === "available").length,
        draft: here.filter((h) => h.current_owner === null && h.status === "draft").length,
        areaSold: sumArea(soldHere),
      };
    })
    .filter((b) => b.holdings > 0)
    .sort((a, b) => b.areaSold - a.areaSold || a.code.localeCompare(b.code));

  return {
    blockArea,
    sold,
    forSale,
    draft,
    areaSold: sumArea(sold),
    areaForSale: sumArea(forSale),
    areaDraft: sumArea(draft),
    areaUndrawn: Math.max(blockArea - drawn, 0),
    owners,
    withoutHolding: investors.filter((i) => i.holdings_in_farm === 0 && i.archived_at === null),
    blocks,
    blocksWithout: map.blocks.filter((b) => b.eligible).length - blocks.length,
  };
}

/** /investments/overview/:farmId — the selected farm's investors and holdings. */
export function InvestmentsOverviewPage(): JSX.Element {
  const { farmId = "" } = useParams<{ farmId: string }>();
  const { t, i18n } = useTranslation("investors");
  const lang = i18n.language;
  const q = useQuery({
    queryKey: ["investments", "overview", farmId],
    queryFn: () => getInvestmentsOverview(farmId),
    enabled: Boolean(farmId),
  });
  const mapQ = useQuery({
    queryKey: ["holdings", "farm-map", farmId],
    queryFn: () => getFarmHoldingsMap(farmId),
    enabled: Boolean(farmId),
  });
  const invQ = useQuery({
    queryKey: ["investors", "farm", farmId, "overview"],
    queryFn: () => listFarmInvestors(farmId),
    enabled: Boolean(farmId),
  });
  const figures = useMemo(
    () => (mapQ.data && invQ.data ? overviewFigures(mapQ.data, invQ.data) : null),
    [mapQ.data, invQ.data],
  );

  const investorLabel = (code: string, name: string, nameAr: string | null): string =>
    `${code} · ${localizedName(lang, name, nameAr)}`;

  return (
    <Page width="wide">
      <PageHeader title={t("overview.title")} subtitle={t("overview.subtitle")} />
      <AsyncBoundary
        state={queryState(q)}
        errorMessage={t("error.load")}
        isEmpty={() => false}
        empty={null}
      >
        {(o) => {
          const f = figures;
          const allTrees = f ? sumTrees([...f.sold, ...f.forSale, ...f.draft]) : null;
          const soldTrees = f ? sumTrees(f.sold) : null;
          const noLogin = f ? f.owners.filter((r) => r.investor.status === "not_invited") : [];
          return (
            <div className="flex flex-col gap-6">
              <KPIRow columns={4}>
                <KPICard
                  title={t("overview.kpiInvestors")}
                  value={o.investors}
                  hint={
                    f && f.withoutHolding.length > 0
                      ? t("overview.kpiInvestorsHint", { count: f.withoutHolding.length })
                      : undefined
                  }
                />
                <KPICard
                  title={t("overview.kpiSold")}
                  value={o.farm.sold}
                  hint={t("overview.kpiSoldHint", {
                    forSale: o.farm.for_sale,
                    draft: o.farm.draft,
                  })}
                />
                <KPICard
                  title={t("overview.kpiAreaSold")}
                  value={<AreaDisplay areaM2={Number(o.farm.area_sold_m2)} />}
                  hint={
                    f
                      ? t("overview.kpiAreaSoldHint", {
                          pct: formatPct(pct(f.areaSold, f.blockArea).toFixed(2), lang),
                        })
                      : undefined
                  }
                />
                <KPICard
                  title={t("overview.kpiTreesSold")}
                  value={soldTrees ? soldTrees.trees : "—"}
                  hint={
                    allTrees
                      ? t("overview.kpiTreesHint", { total: allTrees.trees }) +
                        (soldTrees && soldTrees.unknown > 0
                          ? ` · ${t("overview.treesUnknown", { count: soldTrees.unknown })}`
                          : "")
                      : undefined
                  }
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

              {f ? (
                <>
                  <Card title={t("overview.landTitle")}>
                    <LandBar f={f} />
                  </Card>

                  <Card title={t("overview.investorsTitle")} noPadding>
                    {f.owners.length === 0 ? (
                      <p className="p-4 text-sm text-ap-muted">{t("overview.investorsEmpty")}</p>
                    ) : (
                      <Table>
                        <Thead>
                          <Tr>
                            <Th>{t("overview.colInvestor")}</Th>
                            <Th>{t("overview.colHoldings")}</Th>
                            <Th>{t("overview.colArea")}</Th>
                            <Th>{t("overview.colShareSold")}</Th>
                            <Th>{t("overview.colTrees")}</Th>
                            <Th>{t("overview.colSince")}</Th>
                            <Th>{t("overview.colLogin")}</Th>
                          </Tr>
                        </Thead>
                        <Tbody>
                          {f.owners.map((r) => (
                            <Tr key={r.investor.id}>
                              <Td>
                                <Link
                                  className="text-ap-primary hover:underline"
                                  to={`/investments/investors/${farmId}/${r.investor.id}`}
                                >
                                  {investorLabel(
                                    r.investor.code,
                                    r.investor.full_name,
                                    r.investor.full_name_ar,
                                  )}
                                </Link>
                                {r.investor.other_farm_holdings > 0 ? (
                                  <span className="ms-2 text-xs text-ap-muted">
                                    {t("farmContext.otherFarmsShort", {
                                      count: r.investor.other_farm_holdings,
                                    })}
                                  </span>
                                ) : null}
                              </Td>
                              <Td>
                                <span className="font-mono text-xs">
                                  {r.holdings.map((h) => h.code).join(", ")}
                                </span>
                              </Td>
                              <Td>
                                <AreaDisplay areaM2={r.area} fractionDigits={2} />
                              </Td>
                              <Td>{formatPct(pct(r.area, f.areaSold).toFixed(1), lang)}%</Td>
                              <Td>{r.trees}</Td>
                              <Td className="whitespace-nowrap">{r.since ?? "—"}</Td>
                              <Td>
                                <Pill kind={INVESTOR_STATUS_PILL[r.investor.status]}>
                                  {t(`status.${r.investor.status}`)}
                                </Pill>
                              </Td>
                            </Tr>
                          ))}
                        </Tbody>
                      </Table>
                    )}
                    {f.withoutHolding.length > 0 || noLogin.length > 0 ? (
                      <div className="flex flex-col gap-1 border-t border-ap-line p-4 text-sm text-ap-muted">
                        {f.withoutHolding.length > 0 ? (
                          <p>
                            {t("overview.withoutHolding", { count: f.withoutHolding.length })}{" "}
                            {f.withoutHolding.map((i, n) => (
                              <span key={i.id}>
                                {n > 0 ? ", " : ""}
                                <Link
                                  className="text-ap-primary hover:underline"
                                  to={`/investments/investors/${farmId}/${i.id}`}
                                >
                                  {investorLabel(i.code, i.full_name, i.full_name_ar)}
                                </Link>
                              </span>
                            ))}
                          </p>
                        ) : null}
                        {noLogin.length > 0 ? (
                          <p>{t("overview.withoutLogin", { count: noLogin.length })}</p>
                        ) : null}
                      </div>
                    ) : null}
                  </Card>

                  <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                    <Card title={t("overview.blocksTitle")} noPadding>
                      {f.blocks.length === 0 ? (
                        <p className="p-4 text-sm text-ap-muted">{t("overview.blocksEmpty")}</p>
                      ) : (
                        <Table>
                          <Thead>
                            <Tr>
                              <Th>{t("col.block")}</Th>
                              <Th>{t("overview.colHoldingsCount")}</Th>
                              <Th>{t("overview.colAreaSold")}</Th>
                              <Th>{t("overview.colBlockSold")}</Th>
                            </Tr>
                          </Thead>
                          <Tbody>
                            {f.blocks.map((b) => (
                              <Tr key={b.id}>
                                <Td className="font-mono">{b.code}</Td>
                                <Td className="whitespace-nowrap">
                                  {b.holdings}
                                  <span className="ms-1 text-xs text-ap-muted">
                                    (
                                    {t("overview.blockSplit", {
                                      sold: b.sold,
                                      forSale: b.forSale,
                                      draft: b.draft,
                                    })}
                                    )
                                  </span>
                                </Td>
                                <Td>
                                  <AreaDisplay areaM2={b.areaSold} fractionDigits={2} />
                                </Td>
                                <Td>{formatPct(pct(b.areaSold, b.area).toFixed(1), lang)}%</Td>
                              </Tr>
                            ))}
                          </Tbody>
                        </Table>
                      )}
                      {f.blocksWithout > 0 ? (
                        <p className="border-t border-ap-line p-4 text-sm text-ap-muted">
                          {t("overview.blocksWithout", { count: f.blocksWithout })}
                        </p>
                      ) : null}
                    </Card>

                    <Card title={t("overview.forSaleTitle")} noPadding>
                      {f.forSale.length === 0 ? (
                        <p className="p-4 text-sm text-ap-muted">{t("overview.forSaleEmpty")}</p>
                      ) : (
                        <Table>
                          <Thead>
                            <Tr>
                              <Th>{t("col.code")}</Th>
                              <Th>{t("col.name")}</Th>
                              <Th>{t("col.block")}</Th>
                              <Th>{t("col.area")}</Th>
                              <Th>{t("overview.colTrees")}</Th>
                            </Tr>
                          </Thead>
                          <Tbody>
                            {[...f.forSale]
                              .sort((a, b) => a.code.localeCompare(b.code))
                              .map((h) => (
                                <Tr key={h.id}>
                                  <Td>
                                    <Link
                                      className="font-mono text-ap-primary hover:underline"
                                      to={`/investments/holdings/${farmId}/${h.id}`}
                                    >
                                      {h.code}
                                    </Link>
                                  </Td>
                                  <Td>{localizedName(lang, h.name, h.name_ar)}</Td>
                                  <Td className="font-mono">{h.block_code ?? "—"}</Td>
                                  <Td>
                                    <AreaDisplay areaM2={Number(h.area_m2)} fractionDigits={2} />
                                  </Td>
                                  <Td>{h.tree_count ?? "—"}</Td>
                                </Tr>
                              ))}
                          </Tbody>
                        </Table>
                      )}
                      {f.draft.length > 0 ? (
                        <p className="border-t border-ap-line p-4 text-sm text-ap-muted">
                          {t("overview.draftNote", { count: f.draft.length })}
                        </p>
                      ) : null}
                    </Card>
                  </div>
                </>
              ) : mapQ.isError || invQ.isError ? (
                <p role="alert" className="text-sm text-ap-crit">
                  {t("error.load")}
                </p>
              ) : null}

              <Card title={t("overview.recentTitle")}>
                {o.recent.length === 0 ? (
                  <p className="text-sm text-ap-muted">{t("overview.recentEmpty")}</p>
                ) : (
                  <ul className="flex flex-col gap-2 text-sm">
                    {o.recent.map((r) => {
                      const investor = investorLabel(
                        r.investor_code,
                        r.investor_name,
                        r.investor_name_ar,
                      );
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
                          <span className="text-ap-muted">
                            ({t(`acquiredBy.${r.acquired_by}`)})
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </Card>
            </div>
          );
        }}
      </AsyncBoundary>
    </Page>
  );
}

/** The farm's holding-eligible block area, split by what is drawn on it. */
function LandBar({ f }: { f: OverviewFigures }): JSX.Element {
  const { t, i18n } = useTranslation("investors");
  const parts = [
    { key: "sold", area: f.areaSold, color: HOLDING_STATUS_COLOR.sold },
    { key: "forSale", area: f.areaForSale, color: HOLDING_STATUS_COLOR.available },
    { key: "draft", area: f.areaDraft, color: HOLDING_STATUS_COLOR.draft },
    { key: "undrawn", area: f.areaUndrawn, color: UNDRAWN_COLOR },
  ];
  return (
    <div className="flex flex-col gap-3">
      <div
        className="flex h-4 w-full overflow-hidden rounded-full bg-ap-line"
        role="img"
        aria-label={t("overview.landTitle")}
      >
        {parts.map((p) =>
          p.area > 0 ? (
            <div
              key={p.key}
              style={{ width: `${pct(p.area, f.blockArea)}%`, backgroundColor: p.color }}
            />
          ) : null,
        )}
      </div>
      <ul className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {parts.map((p) => (
          <li key={p.key} className="flex items-start gap-2">
            <span
              className="mt-1 inline-block h-3 w-3 shrink-0 rounded-sm"
              style={{ backgroundColor: p.color }}
              aria-hidden
            />
            <span>
              <span className="block text-ap-muted">{t(`overview.land.${p.key}`)}</span>
              <span className="text-ap-ink">
                <AreaDisplay areaM2={p.area} fractionDigits={2} /> ·{" "}
                {formatPct(pct(p.area, f.blockArea).toFixed(1), i18n.language)}%
              </span>
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-ap-muted">
        {t("overview.landNote")} <AreaDisplay areaM2={f.blockArea} fractionDigits={2} />
      </p>
    </div>
  );
}
