// Evaluation-trace viewer: why each decision tree did or didn't fire, for a
// run that has already happened (tenant migration 0062).
//
// Distinct from the Farm Console's Conditions tab, which re-evaluates *live*
// and so can only ever answer "what would happen now". By the time anyone asks
// why last night's sweep opened nothing, the signals have moved. This reads
// the recorded verdicts instead.
//
// Three levels: pick a run → scan its per-tree verdicts → open one for the
// node walk. The middle level is where most questions are answered, so the
// skip reason is rendered inline there rather than behind the drilldown.

import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { EvalRun, EvalTrace, EvalTraceStatus } from "@/api/decisionTrees";
import { Card } from "@/components/Card";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { Modal } from "@/components/Modal";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Pill } from "@/components/Pill";
import { Toolbar, type FilterValues } from "@/components/Toolbar";
import { queryState } from "@/components/asyncState";
import { useEvalRuns, useEvalTrace, useEvalTraces } from "@/queries/decisionTrees";
import { useCapability } from "@/rbac/useCapability";

const STATUSES: readonly EvalTraceStatus[] = ["fired", "clear", "skipped", "error"];

const STATUS_KIND: Record<EvalTraceStatus, "ok" | "neutral" | "warn" | "crit"> = {
  fired: "ok",
  clear: "neutral",
  skipped: "warn",
  error: "crit",
};

function cellLabel(row: number | null, col: number | null): string | null {
  if (row === null || col === null) return null;
  return `R${row}·C${col}`;
}

export function DecisionTreeTracesPage(): ReactNode {
  const { t, i18n } = useTranslation("decisionTrees");
  const canRead = useCapability("decision_tree.read");

  const [runId, setRunId] = useState<string | null>(null);
  const [filters, setFilters] = useState<FilterValues>({});
  const [search, setSearch] = useState("");
  const [openTraceId, setOpenTraceId] = useState<string | null>(null);

  const runsQ = useEvalRuns(50);
  const runs = runsQ.data;

  // Default to the newest run rather than making the operator pick one — it is
  // the run they came here about in almost every case.
  const selectedRunId = runId ?? runs?.[0]?.id ?? null;

  const statusFilter = (filters.status ?? []) as EvalTraceStatus[];
  const tracesQ = useEvalTraces(
    {
      run_id: selectedRunId ?? undefined,
      status: statusFilter.length ? statusFilter : undefined,
      limit: 500,
    },
    Boolean(selectedRunId),
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return tracesQ.data ?? [];
    return (tracesQ.data ?? []).filter((row) =>
      `${row.tree_code} ${row.block_name ?? ""}`.toLowerCase().includes(q),
    );
  }, [tracesQ.data, search]);

  const dateFmt = useMemo(
    () =>
      new Intl.DateTimeFormat(i18n.language, {
        dateStyle: "medium",
        timeStyle: "short",
      }),
    [i18n.language],
  );

  if (!canRead) {
    return (
      <Page>
        <PageHeader title={t("traces.title")} subtitle={t("traces.subtitle")} />
        <p className="text-xs text-ap-muted">
          {t("traces.missingCapability", { capability: "decision_tree.read" })}
        </p>
      </Page>
    );
  }

  return (
    <Page>
      <PageHeader title={t("traces.title")} subtitle={t("traces.subtitle")} />

      <RunPicker
        runs={runs ?? []}
        loading={runsQ.isPending}
        selectedId={selectedRunId}
        onSelect={setRunId}
        dateFmt={dateFmt}
      />

      {runs && runs.length === 0 ? (
        <EmptyState message={t("traces.noRuns")} />
      ) : (
        <>
          <Toolbar
            search={{
              value: search,
              onChange: setSearch,
              placeholder: t("traces.search"),
              label: t("traces.searchAria"),
            }}
            axes={[
              {
                key: "status",
                label: t("traces.filters.status"),
                options: STATUSES.map((s) => ({
                  value: s,
                  label: t(`traces.status.${s}`),
                })),
              },
            ]}
            values={filters}
            onValuesChange={setFilters}
            resultCount={
              tracesQ.data ? { shown: filtered.length, total: tracesQ.data.length } : undefined
            }
          />

          <DataTable<EvalTrace>
            state={queryState(tracesQ)}
            rows={filtered}
            filtered={search.trim() !== "" || statusFilter.length > 0}
            rowKey={(row) => row.id}
            onRowClick={(row) => setOpenTraceId(row.id)}
            caption={t("traces.table.caption")}
            empty={<EmptyState message={t("traces.noTraces")} />}
            errorMessage={t("traces.loadFailed")}
            columns={[
              {
                key: "tree",
                header: t("traces.table.tree"),
                className: "font-mono text-xs",
                cell: (row) => `${row.tree_code} v${row.tree_version}`,
              },
              {
                key: "target",
                header: t("traces.table.target"),
                className: "text-xs",
                cell: (row) => (
                  <span className="flex items-center gap-1.5">
                    {row.block_name ?? row.block_id.slice(0, 8)}
                    {cellLabel(row.cell_row, row.cell_col) ? (
                      <Pill kind="neutral">
                        {t("traces.table.zone", {
                          zone: cellLabel(row.cell_row, row.cell_col),
                        })}
                      </Pill>
                    ) : null}
                  </span>
                ),
              },
              {
                key: "status",
                header: t("traces.table.status"),
                cell: (row) => (
                  <span className="flex items-center gap-1.5">
                    <Pill kind={STATUS_KIND[row.status]}>{t(`traces.status.${row.status}`)}</Pill>
                    {row.outcome?.deduped ? (
                      <Pill kind="neutral">{t("traces.table.deduped")}</Pill>
                    ) : null}
                  </span>
                ),
              },
              {
                key: "why",
                header: t("traces.table.why"),
                className: "text-xs text-ap-muted",
                cell: (row) => <WhyCell row={row} />,
              },
              {
                key: "duration",
                header: t("traces.table.duration"),
                className: "text-xs text-ap-muted tabular-nums",
                cell: (row) => (row.duration_ms === null ? "—" : `${row.duration_ms} ms`),
              },
            ]}
          />
        </>
      )}

      <TraceDetailModal traceId={openTraceId} onClose={() => setOpenTraceId(null)} />
    </Page>
  );
}

