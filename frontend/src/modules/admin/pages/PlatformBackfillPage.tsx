import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { BackfillRun, RunKind, RunStatus } from "@/api/backfill";
import { estimateBackfill, type BackfillEstimate } from "@/api/backfill";
import { isApiError } from "@/api/errors";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import {
  useBackfillFarms,
  useBackfillRuns,
  useBackfillTenants,
  useCreateBackfillRun,
} from "@/queries/backfill";

type Tab = "backfill" | "indices" | "runs";

function apiMsg(err: unknown): string {
  return isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err);
}

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

// ---------------------------------------------------------------- tabs

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}): ReactNode {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`rounded px-3 py-1.5 text-xs font-semibold transition ${
        active ? "bg-ap-primary text-white" : "text-ap-muted hover:text-ap-ink"
      }`}
    >
      {children}
    </button>
  );
}

// ------------------------------------------------------------- shared form

interface FormState {
  tenantId: string;
  farmId: string;
  from: string;
  to: string;
  imagery: boolean;
  weather: boolean;
}

function useRunForm(defaultFrom: string): [FormState, (patch: Partial<FormState>) => void] {
  const [state, setState] = useState<FormState>({
    tenantId: "",
    farmId: "",
    from: defaultFrom,
    to: today(),
    imagery: true,
    weather: true,
  });
  const patch = (p: Partial<FormState>): void => setState((s) => ({ ...s, ...p }));
  return [state, patch];
}

