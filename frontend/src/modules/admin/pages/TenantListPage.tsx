import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { ErrorState } from "@/components/ErrorState";
import { FilterChip } from "@/components/FilterChip";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import type { TenantStatus } from "@/api/adminTenants";
import { useAdminTenantList, useAdminTenantMeta } from "@/queries/admin/tenants";

import { TenantStatusBadge } from "../components/TenantStatusBadge";

const PAGE_SIZE = 25;

export function TenantListPage(): ReactNode {
  const { t, i18n } = useTranslation("admin");
  const navigate = useNavigate();

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

  const items = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const first = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const last = Math.min(total, first + items.length - 1);
  const hasPrev = page > 0;
  const hasNext = (page + 1) * PAGE_SIZE < total;

  function clearAndSet(next: TenantStatus | undefined): void {
    setStatusFilter(next);
    setPage(0);
  }

  return (
    <section className="mx-auto max-w-5xl">
      <PageHeader
        className="border-b border-ap-line pb-4"
        title={t("tenants.list.title")}
        subtitle={t("tenants.list.subtitle")}
        actions={
          <Link
            to="/platform/tenants/new"
            className="inline-flex items-center justify-center rounded-md bg-ap-primary px-3 py-2 text-sm font-medium text-white hover:bg-ap-primary/90"
          >
            {t("tenants.list.newButton")}
          </Link>
        }
      />

      <div className="mt-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <input
          type="search"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(0);
          }}
          placeholder={t("tenants.list.searchPlaceholder")}
          className="w-full rounded-md border border-ap-line bg-ap-panel px-3 py-2 text-sm text-ap-ink shadow-sm focus:border-ap-primary focus:outline-none focus-visible:ring-2 focus-visible:ring-ap-primary md:max-w-xs"
        />
        <div className="flex flex-wrap gap-2">
          <FilterChip active={statusFilter === undefined} onToggle={() => clearAndSet(undefined)}>
            {t("tenants.list.filterAll")}
          </FilterChip>
          {(meta.data?.statuses ?? []).map((s) => (
            <FilterChip
              key={s}
              active={statusFilter === s}
              onToggle={() => clearAndSet(statusFilter === s ? undefined : s)}
            >
              {t(`status.${s}`)}
            </FilterChip>
          ))}
        </div>
      </div>

      {list.isError ? (
        <ErrorState className="mt-6" message={t("tenants.list.errorTitle")} />
      ) : null}

      <div className="mt-4">
        <Table>
          <Thead>
            <tr>
              <Th>{t("tenants.list.headers.slug")}</Th>
              <Th>{t("tenants.list.headers.name")}</Th>
              <Th>{t("tenants.list.headers.status")}</Th>
              <Th>{t("tenants.list.headers.contact")}</Th>
              <Th>{t("tenants.list.headers.created")}</Th>
            </tr>
          </Thead>
          <Tbody>
            {list.isLoading || (list.isFetching && items.length === 0) ? (
              <tr>
                <Td colSpan={5} className="py-6 text-center">
                  <Skeleton className="mx-auto h-4 w-1/2" />
                </Td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <Td colSpan={5} className="py-10 text-center text-ap-muted">
                  {t("tenants.list.empty")}
                </Td>
              </tr>
            ) : (
              items.map((tenant) => (
                <Tr
                  key={tenant.id}
                  interactive
                  onClick={() => navigate(`/platform/tenants/${tenant.id}`)}
                >
                  <Td className="font-mono text-xs text-ap-ink">{tenant.slug}</Td>
                  <Td className="text-ap-ink">{tenant.name}</Td>
                  <Td>
                    <TenantStatusBadge status={tenant.status} />
                  </Td>
                  <Td className="text-ap-muted">{tenant.contact_email}</Td>
                  <Td className="text-ap-muted">
                    {dateFormatter.format(new Date(tenant.created_at))}
                  </Td>
                </Tr>
              ))
            )}
          </Tbody>
        </Table>
      </div>

      {total > 0 ? (
        <nav
          aria-label="Pagination"
          className="mt-3 flex items-center justify-between text-xs text-ap-muted"
        >
          <span>{t("tenants.list.pagination.showing", { first, last, total })}</span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={!hasPrev}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              className="rounded-md border border-ap-line px-3 py-1 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t("tenants.list.pagination.prev")}
            </button>
            <button
              type="button"
              disabled={!hasNext}
              onClick={() => setPage((p) => p + 1)}
              className="rounded-md border border-ap-line px-3 py-1 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {t("tenants.list.pagination.next")}
            </button>
          </div>
        </nav>
      ) : null}
    </section>
  );
}
