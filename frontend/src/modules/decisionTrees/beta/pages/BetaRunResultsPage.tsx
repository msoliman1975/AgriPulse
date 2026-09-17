/**
 * What real runs of a beta tree produced.
 *
 * Read from `decision_tree_eval_traces` and the three fold columns tenant
 * migration 0095 added: `finding_set`, `matched_rule` and `registered_by`.
 * One row per block and finding set, with the cells that produced it and the
 * card it opened.
 *
 * **The finding set is the answer, not the last node.** A folding walk always
 * ends at `stop`, so nothing here is derived from where the walk stopped. The
 * old rule — the leaf is the step whose `matched` is null — belongs to the
 * other engine and does not apply.
 *
 * **The tree name comes from a join.** A trace row carries `tree_code` and a
 * version, never a name; the server joins `public.decision_trees` for it.
 *
 * Empty until the tree is on the sweep, which is stage C of the rollout. The
 * estate dry run writes no trace by design, so this screen says that in
 * words rather than showing an empty table with no explanation.
 */

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { listAdminTenants } from "@/api/adminTenants";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { Field } from "@/components/Field";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { queryState, resolveErrorMessage } from "@/components/asyncState";
import { localizedField } from "@/lib/localizedField";
import { useClaims } from "@/rbac/useCapability";
import { useBetaTrees } from "@/queries/decisionTreesBeta";
import { useQuery } from "@tanstack/react-query";

import { useAuthoringScope } from "../../lib/authoringScope";
import type { BetaRunResultRow } from "../lib/estateApi";
import { useBetaRunResults } from "../lib/estateQueries";
import { betaBasePath } from "../lib/betaRoutes";
import { formatCount, setLabel } from "../lib/estateReport";

const SELECT_CLASS = "w-full rounded-lg border border-ap-line px-2.5 py-1.5 text-sm text-ap-ink";
const TENANT_LIMIT = 100;

export function BetaRunResultsPage(): ReactNode {
  const { t, i18n } = useTranslation("decisionTreesEstate");
  const { code } = useParams<{ code: string }>();
  const scope = useAuthoringScope();
  const claims = useClaims();

  const trees = useBetaTrees();
  const tree = (trees.data ?? []).find((row) => row.code === code) ?? null;
  const treeId = tree?.id ?? null;

  const ownTenantId = claims?.tenant_id ?? null;
  const [pickedTenant, setPickedTenant] = useState<string>("");
  const tenantId = scope === "tenant" ? ownTenantId : pickedTenant || null;

  const tenants = useQuery({
    queryKey: ["decision_trees_estate", "tenants"] as const,
    queryFn: () => listAdminTenants({ limit: TENANT_LIMIT }),
    enabled: scope === "platform",
    staleTime: 60_000,
  });

  const results = useBetaRunResults(treeId, tenantId);

  const columns: Column<BetaRunResultRow>[] = [
    {
      key: "block",
      header: t("results.block"),
      cell: (row) => (
        <div>
          <div className="text-sm text-ap-ink">
            {localizedField(i18n.language, row.block_name, row.block_name_ar) ?? row.block_id}
          </div>
          <div className="text-xs text-ap-ink-soft">{row.farm_name ?? ""}</div>
        </div>
      ),
    },
    {
      key: "cells",
      align: "end",
      header: t("results.cells"),
      cell: (row) => formatCount(row.cells, i18n.language),
    },
    {
      key: "set",
      header: t("results.set"),
      cell: (row) => <span className="font-mono text-xs">{setLabel(row.finding_set)}</span>,
    },
    {
      key: "rule",
      header: t("results.text"),
      cell: (row) =>
        row.matched_rule ? (
          <Pill kind="info">{t("report.sets.rule", { rule: row.matched_rule })}</Pill>
        ) : (
          <Pill kind="neutral">{t("report.sets.composed")}</Pill>
        ),
    },
    { key: "status", header: t("results.status"), cell: (row) => row.status },
    {
      key: "cards",
      align: "end",
      header: t("results.cards"),
      cell: (row) => formatCount(row.cards_opened, i18n.language),
    },
    {
      key: "when",
      header: t("results.when"),
      cell: (row) =>
        row.last_evaluated_at ? new Date(row.last_evaluated_at).toLocaleString(i18n.language) : "—",
    },
  ];

  return (
    <Page>
      <PageHeader
        title={t("results.title", { tree: tree?.name_en ?? code ?? "" })}
        subtitle={t("results.subtitle")}
        above={
          <Link to={betaBasePath(scope)} className="text-xs text-ap-ink-soft underline">
            {t("actions.back")}
          </Link>
        }
      />

      {scope === "platform" ? (
        <Field label={t("tenant.label")} help={t("tenant.hint")}>
          {(props) => (
            <select
              {...props}
              className={SELECT_CLASS}
              value={pickedTenant}
              onChange={(event) => setPickedTenant(event.target.value)}
            >
              <option value="">{t("tenant.placeholder")}</option>
              {(tenants.data?.items ?? []).map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          )}
        </Field>
      ) : null}

      {!tenantId ? (
        <EmptyState message={t("tenant.required.body")} />
      ) : (
        <>
          <StatusBanner kind="info">{t("results.stageC")}</StatusBanner>
          <DataTable
            columns={columns}
            rowKey={(row) => `${row.run_id}:${row.block_id}:${setLabel(row.finding_set)}`}
            state={queryState(results)}
            empty={t("results.empty")}
            errorMessage={t("results.error")}
          />
        </>
      )}

      {trees.isError ? (
        <StatusBanner kind="crit">
          {resolveErrorMessage(trees.error, t("errors.treesFailed"))}
        </StatusBanner>
      ) : null}
    </Page>
  );
}
