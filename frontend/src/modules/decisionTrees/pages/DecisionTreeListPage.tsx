import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useCapability } from "@/rbac/useCapability";
import { useDecisionTrees } from "@/queries/decisionTrees";

export function DecisionTreeListPage(): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const canManage = useCapability("decision_tree.manage");

  const { data, isLoading, isError } = useDecisionTrees();

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ap-ink">{t("list.title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("list.subtitle")}</p>
        </div>
        {canManage ? (
          <Link
            to="/settings/decision-trees/new"
            className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90"
          >
            {t("list.newButton")}
          </Link>
        ) : null}
      </header>

      {!canManage ? (
        <p className="text-xs text-ap-muted">
          {t("list.missingCapability", { capability: "decision_tree.manage" })}
        </p>
      ) : null}

      <div className="rounded-xl border border-ap-line bg-ap-panel">
        {isLoading ? (
          <div className="flex flex-col gap-2 p-4">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : isError ? (
          <p className="p-4 text-sm text-ap-crit">{t("list.loadFailed")}</p>
        ) : !data || data.length === 0 ? (
          <p className="p-12 text-center text-sm text-ap-muted">{t("list.empty")}</p>
        ) : (
          <table className="min-w-full text-sm">
            <thead className="bg-ap-bg/40 text-xs uppercase text-ap-muted">
              <tr>
                <th className="px-4 py-2 text-start">{t("list.table.code")}</th>
                <th className="px-4 py-2 text-start">{t("list.table.name")}</th>
                <th className="px-4 py-2 text-start">{t("list.table.crop")}</th>
                <th className="px-4 py-2 text-end">{t("list.table.version")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ap-line">
              {data.map((tree) => (
                <tr key={tree.id}>
                  <td className="px-4 py-2">
                    <Link
                      to={`/settings/decision-trees/${tree.code}`}
                      className="font-mono text-xs text-ap-primary hover:underline"
                    >
                      {tree.code}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-ap-ink">{tree.name_en}</td>
                  <td className="px-4 py-2 text-xs text-ap-muted">
                    {tree.crop_id ? (
                      <span className="font-mono">{tree.crop_id.slice(0, 8)}…</span>
                    ) : (
                      <span>{t("list.table.anyCrop")}</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-end">
                    {tree.current_version != null ? (
                      <Pill kind="ok">{t("list.row.v", { n: tree.current_version })}</Pill>
                    ) : (
                      <Pill kind="neutral">{t("list.row.draft")}</Pill>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
