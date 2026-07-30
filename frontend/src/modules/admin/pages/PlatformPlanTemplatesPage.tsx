import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { PlanTemplateSummary, TemplateStatus } from "@/api/planTemplates";
import { Button } from "@/components/Button";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { LinkButton } from "@/components/LinkButton";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Toolbar, ToolbarChips } from "@/components/Toolbar";
import { queryState } from "@/components/asyncState";
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
  const [filter, setFilter] = useState<TemplateStatus | "all">("all");
  const templates = usePlanTemplates(filter === "all" ? undefined : filter);

  return (
    <Page>
      <PageHeader
        title={t("list.title")}
        subtitle={t("list.subtitle")}
        actions={<LinkButton to="/platform/plan-templates/new">{t("list.newButton")}</LinkButton>}
      />

      <Toolbar
        chips={
          <ToolbarChips
            value={filter === "all" ? null : filter}
            onChange={(next) => setFilter((next as TemplateStatus | null) ?? "all")}
            allLabel={t("status.all")}
            options={STATUS_FILTERS.filter((s) => s !== "all").map((s) => ({
              value: s,
              label: t(`status.${s}`),
            }))}
          />
        }
      />

      <DataTable<PlanTemplateSummary>
        columns={[
          {
            key: "name",
            header: t("list.col.name"),
            cell: (tpl) => (
              <>
                <div className="font-medium">{tpl.name}</div>
                <code className="font-mono text-[11px] text-ap-muted">{tpl.code}</code>
              </>
            ),
          },
          {
            key: "cropPath",
            header: t("list.col.cropPath"),
            className: "font-mono text-xs text-ap-primary",
            cell: (tpl) => tpl.crop_path,
          },
          {
            key: "status",
            header: t("list.col.status"),
            cell: (tpl) => <Pill kind={statusKind(tpl.status)}>{t(`status.${tpl.status}`)}</Pill>,
          },
          {
            key: "updated",
            header: t("list.col.updated"),
            className: "text-xs text-ap-muted",
            cell: (tpl) => new Date(tpl.updated_at).toLocaleDateString(),
          },
        ]}
        rowKey={(tpl) => tpl.id}
        state={queryState(templates)}
        filtered={filter !== "all"}
        rowHref={(tpl) => `/platform/plan-templates/${tpl.id}`}
        caption={t("list.title")}
        errorMessage={t("list.loadFailed")}
        empty={
          <EmptyState
            message={t("list.empty")}
            action={
              <LinkButton to="/platform/plan-templates/new">{t("list.newButton")}</LinkButton>
            }
          />
        }
        noResults={
          <EmptyState
            message={t("list.noResults")}
            action={
              <Button variant="secondary" onClick={() => setFilter("all")}>
                {t("list.clearFilter")}
              </Button>
            }
          />
        }
      />
    </Page>
  );
}
