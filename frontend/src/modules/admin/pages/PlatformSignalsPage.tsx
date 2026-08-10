import { useQuery } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  listPlatformSignalDefinitions,
  listPlatformSignalTemplates,
  type SignalDefinition,
  type SignalTemplate,
} from "@/api/signals";
import { DataTable } from "@/components/DataTable";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { queryState } from "@/components/asyncState";
import { useCapability } from "@/rbac/useCapability";

/** Categorical options, or the numeric range, or nothing — whichever applies. */
function describeValues(d: SignalDefinition): string {
  if (d.categorical_values?.length) return d.categorical_values.join(" · ");
  if (d.value_min !== null || d.value_max !== null) {
    return `${d.value_min ?? "−∞"} … ${d.value_max ?? "∞"}`;
  }
  return "—";
}

/**
 * /platform/signals — the shared signal catalog every tenant reads.
 *
 * Rows here are platform-curated (`tenant_id IS NULL`). A tenant may author its
 * own definition with the same `code`, in which case the tenant's row shadows
 * this one for that tenant only — so editing here changes the default, never
 * somebody's override.
 *
 * Deletion is deliberately absent. Retiring a definition affects every tenant
 * recording against it, so the safe control is the active/retired state rather
 * than a delete button that looks reversible and is not.
 */
export function PlatformSignalsPage(): ReactNode {
  const { t } = useTranslation("admin");
  const canManage = useCapability("signal.platform.manage");

  const definitions = useQuery({
    queryKey: ["platform", "signals", "definitions"],
    queryFn: () => listPlatformSignalDefinitions(true),
  });
  const templates = useQuery({
    queryKey: ["platform", "signals", "templates"],
    queryFn: () => listPlatformSignalTemplates(true),
  });

  const statePill = (isActive: boolean) =>
    isActive ? (
      <Pill kind="ok">{t("signals.active")}</Pill>
    ) : (
      <Pill kind="warn">{t("signals.retired")}</Pill>
    );

  return (
    <Page>
      <PageHeader
        title={t("signals.title")}
        subtitle={t("signals.subtitle")}
        badge={!canManage ? <Pill kind="warn">{t("signals.readonlyHint")}</Pill> : undefined}
      />

      <DataTable<SignalDefinition>
        columns={[
          {
            key: "code",
            header: t("signals.colCode"),
            cell: (d) => (
              <>
                <div className="font-medium">{d.name}</div>
                <code className="font-mono text-[11px] text-ap-muted">{d.code}</code>
              </>
            ),
          },
          {
            key: "kind",
            header: t("signals.colKind"),
            className: "text-xs",
            cell: (d) => (d.unit ? `${d.value_kind} · ${d.unit}` : d.value_kind),
          },
          {
            key: "values",
            header: t("signals.colValues"),
            className: "text-xs text-ap-muted",
            cell: describeValues,
          },
          {
            // Gates whether the capture UI offers a camera at all — unset it
            // and the control silently never appears in the field app.
            key: "photo",
            header: t("signals.colPhoto"),
            cell: (d) => (d.attachment_allowed ? "✓" : "—"),
          },
          {
            key: "aggregation",
            header: t("signals.colAggregation"),
            className: "font-mono text-xs text-ap-primary",
            cell: (d) =>
              d.aggregation_window_days
                ? `${d.aggregation}/${d.aggregation_window_days}d`
                : d.aggregation,
          },
          {
            key: "state",
            header: t("signals.colState"),
            cell: (d) => statePill(d.is_active),
          },
        ]}
        rowKey={(d) => d.id}
        state={queryState(definitions)}
        caption={t("signals.definitions")}
        errorMessage={t("signals.loadFailed")}
        empty={t("signals.emptyDefinitions")}
      />

      <DataTable<SignalTemplate>
        columns={[
          {
            key: "code",
            header: t("signals.colCode"),
            cell: (tpl) => (
              <>
                <div className="font-medium">{tpl.name}</div>
                <code className="font-mono text-[11px] text-ap-muted">{tpl.code}</code>
              </>
            ),
          },
          {
            key: "description",
            header: t("signals.colName"),
            className: "text-xs text-ap-muted",
            cell: (tpl) => tpl.description ?? "—",
          },
          {
            key: "state",
            header: t("signals.colState"),
            cell: (tpl) => statePill(tpl.is_active),
          },
        ]}
        rowKey={(tpl) => tpl.id}
        state={queryState(templates)}
        caption={t("signals.templates")}
        errorMessage={t("signals.loadFailed")}
        empty={t("signals.emptyTemplates")}
      />
    </Page>
  );
}
