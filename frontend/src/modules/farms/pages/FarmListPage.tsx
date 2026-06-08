import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { listFarms, type Farm } from "@/api/farms";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { useCapability } from "@/rbac/useCapability";
import { isApiError } from "@/api/errors";
import { AreaDisplay } from "../components/AreaDisplay";

export function FarmListPage(): JSX.Element {
  const { t } = useTranslation("farms");
  const canCreate = useCapability("farm.create");
  const [farms, setFarms] = useState<Farm[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    listFarms({ include_inactive: includeArchived })
      .then((page) => {
        if (!cancelled) setFarms(page.items);
      })
      .catch((err) => {
        if (cancelled) return;
        if (isApiError(err)) setError(err.problem.detail ?? err.problem.title);
        else setError(String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [includeArchived]);

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("list.heading")}
        actions={
          canCreate ? (
            <Link
              to="/farms/new"
              className="inline-flex items-center justify-center rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-ap-primary/90"
            >
              {t("list.createButton")}
            </Link>
          ) : null
        }
      />

      <Card>
        <label className="inline-flex items-center gap-2 text-sm text-ap-ink">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          {t("list.filters.includeArchived")}
        </label>
      </Card>

      {error ? <ErrorState message={error} /> : null}

      {farms === null ? (
        <Skeleton className="h-40 w-full rounded-xl" />
      ) : farms.length === 0 ? (
        <EmptyState message={t("list.empty")} />
      ) : (
        <Table>
          <Thead>
            <tr>
              <Th>{t("list.columns.code")}</Th>
              <Th>{t("list.columns.name")}</Th>
              <Th>{t("list.columns.governorate")}</Th>
              <Th>{t("list.columns.area")}</Th>
              <Th>{t("list.columns.status")}</Th>
            </tr>
          </Thead>
          <Tbody>
            {farms.map((f) => (
              <Tr key={f.id}>
                <Td>
                  <Link to={`/farms/${f.id}`} className="text-ap-primary underline">
                    {f.code}
                  </Link>
                </Td>
                <Td>{f.name}</Td>
                <Td>{f.governorate ?? "—"}</Td>
                <Td>
                  <AreaDisplay areaM2={Number(f.area_m2)} />
                </Td>
                <Td>{f.is_active ? t("status.active") : t("status.archived")}</Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      )}
    </div>
  );
}
