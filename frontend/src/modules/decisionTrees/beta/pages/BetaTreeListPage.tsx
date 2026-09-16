/**
 * The beta designer's index.
 *
 * The same `<Page>` / `<PageHeader>` / `<DataTable state>` pattern as
 * `DecisionTreeListPage`, so the two surfaces read as one product. It is a
 * separate list on purpose: a beta tree folds findings and an existing tree
 * ends at an outcome leaf, and mixing them in one table would put two engines
 * behind one row.
 */

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { LinkButton } from "@/components/LinkButton";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { mapAsyncState, queryState } from "@/components/asyncState";
import { localizedField } from "@/lib/localizedField";
import { useBetaTrees } from "@/queries/decisionTreesBeta";
import type { BetaTreeSummary } from "@/api/decisionTreesBeta";

import { useAuthoringScope } from "../../lib/authoringScope";
import { betaBasePath, findingCataloguePath } from "../lib/betaRoutes";

export function BetaTreeListPage(): ReactNode {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const scope = useAuthoringScope();
  const base = betaBasePath(scope);
  const query = useBetaTrees();

  // Never cast a query result: `mapAsyncState` carries loading and error
  // through and only touches the success payload.
  const rows = mapAsyncState(queryState(query), (list): readonly BetaTreeSummary[] => list);

  return (
    <Page>
      <PageHeader
        title={t("list.title")}
        badge={<Pill kind="info">{t("beta.badge")}</Pill>}
        subtitle={t("list.subtitle")}
        actions={
          <LinkButton to={findingCataloguePath(scope)} variant="secondary">
            {t("list.openCatalogue")}
          </LinkButton>
        }
      />
      <p className="text-sm text-ap-muted">{t("beta.note")}</p>
      <DataTable<BetaTreeSummary>
        state={rows}
        rowKey={(row) => row.code}
        rowHref={(row) => `${base}/${row.code}`}
        errorMessage={t("list.loadFailed")}
        empty={<EmptyState message={t("list.empty")} />}
        caption={t("list.title")}
        columns={[
          {
            key: "name",
            header: t("list.columns.name"),
            cell: (row) => localizedField(i18n.language, row.name_en, row.name_ar) ?? row.code,
          },
          {
            key: "code",
            header: t("list.columns.code"),
            cell: (row) => (
              <span dir="ltr" className="font-mono text-xs">
                {row.code}
              </span>
            ),
          },
          {
            key: "scope",
            header: t("list.columns.scope"),
            cell: (row) => t(`list.scope.${row.scope}`),
          },
          {
            key: "version",
            header: t("list.columns.version"),
            cell: (row) => row.current_version ?? "—",
          },
          {
            key: "published",
            header: t("list.columns.published"),
            cell: (row) =>
              row.published_version !== null ? (
                <Pill kind="ok">{row.published_version}</Pill>
              ) : (
                <Pill kind="neutral">{t("list.notPublished")}</Pill>
              ),
          },
        ]}
      />
    </Page>
  );
}
