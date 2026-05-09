import type { ReactNode } from "react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { FilterChip } from "@/components/FilterChip";
import { Skeleton } from "@/components/Skeleton";
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
      <header className="flex flex-col gap-3 border-b border-ap-line pb-4 md:flex-row md:items-start md:justify-between">
        <div>
          <h1 className="text-lg font-semibold text-ap-ink">{t("tenants.list.title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("tenants.list.subtitle")}</p>
        </div>
        <Link
          to="/platform/tenants/new"
          className="inline-flex items-center justify-center rounded-md bg-ap-primary px-3 py-2 text-sm font-medium text-white hover:bg-ap-primary/90"
        >
          {t("tenants.list.newButton")}
        </Link>
      </header>

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
          <FilterChip
            active={statusFilter === undefined}
            onToggle={() => clearAndSet(undefined)}
          >
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
        <p
          role="alert"
          className="mt-6 rounded-md border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"
        >
          {t("tenants.list.errorTitle")}
        </p>
      ) : null}

      <div className="mt-4 overflow-hidden rounded-lg border border-ap-line bg-ap-panel shadow-card">
        <table className="min-w-full divide-y divide-ap-line text-sm">
          <thead className="bg-ap-line/30 text-[11px] uppercase tracking-wider text-ap-muted">
            <tr>
              <th scope="col" className="px-3 py-2 text-start font-semibold">
                {t("tenants.list.headers.slug")}
              </th>
              <th scope="col" className="px-3 py-2 text-start font-semibold">
                {t("tenants.list.headers.name")}
              </th>
              <th scope="col" className="px-3 py-2 text-start font-semibold">
                {t("tenants.list.headers.status")}
              </th>
              <th scope="col" className="px-3 py-2 text-start font-semibold">
                {t("tenants.list.headers.contact")}
              </th>
              <th scope="col" className="px-3 py-2 text-start font-semibold">
                {t("tenants.list.headers.created")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ap-line">
            {list.isLoading || (list.isFetching && items.length === 0) ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center">
                  <Skeleton className="mx-auto h-4 w-1/2" />
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td
                  colSpan={5}
                  className="px-3 py-10 text-center text-sm text-ap-muted"
                >
                  {t("tenants.list.empty")}
                </td>
              </tr>
            ) : (
              items.map((tenant) => (
                <tr
                  key={tenant.id}
                  onClick={() => navigate(`/platform/tenants/${tenant.id}`)}
                  className="cursor-pointer transition-colors hover:bg-ap-line/30"
                >
                  <td className="px-3 py-2 font-mono text-xs text-ap-ink">
                    {tenant.slug}
                  </td>
                  <td className="px-3 py-2 text-ap-ink">{tenant.name}</td>
                  <td className="px-3 py-2">
                    <TenantStatusBadge status={tenant.status} />
                  </td>
                  <td className="px-3 py-2 text-ap-muted">{tenant.contact_email}</td>
                  <td className="px-3 py-2 text-ap-muted">
                    {dateFormatter.format(new Date(tenant.created_at))}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {total > 0 ? (
        <nav
          aria-label="Pagination"
          className="mt-3 flex items-center justify-between text-xs text-ap-muted"
        >
          <span>
            {t("tenants.list.pagination.showing", { first, last, total })}
          </span>
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
