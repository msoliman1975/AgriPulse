import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import type { TemplateStatus } from "@/api/planTemplates";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { usePlanTemplates } from "@/queries/planTemplates";

const STATUS_FILTERS: readonly (TemplateStatus | "all")[] = [
  "all",
  "draft",
  "published",
  "archived",
];

function statusKind(status: TemplateStatus): "ok" | "neutral" | "warn" {
  if (status === "published") return "ok";
  if (status === "archived") return "warn";
  return "neutral";
}

/**
 * /platform/plan-templates — PlatformAdmin authors the catalog of
 * crop-keyed agriculture plan templates. List + status filter; rows open
 * the whole-tree editor. Guarded by `plan_template.manage` on the API.
 */
export function PlatformPlanTemplatesPage(): ReactNode {
  const { t } = useTranslation("planTemplates");
  const navigate = useNavigate();
  const [filter, setFilter] = useState<TemplateStatus | "all">("all");
  const { data, isLoading, isError } = usePlanTemplates(filter === "all" ? undefined : filter);

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ap-ink">{t("list.title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("list.subtitle")}</p>
        </div>
        <button
          type="button"
          onClick={() => navigate("/platform/plan-templates/new")}
          className="rounded-md bg-ap-primary px-3 py-2 text-sm font-medium text-white hover:bg-ap-primary/90"
        >
          {t("list.newButton")}
        </button>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-ap-muted">{t("list.filterLabel")}</span>
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setFilter(s)}
            className={
              filter === s
                ? "rounded-full bg-ap-primary-soft px-3 py-1 text-xs font-medium text-ap-primary"
                : "rounded-full px-3 py-1 text-xs text-ap-muted hover:bg-ap-line/50"
            }
          >
            {t(`status.${s}`)}
          </button>
        ))}
      </div>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : isError ? (
        <p className="text-sm text-ap-crit">{t("list.loadFailed")}</p>
      ) : (data ?? []).length === 0 ? (
        <p className="text-sm text-ap-muted">{t("list.empty")}</p>
      ) : (
        <div className="overflow-hidden rounded-xl border border-ap-line bg-ap-panel">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ap-line text-start text-xs uppercase tracking-wider text-ap-muted">
                <th className="px-4 py-2 text-start font-semibold">{t("list.col.name")}</th>
                <th className="px-4 py-2 text-start font-semibold">{t("list.col.cropPath")}</th>
                <th className="px-4 py-2 text-start font-semibold">{t("list.col.status")}</th>
                <th className="px-4 py-2 text-start font-semibold">{t("list.col.updated")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ap-line">
              {(data ?? []).map((tpl) => (
                <tr
                  key={tpl.id}
                  onClick={() => navigate(`/platform/plan-templates/${tpl.id}`)}
                  className="cursor-pointer hover:bg-ap-line/30"
                >
                  <td className="px-4 py-3">
                    <div className="font-medium text-ap-ink">{tpl.name}</div>
                    <code className="font-mono text-[11px] text-ap-muted">{tpl.code}</code>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-ap-primary">{tpl.crop_path}</td>
                  <td className="px-4 py-3">
                    <Pill kind={statusKind(tpl.status)}>{t(`status.${tpl.status}`)}</Pill>
                  </td>
                  <td className="px-4 py-3 text-xs text-ap-muted">
                    {new Date(tpl.updated_at).toLocaleDateString()}
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
