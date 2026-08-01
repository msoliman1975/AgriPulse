import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/Button";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { LinkButton } from "@/components/LinkButton";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Toolbar, ToolbarChips } from "@/components/Toolbar";
import { mapAsyncState, queryState } from "@/components/asyncState";
import type { AdminTenant, TenantStatus } from "@/api/adminTenants";
import { useAdminTenantList, useAdminTenantMeta } from "@/queries/admin/tenants";

import { TenantStatusBadge } from "../components/TenantStatusBadge";

const PAGE_SIZE = 25;

/**
 * /platform/tenants — the reference IndexPage.
 *
 * PageHeader + Toolbar + DataTable + Pagination, with the async ladder owned
 * by the table so the column headers stay put while rows load.
 */
export function TenantListPage(): ReactNode {
  const { t, i18n } = useTranslation("admin");

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<TenantStatus | undefined>(undefined);
  const [page, setPage] = useState(0);

  const meta = useAdminTenantMeta();
  const params = useMemo(
    () => ({
      search: search.trim() || undefined,
      status: statusFilter,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [search, statusFilter, page],
  );
  const list = useAdminTenantList(params);

  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(i18n.language, {
        year: "numeric",
        month: "short",
        day: "numeric",
      }),
    [i18n.language],
  );

  const total = list.data?.total ?? 0;
  const shown = list.data?.items.length ?? 0;
  const filtered = search.trim() !== "" || statusFilter !== undefined;

  function clearFilters(): void {
    setSearch("");
    setStatusFilter(undefined);
    setPage(0);
  }

  const columns: Column<AdminTenant>[] = [
    {
      key: "slug",
      header: t("tenants.list.headers.slug"),
      cell: (tenant) => <span className="font-mono text-xs">{tenant.slug}</span>,
    },
    { key: "name", header: t("tenants.list.headers.name"), cell: (tenant) => tenant.name },
    {
      key: "status",
      header: t("tenants.list.headers.status"),
      cell: (tenant) => <TenantStatusBadge status={tenant.status} />,
    },
    {
      key: "contact",
      header: t("tenants.list.headers.contact"),
      className: "text-ap-muted",
      cell: (tenant) => tenant.contact_email,
    },
    {
      key: "created",
      header: t("tenants.list.headers.created"),
      className: "text-ap-muted",
      cell: (tenant) => dateFormatter.format(new Date(tenant.created_at)),
    },
  ];

  return (
    <Page>
      <PageHeader
        className="border-b border-ap-line pb-4"
        title={t("tenants.list.title")}
        subtitle={t("tenants.list.subtitle")}
        actions={<LinkButton to="/platform/tenants/new">{t("tenants.list.newButton")}</LinkButton>}
      />

      <Toolbar
        search={{
          value: search,
          onChange: (value) => {
            setSearch(value);
            setPage(0);
          },
          placeholder: t("tenants.list.searchPlaceholder"),
        }}
        chips={
          <ToolbarChips
            allLabel={t("tenants.list.filterAll")}
            value={statusFilter ?? null}
            onChange={(next) => {
              setStatusFilter((next as TenantStatus | null) ?? undefined);
              setPage(0);
            }}
            options={(meta.data?.statuses ?? []).map((s) => ({
              value: s,
              label: t(`status.${s}`),
            }))}
          />
        }
        resultCount={total > 0 ? { shown, total } : undefined}
      />

      <DataTable<AdminTenant>
        columns={columns}
        rowKey={(tenant) => tenant.id}
        state={mapAsyncState(queryState(list), (p) => p.items)}
        filtered={filtered}
        rowHref={(tenant) => `/platform/tenants/${tenant.id}`}
        caption={t("tenants.list.title")}
        errorMessage={t("tenants.list.errorTitle")}
        empty={
          <EmptyState
            message={t("tenants.list.empty")}
            action={
              <LinkButton to="/platform/tenants/new">{t("tenants.list.newButton")}</LinkButton>
            }
          />
        }
        noResults={
          <EmptyState
            message={t("tenants.list.noResults")}
            action={
              <Button variant="secondary" onClick={clearFilters}>
                {t("tenants.list.clearFilters")}
              </Button>
            }
          />
        }
      />

      <Pagination page={page} pageSize={PAGE_SIZE} total={total} onPageChange={setPage} />
    </Page>
  );
}