/**
 * The one-line answer to "why". For a skipped tree that is the targeting axis
 * and both sides of the comparison — the reason this column exists at all,
 * since "skipped" on its own is the non-answer the trace table replaced.
 */
function WhyCell({ row }: { row: EvalTrace }): ReactNode {
  const { t } = useTranslation("decisionTrees");

  if (row.status === "skipped" && row.skip_axis) {
    const required = row.skip_detail?.required ?? [];
    const actual = row.skip_detail?.actual;
    return (
      <span>
        {t(`traces.skipAxis.${row.skip_axis}`)}
        {": "}
        <span className="font-mono">{required.join(", ") || "—"}</span>
        {" ≠ "}
        <span className="font-mono">
          {actual === null || actual === undefined ? t("traces.unset") : actual}
        </span>
      </span>
    );
  }
  if (row.status === "error") return <span className="text-ap-crit">{row.error ?? "—"}</span>;
  if (row.status === "fired" && row.outcome?.action_type) {
    return (
      <span>
        {row.outcome.action_type}
        {row.outcome.severity ? ` · ${row.outcome.severity}` : ""}
      </span>
    );
  }
  return <span>—</span>;
}

function RunPicker({
  runs,
  loading,
  selectedId,
  onSelect,
  dateFmt,
}: {
  runs: readonly EvalRun[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  dateFmt: Intl.DateTimeFormat;
}): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const selected = runs.find((r) => r.id === selectedId) ?? null;

  return (
    <Card className="flex flex-col gap-2 p-3">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium text-ap-muted">{t("traces.run")}</span>
          <select
            value={selectedId ?? ""}
            disabled={loading || runs.length === 0}
            onChange={(e) => onSelect(e.target.value)}
            className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
          >
            {loading ? <option value="">{t("traces.loadingRuns")}</option> : null}
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                {`${dateFmt.format(new Date(run.started_at))} · ${t(`traces.runKind.${run.kind}`)}`}
              </option>
            ))}
          </select>
        </label>

        {selected ? (
          <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ap-muted">
            <Stat label={t("traces.runStats.blocks")} value={selected.blocks_evaluated} />
            <Stat label={t("traces.runStats.evaluated")} value={selected.trees_evaluated} />
            <Stat label={t("traces.runStats.skipped")} value={selected.trees_skipped} />
            <Stat label={t("traces.runStats.opened")} value={selected.recommendations_opened} />
            <Stat label={t("traces.runStats.traces")} value={selected.traces_written} />
            {selected.duration_ms !== null ? (
              <Stat
                label={t("traces.runStats.duration")}
                value={`${Math.round(selected.duration_ms / 1000)}s`}
              />
            ) : null}
          </dl>
        ) : null}
      </div>
      {selected?.finished_at === null ? (
        <p className="text-xs text-ap-muted">{t("traces.runInFlight")}</p>
      ) : null}
      {selected?.error ? <p className="text-xs text-ap-crit">{selected.error}</p> : null}
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: number | string }): ReactNode {
  return (
    <div className="flex items-center gap-1">
      <dt>{label}</dt>
      <dd className="font-medium tabular-nums text-ap-ink">{value}</dd>
    </div>
  );
}

