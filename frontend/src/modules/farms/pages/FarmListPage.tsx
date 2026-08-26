import { useState } from "react";
import { useTranslation } from "react-i18next";

import { listFarms, type Farm } from "@/api/farms";
import { Button } from "@/components/Button";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { FilterChip } from "@/components/FilterChip";
import { LinkButton } from "@/components/LinkButton";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Toolbar } from "@/components/Toolbar";
import { mapAsyncState, useAsyncData } from "@/components/asyncState";
import { localizedName } from "@/lib/localizedField";
import { useCapability } from "@/rbac/useCapability";
import { AreaDisplay } from "../components/AreaDisplay";

export function FarmListPage(): JSX.Element {
  const { t, i18n } = useTranslation("farms");
  const canCreate = useCapability("farm.create");
  const [includeArchived, setIncludeArchived] = useState(false);

  const state = useAsyncData(
    () => listFarms({ include_inactive: includeArchived }),
    [includeArchived],
  );

  const columns: Column<Farm>[] = [
    { key: "code", header: t("list.columns.code"), cell: (f) => f.code },
    {
      key: "name",
      header: t("list.columns.name"),
      cell: (f) => localizedName(i18n.language, f.name, f.name_ar),
    },
    {
      key: "governorate",
      header: t("list.columns.governorate"),
      className: "text-ap-muted",
      cell: (f) => f.governorate ?? "—",
    },
    {
      key: "area",
      header: t("list.columns.area"),
      align: "end",
      cell: (f) => <AreaDisplay areaM2={Number(f.area_m2)} />,
    },
    {
      key: "status",
      header: t("list.columns.status"),
      cell: (f) => (
        <Pill kind={f.is_active ? "ok" : "neutral"}>
          {f.is_active ? t("status.active") : t("status.archived")}
        </Pill>
      ),
    },
  ];

  return (
    // Five columns do not fill max-w-6xl — see decision 5's escape hatch.
    <Page width="standard">
      <PageHeader
        title={t("list.heading")}
        actions={
          canCreate ? <LinkButton to="/farms/new">{t("list.createButton")}</LinkButton> : null
        }
      />

      <Toolbar
        chips={
          <FilterChip active={includeArchived} onToggle={() => setIncludeArchived((v) => !v)}>
            {t("list.filters.includeArchived")}
          </FilterChip>
        }
      />

      <DataTable<Farm>
        columns={columns}
        rowKey={(f) => f.id}
        state={mapAsyncState(state, (p) => p.items)}
        filtered={includeArchived}
        rowHref={(f) => `/farms/${f.id}`}
        caption={t("list.heading")}
        empty={
          <EmptyState
            message={t("list.empty")}
            action={
              canCreate ? <LinkButton to="/farms/new">{t("list.createButton")}</LinkButton> : null
            }
          />
        }
        noResults={
          <EmptyState
            message={t("list.empty")}
            action={
              <Button variant="secondary" onClick={() => setIncludeArchived(false)}>
                {t("list.filters.hideArchived")}
              </Button>
            }
          />
        }
      />
    </Page>
  );
}
