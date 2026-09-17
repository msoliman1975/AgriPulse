/**
 * The estate dry run and its report (design section 9, stage B).
 *
 * One beta tree, one tenant, every active block and every cell, folded and
 * counted. Nothing on this screen writes a card: the run is what an
 * agronomist reads before anyone agrees to switch the tree on.
 *
 * What the screen is arranged around, in the order the design puts it:
 *
 *   1. **The error count first.** A switch on a missing index stops the walk,
 *      and cloud cover makes a missing index common, so this number says
 *      whether a tenant would be blanked. It is the headline, not a footnote.
 *   2. The four counts: cells evaluated, no findings, carded, errored.
 *   3. The finding-set table, sortable, one row per set, each saying whether
 *      a rule matched or the text was composed.
 *   4. Rules fired out of rules defined, and the composed share.
 *   5. Timing: total, per cell, and where the time went by block.
 *
 * Every label carries a number. "87.7%" and "204 cells", never "most".
 */

import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { listAdminTenants } from "@/api/adminTenants";
import { Button } from "@/components/Button";
import { DataTable, type Column } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { Field } from "@/components/Field";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { queryState, resolveErrorMessage } from "@/components/asyncState";
import { useClaims, useCapability } from "@/rbac/useCapability";
import { useBetaTrees } from "@/queries/decisionTreesBeta";
import { useQuery } from "@tanstack/react-query";

import { useAuthoringScope } from "../../lib/authoringScope";
import type { EstateErrorByNode, EstateFindingSet, EstateReport } from "../lib/estateApi";
import { useEstateRun, useEstateRuns, useStartEstateDryRun } from "../lib/estateQueries";
import {
  errorBand,
  formatCount,
  formatDuration,
  formatPct,
  formatPerCell,
  rulesAreBypassed,
  sortFindingSets,
  type SetSortKey,
  type SortDirection,
} from "../lib/estateReport";
import { betaBasePath } from "../lib/betaRoutes";

const SELECT_CLASS = "w-full rounded-lg border border-ap-line px-2.5 py-1.5 text-sm text-ap-ink";

/** How many tenants the picker lists. A platform with more than this picks
 *  the tenant from the tenants screen and comes back with it chosen. */
const TENANT_LIMIT = 100;

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }): ReactNode {
  return (
    <div className="rounded-lg border border-ap-line p-3">
      <div className="text-xs text-ap-ink-soft">{label}</div>
      <div className="mt-1 text-xl font-semibold text-ap-ink">{value}</div>
      {hint ? <div className="mt-0.5 text-xs text-ap-ink-soft">{hint}</div> : null}
    </div>
  );
}

