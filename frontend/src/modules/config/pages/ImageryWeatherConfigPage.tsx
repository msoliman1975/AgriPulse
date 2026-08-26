import { useQueries, useQuery } from "@tanstack/react-query";
import { formatDistanceToNow, parseISO } from "date-fns";
import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate } from "react-router-dom";

import { listBlocks, type Block } from "@/api/blocks";
import {
  listSubscriptions as listImagerySubs,
  type Subscription as ImagerySubscription,
} from "@/api/imagery";
import {
  listSubscriptions as listWeatherSubs,
  type Subscription as WeatherSubscription,
} from "@/api/weather";
import { Card } from "@/components/Card";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { useConfig } from "@/config/ConfigContext";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useDateLocale } from "@/hooks/useDateLocale";
import { localizedName } from "@/lib/localizedField";

export function ImageryWeatherConfigPage(): ReactNode {
  const farmId = useActiveFarmId();
  const { t } = useTranslation("imageryWeatherConfig");
  const config = useConfig();

  const blocksQuery = useQuery({
    queryKey: ["blocks", "list", farmId] as const,
    queryFn: () => listBlocks(farmId!),
    enabled: Boolean(farmId),
  });

  if (!farmId) {
    return <Navigate to="/" replace />;
  }

  return (
    <Page>
      <header>
        <PageHeader title={t("page.title")} subtitle={t("page.subtitle")} />
      </header>

      <Card noPadding className="p-4">
        <h2 className="text-sm font-semibold text-ap-ink">{t("platform.heading")}</h2>
        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div className="flex items-center justify-between gap-2 border-b border-ap-line pb-2 sm:border-0 sm:pb-0">
            <dt className="text-ap-muted">{t("platform.vizCloudCover")}</dt>
            <dd className="font-mono text-ap-ink">≤ {config.cloud_cover_visualization_max_pct}%</dd>
          </div>
          <div className="flex items-center justify-between gap-2 border-b border-ap-line pb-2 sm:border-0 sm:pb-0">
            <dt className="text-ap-muted">{t("platform.aggCloudCover")}</dt>
            <dd className="font-mono text-ap-ink">≤ {config.cloud_cover_aggregation_max_pct}%</dd>
          </div>
        </dl>
        <div className="mt-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-ap-muted">
            {t("platform.products")}
          </h3>
          {config.products.length === 0 ? (
            <p className="mt-1 text-sm text-ap-muted">{t("platform.productsEmpty")}</p>
          ) : (
            <ul className="mt-2 flex flex-wrap gap-2">
              {config.products.map((p) => (
                <li key={p.product_id}>
                  <Pill kind="info">
                    <span className="font-mono">{p.product_code}</span> · {p.product_name}
                  </Pill>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      <Card noPadding>
        <header className="flex items-center justify-between border-b border-ap-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ap-ink">{t("blocks.heading")}</h2>
          <span className="text-xs text-ap-muted">{blocksQuery.data?.items.length ?? 0}</span>
        </header>
        {blocksQuery.isLoading ? (
          <div className="flex flex-col gap-2 p-4">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : blocksQuery.isError ? (
          <p className="p-4 text-sm text-ap-crit">{t("blocks.loadFailed")}</p>
        ) : !blocksQuery.data || blocksQuery.data.items.length === 0 ? (
          <p className="p-12 text-center text-sm text-ap-muted">{t("blocks.empty")}</p>
        ) : (
          <BlocksTable farmId={farmId} blocks={blocksQuery.data.items} />
        )}
      </Card>
    </Page>
  );
}

function BlocksTable({ farmId, blocks }: { farmId: string; blocks: Block[] }): ReactNode {
  const { t, i18n } = useTranslation("imageryWeatherConfig");
  const dateLocale = useDateLocale();

  // Fan out one imagery + one weather query per block. Ten blocks ⇒ 20
  // queries; tanstack batches the network round-trips and the cache key is
  // unique per block so subsequent visits hit cache.
  const imagerySubsQueries = useQueries({
    queries: blocks.map((b) => ({
      queryKey: ["imagery", "subscriptions", b.id, "active"] as const,
      queryFn: () => listImagerySubs(b.id),
      staleTime: 30_000,
    })),
  });
  const weatherSubsQueries = useQueries({
    queries: blocks.map((b) => ({
      queryKey: ["weather", "subscriptions", b.id, "active"] as const,
      queryFn: () => listWeatherSubs(b.id),
      staleTime: 30_000,
    })),
  });

  return (
    <div className="overflow-x-auto">
      <Table>
        <Thead>
          <Tr>
            <Th>{t("blocks.table.block")}</Th>
            <Th>{t("blocks.table.imagery")}</Th>
            <Th>{t("blocks.table.lastImagery")}</Th>
            <Th>{t("blocks.table.weather")}</Th>
            <Th>{t("blocks.table.lastWeather")}</Th>
            <Th className="text-end">{t("blocks.table.actions")}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {blocks.map((b, idx) => {
            const imagery = imagerySubsQueries[idx];
            const weather = weatherSubsQueries[idx];
            return (
              <Tr key={b.id}>
                <Td>
                  <span className="font-mono text-xs text-ap-muted">{b.code}</span>
                  {b.name ? (
                    <span className="ms-2 text-ap-ink">
                      {localizedName(i18n.language, b.name, b.name_ar)}
                    </span>
                  ) : null}
                </Td>
                <SubsCell query={imagery} />
                <LastCell
                  query={imagery}
                  pick={(s) => s.last_successful_ingest_at}
                  dateLocale={dateLocale}
                />
                <SubsCell query={weather} />
                <LastCell
                  query={weather}
                  pick={(s) => s.last_successful_ingest_at}
                  dateLocale={dateLocale}
                />
                <Td className="text-end">
                  <Link
                    to={`/farms/${farmId}/blocks/${b.id}`}
                    className="text-xs font-medium text-ap-primary hover:underline"
                  >
                    {t("blocks.row.openBlock")}
                  </Link>
                </Td>
              </Tr>
            );
          })}
        </Tbody>
      </Table>
    </div>
  );
}

function SubsCell({
  query,
}: {
  query: {
    data?: ImagerySubscription[] | WeatherSubscription[];
    isLoading: boolean;
    isError: boolean;
  };
}): ReactNode {
  const { t } = useTranslation("imageryWeatherConfig");
  if (query.isLoading) {
    return (
      <Td>
        <Skeleton className="h-4 w-20" />
      </Td>
    );
  }
  if (query.isError) {
    return <Td className="text-ap-crit">!</Td>;
  }
  const subs = (query.data ?? []).filter((s) => s.is_active);
  if (subs.length === 0) {
    return (
      <Td>
        <span className="text-xs text-ap-muted">{t("blocks.row.noSubs")}</span>
      </Td>
    );
  }
  return (
    <Td>
      <span className="text-xs">{t("blocks.row.subsCount", { count: subs.length })}</span>
    </Td>
  );
}

function LastCell({
  query,
  pick,
  dateLocale,
}: {
  query: {
    data?: (ImagerySubscription | WeatherSubscription)[];
    isLoading: boolean;
    isError: boolean;
  };
  pick: (s: ImagerySubscription | WeatherSubscription) => string | null;
  dateLocale: ReturnType<typeof useDateLocale>;
}): ReactNode {
  const { t } = useTranslation("imageryWeatherConfig");
  if (query.isLoading) {
    return (
      <Td>
        <Skeleton className="h-4 w-16" />
      </Td>
    );
  }
  if (query.isError) {
    return <Td className="text-ap-crit">!</Td>;
  }
  const subs = (query.data ?? []).filter((s) => s.is_active);
  const latest = subs
    .map(pick)
    .filter((iso): iso is string => Boolean(iso))
    .sort()
    .pop();
  return (
    <Td>
      {latest
        ? formatDistanceToNow(parseISO(latest), { addSuffix: true, locale: dateLocale })
        : t("blocks.row.never")}
    </Td>
  );
}