function TraceDetailModal({
  traceId,
  onClose,
}: {
  traceId: string | null;
  onClose: () => void;
}): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const traceQ = useEvalTrace(traceId ?? undefined);
  const trace = traceQ.data;

  return (
    <Modal open={Boolean(traceId)} onClose={onClose} labelledBy="trace-detail-title">
      <div className="flex max-h-[80vh] flex-col gap-3 overflow-y-auto p-4">
        <h2 id="trace-detail-title" className="text-sm font-semibold text-ap-ink">
          {t("traces.detail.title")}
        </h2>

        {traceQ.isPending ? (
          <p className="text-xs text-ap-muted">{t("traces.detail.loading")}</p>
        ) : null}
        {traceQ.isError ? <p className="text-xs text-ap-crit">{t("traces.loadFailed")}</p> : null}

        {trace ? (
          <>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
              <Row
                label={t("traces.detail.tree")}
                value={`${trace.tree_code} v${trace.tree_version}`}
                mono
              />
              <Row label={t("traces.detail.block")} value={trace.block_name ?? trace.block_id} />
              {cellLabel(trace.cell_row, trace.cell_col) ? (
                <Row
                  label={t("traces.detail.zone")}
                  value={cellLabel(trace.cell_row, trace.cell_col) ?? ""}
                />
              ) : null}
              <Row label={t("traces.detail.status")} value={t(`traces.status.${trace.status}`)} />
            </dl>

            {trace.status === "skipped" ? (
              <p className="rounded-md bg-ap-bg/60 p-2 text-xs text-ap-ink">
                {t("traces.detail.skippedExplainer", {
                  axis: t(`traces.skipAxis.${trace.skip_axis ?? "crop"}`),
                  required: (trace.skip_detail?.required ?? []).join(", ") || "—",
                  actual:
                    trace.skip_detail?.actual === null || trace.skip_detail?.actual === undefined
                      ? t("traces.unset")
                      : trace.skip_detail.actual,
                })}
              </p>
            ) : null}

            {Object.keys(trace.param_overrides).length > 0 ? (
              <section className="flex flex-col gap-1">
                <h3 className="text-xs font-medium text-ap-muted">
                  {t("traces.detail.overrides")}
                </h3>
                <pre className="overflow-x-auto rounded-md bg-ap-bg/60 p-2 font-mono text-[10px] text-ap-ink">
                  {JSON.stringify(trace.param_overrides, null, 2)}
                </pre>
              </section>
            ) : null}

            {trace.node_path.length > 0 ? (
              <section className="flex flex-col gap-1">
                <h3 className="text-xs font-medium text-ap-muted">{t("traces.detail.walk")}</h3>
                <ol className="flex flex-col gap-1">
                  {trace.node_path.map((step, i) => (
                    <li
                      key={`${step.node_id}-${i}`}
                      className="rounded-md border border-ap-line p-2 text-xs"
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[11px]">{step.node_id}</span>
                        {step.matched === null ? (
                          <Pill kind="neutral">{t("traces.detail.leaf")}</Pill>
                        ) : (
                          <Pill kind={step.matched ? "ok" : "neutral"}>
                            {step.matched
                              ? t("traces.detail.matched")
                              : t("traces.detail.notMatched")}
                          </Pill>
                        )}
                      </div>
                      {step.label_en ? <p className="mt-0.5 text-ap-ink">{step.label_en}</p> : null}
                      {Object.keys(step.values ?? {}).length > 0 ? (
                        <ValueList values={step.values} />
                      ) : null}
                    </li>
                  ))}
                </ol>
              </section>
            ) : null}

            {Object.keys(trace.resolved_values).length > 0 ? (
              <section className="flex flex-col gap-1">
                <h3 className="text-xs font-medium text-ap-muted">{t("traces.detail.resolved")}</h3>
                <ValueList values={trace.resolved_values} />
              </section>
            ) : trace.status === "clear" ? (
              // Not a gap in the data — 0062 stores the walk but not the value
              // dump for a clear verdict. Saying so beats an empty section that
              // reads as missing data.
              <p className="text-[11px] text-ap-muted">{t("traces.detail.clearNoValues")}</p>
            ) : null}

            {trace.error ? <p className="text-xs text-ap-crit">{trace.error}</p> : null}
          </>
        ) : null}
      </div>
    </Modal>
  );
}

/**
 * Resolved refs. A null value is rendered explicitly as "no data" rather than
 * blank: a ref that resolved to null is why a predicate failed closed, and
 * blanking it hides the actual cause.
 */
function ValueList({ values }: { values: Record<string, unknown> }): ReactNode {
  const { t } = useTranslation("decisionTrees");
  return (
    <dl className="mt-1 flex flex-col gap-0.5">
      {Object.entries(values).map(([ref, value]) => (
        <div key={ref} className="flex items-baseline gap-2 text-[11px]">
          <dt className="font-mono text-ap-muted">{ref}</dt>
          <dd className={value === null ? "italic text-ap-muted" : "font-medium text-ap-ink"}>
            {value === null ? t("traces.detail.noData") : formatValue(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * The evaluator stringifies its resolved values (Decimals keep precision that
 * way), so these are almost always strings. A nested object would still be a
 * legitimate ref value, and `String(…)` would render it as [object Object].
 */
function formatValue(value: unknown): string {
  if (typeof value === "object") return JSON.stringify(value);
  // eslint-disable-next-line @typescript-eslint/no-base-to-string -- primitives only past the guard
  return String(value);
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }): ReactNode {
  return (
    <>
      <dt className="text-ap-muted">{label}</dt>
      <dd className={mono ? "font-mono text-ap-ink" : "text-ap-ink"}>{value}</dd>
    </>
  );
}
