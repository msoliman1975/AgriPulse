import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { listFarms, type Farm } from "@/api/farms";
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
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-brand-800">{t("list.heading")}</h1>
        {canCreate ? (
          <Link to="/farms/new" className="btn btn-primary">
            {t("list.createButton")}
          </Link>
        ) : null}
      </div>

      <div className="card">
        <label className="inline-flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          {t("list.filters.includeArchived")}
        </label>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}

      {farms === null ? (
        <p role="status">{t("detail.loading")}</p>
      ) : farms.length === 0 ? (
        <p className="text-sm text-slate-600">{t("list.empty")}</p>
      ) : (
        <div className="card overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="text-start text-xs uppercase text-slate-500">
                <th className="py-2 text-start">{t("list.columns.code")}</th>
                <th className="py-2 text-start">{t("list.columns.name")}</th>
                <th className="py-2 text-start">{t("list.columns.governorate")}</th>
                <th className="py-2 text-start">{t("list.columns.area")}</th>
                <th className="py-2 text-start">{t("list.columns.status")}</th>
              </tr>
            </thead>
            <tbody>
              {farms.map((f) => (
                <tr key={f.id} className="border-t border-slate-100">
                  <td className="py-2">
                    <Link to={`/farms/${f.id}`} className="text-brand-700 underline">
                      {f.code}
                    </Link>
                  </td>
                  <td className="py-2">{f.name}</td>
                  <td className="py-2">{f.governorate ?? "—"}</td>
                  <td className="py-2">
                    <AreaDisplay areaM2={Number(f.area_m2)} />
                  </td>
                  <td className="py-2">
                    {f.is_active ? t("status.active") : t("status.archived")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