export function EstateDryRunPage(): ReactNode {
  const { t, i18n } = useTranslation("decisionTreesEstate");
  const { code } = useParams<{ code: string }>();
  const scope = useAuthoringScope();
  const claims = useClaims();
  const canManage = useCapability("decision_tree.manage");

  const trees = useBetaTrees();
  const tree = (trees.data ?? []).find((row) => row.code === code) ?? null;
  const treeId = tree?.id ?? null;

  // A tenant-scoped caller has exactly one tenant and never picks. A platform
  // caller has none of their own, so the run has nowhere to go until they
  // name one — which is why the picker is a blocking control and not a filter.
  const ownTenantId = claims?.tenant_id ?? null;
  const [pickedTenant, setPickedTenant] = useState<string>("");
  const tenantId = scope === "tenant" ? ownTenantId : pickedTenant || null;

  const tenants = useQuery({
    queryKey: ["decision_trees_estate", "tenants"] as const,
    queryFn: () => listAdminTenants({ limit: TENANT_LIMIT }),
    enabled: scope === "platform",
    staleTime: 60_000,
  });

  const runs = useEstateRuns(treeId, tenantId);
  const [pickedRun, setPickedRun] = useState<string | null>(null);
  const newestRun = (runs.data ?? [])[0]?.id ?? null;
  const runId = pickedRun ?? newestRun;
  const run = useEstateRun(treeId, runId, tenantId);
  const start = useStartEstateDryRun(treeId);

  const [sortKey, setSortKey] = useState<SetSortKey>("count");
  const [direction, setDirection] = useState<SortDirection>("desc");

  const report: EstateReport = run.data?.report ?? {};
  const sets = useMemo(
    () => sortFindingSets(report.finding_sets ?? [], sortKey, direction),
    [report.finding_sets, sortKey, direction],
  );

  const onSort = (key: SetSortKey): void => {
    if (key === sortKey) {
      setDirection(direction === "asc" ? "desc" : "asc");
      return;
    }
    setSortKey(key);
    setDirection(key === "count" ? "desc" : "asc");
  };

  const setColumns: Column<EstateFindingSet>[] = [
    {
      key: "label",
      header: (
        <button type="button" onClick={() => onSort("label")} className="underline-offset-2">
          {t("report.sets.set")}
        </button>
      ),
      cell: (row) => <span className="font-mono text-xs">{row.label}</span>,
    },
    {
      key: "count",
      align: "end",
      header: (
        <button type="button" onClick={() => onSort("count")} className="underline-offset-2">
          {t("report.sets.cells")}
        </button>
      ),
      cell: (row) => formatCount(row.count, i18n.language),
    },
    {
      key: "share",
      align: "end",
      header: t("report.sets.share"),
      cell: (row) => formatPct(row.share_pct),
    },
    {
      key: "rule",
      header: (
        <button type="button" onClick={() => onSort("rule")} className="underline-offset-2">
          {t("report.sets.text")}
        </button>
      ),
      cell: (row) =>
        row.matched_rule ? (
          <Pill kind="info">{t("report.sets.rule", { rule: row.matched_rule })}</Pill>
        ) : (
          <Pill kind="neutral">{t("report.sets.composed")}</Pill>
        ),
    },
    {
      key: "blocks",
      align: "end",
      header: t("report.sets.blocks"),
      cell: (row) => formatCount(row.blocks, i18n.language),
    },
    {
      key: "status",
      header: t("report.sets.status"),
      cell: (row) => row.status ?? "—",
    },
  ];

  const errorColumns: Column<EstateErrorByNode>[] = [
    { key: "node", header: t("report.errors.node"), cell: (row) => row.node_id },
    {
      key: "count",
      align: "end",
      header: t("report.errors.cells"),
      cell: (row) => formatCount(row.count, i18n.language),
    },
    {
      key: "share",
      align: "end",
      header: t("report.errors.share"),
      cell: (row) => formatPct(row.share_pct),
    },
    {
      key: "example",
      header: t("report.errors.example"),
      cell: (row) => <span className="text-xs text-ap-ink-soft">{row.example ?? "—"}</span>,
    },
  ];

  const band = errorBand(report);
  const running = run.data?.state === "running";

  return (
    <Page>
      <PageHeader
        title={t("title", { tree: tree?.name_en ?? code ?? "" })}
        subtitle={t("subtitle")}
        above={
          <Link to={betaBasePath(scope)} className="text-xs text-ap-ink-soft underline">
            {t("actions.back")}
          </Link>
        }
        actions={
          canManage ? (
            <Button
              onClick={() => {
                if (!tenantId) return;
                start.mutate(
                  { tenantId },
                  { onSuccess: (started) => setPickedRun(started.run_id) },
                );
              }}
              disabled={!treeId || !tenantId || start.isPending}
            >
              {t("actions.run")}
            </Button>
          ) : null
        }
      />

      {scope === "platform" ? (
        <Field label={t("tenant.label")} help={t("tenant.hint")}>
          {(props) => (
            <select
              {...props}
              className={SELECT_CLASS}
              value={pickedTenant}
              onChange={(event) => {
                setPickedTenant(event.target.value);
                setPickedRun(null);
              }}
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

      {start.isError ? (
        <StatusBanner kind="crit">
          {resolveErrorMessage(start.error, t("errors.startFailed"))}
        </StatusBanner>
      ) : null}

      {!tenantId ? (
        <EmptyState message={t("tenant.required.body")} />
      ) : (runs.data ?? []).length === 0 ? (
        <EmptyState message={t("empty.body")} />
      ) : (
        <>
          <Field label={t("runPicker.label")}>
            {(props) => (
              <select
                {...props}
                className={SELECT_CLASS}
                value={runId ?? ""}
                onChange={(event) => setPickedRun(event.target.value)}
              >
                {(runs.data ?? []).map((row) => (
                  <option key={row.id} value={row.id}>
                    {t("runPicker.option", {
                      started: new Date(row.started_at).toLocaleString(i18n.language),
                      state: t(`state.${row.state}`),
                      cells: formatCount(row.cells_evaluated, i18n.language),
                    })}
                  </option>
                ))}
              </select>
            )}
          </Field>

          {running ? <StatusBanner kind="info">{t("state.runningBody")}</StatusBanner> : null}
          {run.data?.state === "failed" ? (
            <StatusBanner kind="crit">
              {t("state.failedBody", { error: run.data.error ?? "" })}
            </StatusBanner>
          ) : null}

          {/* The headline. The design puts the error count first, because a
              tenant whose cells error is a tenant that cannot be switched on,
              whatever the rest of the report says. */}
          {band === "blocking" ? (
            <StatusBanner kind="crit">
              {t("report.errors.blocking", {
                cells: formatCount(report.cells_errored, i18n.language),
                pct: formatPct(report.cells_errored_pct),
              })}
            </StatusBanner>
          ) : band === "some" ? (
            <StatusBanner kind="warn">
              {t("report.errors.some", {
                cells: formatCount(report.cells_errored, i18n.language),
                pct: formatPct(report.cells_errored_pct),
              })}
            </StatusBanner>
          ) : null}

          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat
              label={t("report.stats.cells")}
              value={formatCount(report.cells_evaluated, i18n.language)}
              hint={t("report.stats.blocks", {
                blocks: formatCount(report.blocks_evaluated, i18n.language),
              })}
            />
            <Stat
              label={t("report.stats.healthy")}
              value={formatCount(report.cells_no_findings, i18n.language)}
              hint={formatPct(report.cells_no_findings_pct)}
            />
            <Stat
              label={t("report.stats.carded")}
              value={formatCount(report.cells_carded, i18n.language)}
              hint={t("report.stats.composedShare", {
                pct: formatPct(report.composed_share_pct),
              })}
            />
            <Stat
              label={t("report.stats.errored")}
              value={formatCount(report.cells_errored, i18n.language)}
              hint={formatPct(report.cells_errored_pct)}
            />
          </div>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-ap-ink">{t("report.sets.title")}</h2>
            <DataTable
              columns={setColumns}
              rowKey={(row) => row.label}
              rows={sets}
              empty={t("report.sets.empty")}
            />
            {report.other_sets && report.other_sets.sets > 0 ? (
              <p className="text-xs text-ap-ink-soft">
                {t("report.sets.other", {
                  sets: formatCount(report.other_sets.sets, i18n.language),
                  cells: formatCount(report.other_sets.cells, i18n.language),
                })}
              </p>
            ) : null}
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-ap-ink">{t("report.rules.title")}</h2>
            <p className="text-sm text-ap-ink">
              {t("report.rules.fired", {
                fired: report.rules_fired ?? 0,
                defined: report.rules_defined ?? 0,
              })}
            </p>
            <p className="text-sm text-ap-ink">
              {t("report.rules.composed", { pct: formatPct(report.composed_share_pct) })}
            </p>
            {rulesAreBypassed(report) ? (
              <StatusBanner kind="warn">{t("report.rules.allComposed")}</StatusBanner>
            ) : null}
            {(report.rules_never_fired ?? []).length > 0 ? (
              <p className="text-sm text-ap-ink">
                {t("report.rules.never", {
                  rules: (report.rules_never_fired ?? []).join(", "),
                })}
              </p>
            ) : null}
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-ap-ink">{t("report.errors.title")}</h2>
            <DataTable
              columns={errorColumns}
              rowKey={(row) => row.node_id}
              rows={report.errors?.by_node ?? []}
              empty={t("report.errors.empty")}
            />
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-semibold text-ap-ink">{t("report.timing.title")}</h2>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
              <Stat
                label={t("report.timing.total")}
                value={formatDuration(report.timing?.total_ms)}
              />
              <Stat
                label={t("report.timing.perCell")}
                value={formatPerCell(report.timing?.per_cell_ms)}
                hint={t("report.timing.includes")}
              />
              <Stat
                label={t("report.timing.slowestBlock")}
                value={formatDuration(report.timing?.slowest_blocks?.[0]?.duration_ms)}
                hint={report.timing?.slowest_blocks?.[0]?.block_name ?? "—"}
              />
            </div>
            {report.timing?.node_timing?.available === false ? (
              <p className="text-xs text-ap-ink-soft">{t("report.timing.noNodeTiming")}</p>
            ) : null}
          </section>

          {(report.block_failures ?? []).length > 0 ? (
            <section className="space-y-2">
              <h2 className="text-sm font-semibold text-ap-ink">{t("report.failures.title")}</h2>
              <ul className="space-y-1 text-sm text-ap-ink">
                {(report.block_failures ?? []).map((row) => (
                  <li key={row.block_id}>
                    {row.block_name ?? row.block_id}: {row.error}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      )}

      {run.isError ? (
        <StatusBanner kind="crit">
          {resolveErrorMessage(run.error, t("errors.readFailed"))}
        </StatusBanner>
      ) : null}
      {queryState(trees).status === "error" ? (
        <StatusBanner kind="crit">
          {resolveErrorMessage(trees.error, t("errors.treesFailed"))}
        </StatusBanner>
      ) : null}
    </Page>
  );
}
