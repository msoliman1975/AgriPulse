import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { listFarms, type Farm } from "@/api/farms";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
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
        <p role="status" className="text-sm text-ap-muted">
          {t("detail.loading")}
        </p>
      ) : farms.length === 0 ? (
        <EmptyState message={t("list.empty")} />
      ) : (
        <Card noPadding className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-start text-xs uppercase text-ap-muted">
                <th className="px-4 py-2 text-start">{t("list.columns.code")}</th>
                <th className="px-4 py-2 text-start">{t("list.columns.name")}</th>
                <th className="px-4 py-2 text-start">{t("list.columns.governorate")}</th>
                <th className="px-4 py-2 text-start">{t("list.columns.area")}</th>
                <th className="px-4 py-2 text-start">{t("list.columns.status")}</th>
              </tr>
            </thead>
            <tbody>
              {farms.map((f) => (
                <tr key={f.id} className="border-t border-ap-line">
                  <td className="px-4 py-2">
                    <Link to={`/farms/${f.id}`} className="text-ap-primary underline">
                      {f.code}
                    </Link>
                  </td>
                  <td className="px-4 py-2">{f.name}</td>
                  <td className="px-4 py-2">{f.governorate ?? "—"}</td>
                  <td className="px-4 py-2">
                    <AreaDisplay areaM2={Number(f.area_m2)} />
                  </td>
                  <td className="px-4 py-2">
                    {f.is_active ? t("status.active") : t("status.archived")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