function TenantFarmFields({
  form,
  patch,
  label,
  idPrefix,
}: {
  form: FormState;
  patch: (p: Partial<FormState>) => void;
  label: { tenant: string; farm: string; pick: string; busy: string; blocks: string };
  // Both composers mount the same fields; unique ids keep htmlFor honest.
  idPrefix: string;
}): ReactNode {
  const tenantsQ = useBackfillTenants();
  const farmsQ = useBackfillFarms(form.tenantId || null);

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="flex flex-col gap-1">
        <label
          htmlFor={`${idPrefix}-tenant`}
          className="text-xs font-semibold uppercase tracking-wide text-ap-muted"
        >
          {label.tenant}
        </label>
        <select
          id={`${idPrefix}-tenant`}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1.5 text-sm"
          value={form.tenantId}
          onChange={(e) => patch({ tenantId: e.target.value, farmId: "" })}
        >
          <option value="">{label.pick}</option>
          {(tenantsQ.data ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label
          htmlFor={`${idPrefix}-farm`}
          className="text-xs font-semibold uppercase tracking-wide text-ap-muted"
        >
          {label.farm}
        </label>
        <select
          id={`${idPrefix}-farm`}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1.5 text-sm disabled:opacity-50"
          value={form.farmId}
          disabled={!form.tenantId || farmsQ.isLoading}
          onChange={(e) => patch({ farmId: e.target.value })}
        >
          <option value="">{label.pick}</option>
          {(farmsQ.data ?? []).map((f) => (
            // A farm already holding a run cannot take another — disable it
            // here rather than letting the submit 409.
            <option key={f.id} value={f.id} disabled={Boolean(f.active_run_id)}>
              {f.name ?? f.code} · {f.block_count} {label.blocks}
              {f.active_run_id ? ` — ${label.busy}` : ""}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function WindowFields({
  form,
  patch,
  label,
}: {
  form: FormState;
  patch: (p: Partial<FormState>) => void;
  label: { from: string; to: string };
}): ReactNode {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="flex flex-col gap-1">
        <span className="text-xs font-semibold uppercase tracking-wide text-ap-muted">
          {label.from}
        </span>
        <input
          type="date"
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1.5 text-sm"
          value={form.from}
          onChange={(e) => patch({ from: e.target.value })}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs font-semibold uppercase tracking-wide text-ap-muted">
          {label.to}
        </span>
        <input
          type="date"
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1.5 text-sm"
          value={form.to}
          onChange={(e) => patch({ to: e.target.value })}
        />
      </label>
    </div>
  );
}

function SourceCheck({
  checked,
  onChange,
  title,
  hint,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  title: string;
  hint: string;
}): ReactNode {
  // The hint sits OUTSIDE the label on purpose: help text inside a label
  // gets folded into the control's accessible name, so a screen reader
  // would read the entire paragraph as the checkbox's name.
  return (
    <div
      className={`rounded-md border p-2.5 ${
        checked ? "border-ap-accent bg-ap-accent/5" : "border-ap-line"
      }`}
    >
      <label className="flex cursor-pointer items-center gap-2.5 text-sm font-semibold">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        {title}
      </label>
      <p className="mt-1 ps-6 text-xs text-ap-muted">{hint}</p>
    </div>
  );
}

// ------------------------------------------------------------ runs table

function StatusPill({ status, label }: { status: RunStatus; label: string }): ReactNode {
  const tone: Record<RunStatus, string> = {
    queued: "bg-ap-bg text-ap-muted border border-ap-line",
    running: "bg-ap-warn-soft text-ap-warn",
    succeeded: "bg-ap-primary-soft text-ap-good",
    partial: "bg-ap-warn-soft text-ap-accent",
    failed: "bg-ap-crit-soft text-ap-crit",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${tone[status]}`}>
      {label}
    </span>
  );
}

function summarise(run: BackfillRun): string {
  // Counters are free-form per source; render whatever the tasks wrote
  // rather than guessing at a fixed shape.
  const parts: string[] = [];
  for (const [source, counters] of Object.entries(run.progress ?? {})) {
    const nums = Object.entries(counters ?? {})
      .filter(([, v]) => typeof v === "number")
      .map(([k, v]) => `${k} ${String(v)}`);
    if (nums.length) parts.push(`${source}: ${nums.join(", ")}`);
  }
  return parts.join(" · ");
}

function RunsTable({ runs }: { runs: BackfillRun[] }): ReactNode {
  const { t } = useTranslation("admin");
  if (!runs.length) {
    return <p className="text-sm text-ap-muted">{t("backfill.runs.empty")}</p>;
  }
  return (
    <div className="overflow-x-auto">
      <Table className="min-w-[720px]">
        <Thead>
          <Tr>
            <Th className="p-2">{t("backfill.runs.status")}</Th>
            <Th className="p-2">{t("backfill.runs.target")}</Th>
            <Th className="p-2">{t("backfill.runs.window")}</Th>
            <Th className="p-2">{t("backfill.runs.sources")}</Th>
            <Th className="p-2">{t("backfill.runs.progress")}</Th>
            <Th className="p-2">{t("backfill.runs.startedBy")}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {runs.map((r) => (
            <Tr key={r.id} className="align-top">
              <Td className="p-2">
                <StatusPill status={r.status} label={t(`backfill.status.${r.status}`)} />
                {r.error ? <div className="mt-1 text-xs text-ap-crit">{r.error}</div> : null}
              </Td>
              <Td className="p-2">
                {r.tenant_name}
                <div className="text-xs text-ap-muted">{r.farm_name}</div>
              </Td>
              <Td className="p-2 tabular-nums">
                {r.window_from}
                <div className="text-xs text-ap-muted tabular-nums">→ {r.window_to}</div>
              </Td>
              <Td className="p-2">
                <span className="text-xs">
                  {Object.entries(r.sources ?? {})
                    .filter(([, on]) => on)
                    .map(([s]) => t(`backfill.source.${s}`))
                    .join(", ")}
                </span>
                <div className="text-xs text-ap-muted">{t(`backfill.kind.${r.kind}`)}</div>
              </Td>
              <Td className="p-2">{summarise(r) || "—"}</Td>
              <Td className="p-2">
                {r.created_by_email ?? "—"}
                <div className="text-ap-muted tabular-nums">{r.created_at.slice(0, 16)}</div>
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </div>
  );
}

// ------------------------------------------------------------------ page

export function PlatformBackfillPage(): ReactNode {
  const { t } = useTranslation("admin");
  const [tab, setTab] = useState<Tab>("backfill");
  const runsQ = useBackfillRuns();

  const activeCount = useMemo(
    () => (runsQ.data ?? []).filter((r) => r.status === "queued" || r.status === "running").length,
    [runsQ.data],
  );

  return (
    <Page>
      <div>
        <PageHeader title={t("backfill.title")} subtitle={t("backfill.subtitle")} />
      </div>

      <div
        className="inline-flex w-fit rounded-md border border-ap-line bg-ap-panel p-0.5"
        role="tablist"
        aria-label={t("backfill.title")}
      >
        <TabButton active={tab === "backfill"} onClick={() => setTab("backfill")}>
          {t("backfill.tabs.backfill")}
        </TabButton>
        <TabButton active={tab === "indices"} onClick={() => setTab("indices")}>
          {t("backfill.tabs.indices")}
        </TabButton>
        <TabButton active={tab === "runs"} onClick={() => setTab("runs")}>
          {t("backfill.tabs.runs")}
          {activeCount > 0 ? ` (${String(activeCount)})` : ""}
        </TabButton>
      </div>

      {tab === "backfill" ? <RunComposer kind="backfill" /> : null}
      {tab === "indices" ? <RunComposer kind="indices" /> : null}
      {tab === "runs" ? (
        runsQ.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : (
          <RunsTable runs={runsQ.data ?? []} />
        )
      ) : null}
    </Page>
  );
}

function RunComposer({ kind }: { kind: RunKind }): ReactNode {
  const { t } = useTranslation("admin");
  const isIndices = kind === "indices";
  const [form, patch] = useRunForm(isoDaysAgo(isIndices ? 30 : 365));
  const [estimate, setEstimate] = useState<BackfillEstimate | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const createRun = useCreateBackfillRun();

  const ready = Boolean(form.tenantId && form.farmId && (form.imagery || form.weather));

  const runEstimate = async (): Promise<void> => {
    setError(null);
    setEstimating(true);
    try {
      setEstimate(
        await estimateBackfill(form.tenantId, {
          farm_id: form.farmId,
          window_from: form.from,
          window_to: form.to,
          imagery: form.imagery,
          weather: form.weather,
        }),
      );
    } catch (err) {
      setError(apiMsg(err));
    } finally {
      setEstimating(false);
    }
  };

  const submit = async (): Promise<void> => {
    setError(null);
    setDone(null);
    try {
      const run = await createRun.mutateAsync({
        tenantId: form.tenantId,
        payload: {
          farm_id: form.farmId,
          window_from: form.from,
          window_to: form.to,
          imagery: form.imagery,
          weather: form.weather,
          kind,
        },
      });
      setDone(run.id);
      setEstimate(null);
    } catch (err) {
      setError(apiMsg(err));
    }
  };

  const labels = {
    tenant: t("backfill.form.tenant"),
    farm: t("backfill.form.farm"),
    pick: t("backfill.form.pick"),
    busy: t("backfill.form.busy"),
    blocks: t("backfill.form.blocks"),
  };

  return (
    <div className="flex max-w-3xl flex-col gap-4 rounded-md border border-ap-line bg-ap-panel p-4">
      <TenantFarmFields form={form} patch={patch} label={labels} idPrefix={kind} />
      <WindowFields
        form={form}
        patch={patch}
        label={{ from: t("backfill.form.from"), to: t("backfill.form.to") }}
      />

      <div className="flex flex-col gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-ap-muted">
          {isIndices ? t("backfill.form.compute") : t("backfill.form.sources")}
        </span>
        <SourceCheck
          checked={form.imagery}
          onChange={(v) => patch({ imagery: v })}
          title={isIndices ? t("backfill.source.imageryIndices") : t("backfill.source.imagery")}
          hint={isIndices ? t("backfill.hint.imageryIndices") : t("backfill.hint.imagery")}
        />
        <SourceCheck
          checked={form.weather}
          onChange={(v) => patch({ weather: v })}
          title={isIndices ? t("backfill.source.weatherIndices") : t("backfill.source.weather")}
          hint={isIndices ? t("backfill.hint.weatherIndices") : t("backfill.hint.weather")}
        />
        <p className="text-xs text-ap-muted">
          {isIndices ? t("backfill.hint.indicesFree") : t("backfill.hint.rawOnly")}
        </p>
      </div>

      {estimate ? (
        <div className="rounded-md border border-ap-warn bg-ap-warn-soft p-3 text-xs">
          <div className="font-semibold">{t("backfill.estimate.title")}</div>
          <div className="mt-1 tabular-nums">
            {t("backfill.estimate.body", {
              days: estimate.days,
              blocks: estimate.blocks,
              subscriptions: estimate.subscriptions,
              scenes: estimate.estimated_scenes,
            })}
          </div>
          {estimate.units_estimated ? (
            <div className="mt-1">
              {t("backfill.estimate.units", { units: estimate.estimated_units })}
            </div>
          ) : null}
          {/* A source with no subscription would fetch nothing. Say so here,
              even though the API also refuses the run, so the operator is
              never surprised by a rejection after filling in the form. */}
          {form.imagery && estimate.subscriptions === 0 ? (
            <div className="mt-1.5 font-semibold text-ap-crit">
              {t("backfill.estimate.noImagerySubs")}
            </div>
          ) : null}
          {form.weather && estimate.weather_subscriptions === 0 ? (
            <div className="mt-1.5 font-semibold text-ap-crit">
              {t("backfill.estimate.noWeatherSubs")}
            </div>
          ) : null}
        </div>
      ) : null}

      {error ? <p className="text-sm text-ap-crit">{error}</p> : null}
      {done ? <p className="text-sm text-ap-good">{t("backfill.started")}</p> : null}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!ready || createRun.isPending}
          onClick={() => void submit()}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
        >
          {isIndices ? t("backfill.actions.compute") : t("backfill.actions.start")}
        </button>
        {!isIndices ? (
          <button
            type="button"
            disabled={!ready || estimating}
            onClick={() => void runEstimate()}
            className="rounded-md border border-ap-line px-3 py-1.5 text-sm disabled:opacity-50"
          >
            {t("backfill.actions.dryRun")}
          </button>
        ) : null}
      </div>
    </div>
  );
}
