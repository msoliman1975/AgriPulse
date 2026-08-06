import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { VerifyMode } from "@/api/observer";
import { isApiError } from "@/api/errors";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { useCancelVerifyRun, useCreateVerifyRun, useVerifyRuns } from "@/queries/observer";

/**
 * Named verification runs for the selected farm.
 *
 * A full verify of one year across 36 blocks is roughly 2,500 recomputations,
 * which is not a request/response — so this follows the Backfill Console's
 * model: queue a run, watch progress, cancel if it hangs. One run per farm,
 * enforced server-side.
 */

const STATUS_KIND: Record<string, "ok" | "warn" | "crit" | "neutral" | "info"> = {
  queued: "neutral",
  running: "info",
  succeeded: "ok",
  failed: "crit",
  cancelled: "warn",
};

export function VerifyRunsCard({
  tenantId,
  farmId,
  windowFrom,
  windowTo,
  blockIds,
  productId,
}: {
  tenantId: string;
  farmId: string;
  windowFrom: string;
  windowTo: string;
  blockIds: string[];
  productId: string | null;
}): ReactNode {
  const { t, i18n } = useTranslation("admin");
  const [mode, setMode] = useState<VerifyMode>("full");

  const runs = useVerifyRuns(tenantId, farmId);
  const create = useCreateVerifyRun(tenantId);
  const cancel = useCancelVerifyRun(tenantId);

  const conflict = isApiError(create.error) && create.error.problem.status === 409;

  return (
    <Card
      title={t("observer.verify.runs.title")}
      actions={
        <div className="flex items-center gap-2">
          <select
            className="rounded border border-ap-line bg-ap-panel px-2 py-1 text-xs"
            value={mode}
            onChange={(e) => setMode(e.target.value as VerifyMode)}
            aria-label={t("observer.verify.mode")}
          >
            <option value="full">{t("observer.verify.modeFull")}</option>
            <option value="fast">{t("observer.verify.modeFast")}</option>
          </select>
          <Button
            size="sm"
            disabled={create.isPending}
            onClick={() =>
              create.mutate({
                farm_id: farmId,
                window_from: windowFrom,
                window_to: windowTo,
                mode,
                block_ids: blockIds.length ? blockIds : null,
                product_id: productId,
              })
            }
          >
            {create.isPending
              ? t("observer.verify.runs.starting")
              : t("observer.verify.runs.start")}
          </Button>
        </div>
      }
    >
      <p className="mb-3 text-xs text-ap-muted">{t("observer.verify.runs.explain")}</p>

      {conflict ? (
        <p className="mb-3 border-s-2 border-ap-warn ps-3 text-xs">
          {t("observer.verify.runs.conflict")}
        </p>
      ) : null}

      {runs.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : (runs.data ?? []).length === 0 ? (
        <EmptyState message={t("observer.verify.runs.empty")} />
      ) : (
        <Table className="text-xs">
          <Thead>
            <Tr>
              <Th>{t("observer.verify.runs.scope")}</Th>
              <Th>{t("observer.verify.runs.mode")}</Th>
              <Th>{t("observer.verify.runs.progress")}</Th>
              <Th>{t("observer.verify.runs.findings")}</Th>
              <Th>{t("observer.verify.runs.started")}</Th>
              <Th />
            </Tr>
          </Thead>
          <Tbody>
            {(runs.data ?? []).map((run) => {
              const done = run.progress.scenes_done ?? 0;
              const total = run.progress.scenes_total ?? 0;
              const active = run.status === "queued" || run.status === "running";
              return (
                <Tr key={run.id}>
                  <Td>
                    <div>
                      {run.window_from.slice(0, 10)} → {run.window_to.slice(0, 10)}
                    </div>
                    <div className="text-ap-muted">
                      {run.block_ids ? `${run.block_ids.length} blocks` : "all blocks"}
                    </div>
                  </Td>
                  <Td>{run.mode}</Td>
                  <Td>
                    <Pill kind={STATUS_KIND[run.status] ?? "neutral"}>{run.status}</Pill>
                    {total ? (
                      <div className="mt-1 text-ap-muted">
                        {t("observer.verify.runs.of", { done, total })}
                      </div>
                    ) : null}
                  </Td>
                  <Td>
                    {/*
                     * Drift is the only number anyone reads on a 2,500-scene
                     * run, so it is shown even when zero — an absent count
                     * reads as "not checked" rather than "nothing found".
                     */}
                    <span className="text-ap-primary">
                      {t("observer.verify.runs.matched", { n: run.progress.match ?? 0 })}
                    </span>
                    <span className="ms-2 font-semibold text-ap-crit">
                      {t("observer.verify.runs.drifted", { n: run.progress.drift ?? 0 })}
                    </span>
                    {run.progress.error ? (
                      <span className="ms-2 text-ap-warn">
                        {t("observer.verify.runs.errored", { n: run.progress.error })}
                      </span>
                    ) : null}
                  </Td>
                  <Td className="tabular-nums">
                    {new Date(run.created_at).toLocaleString(i18n.language)}
                  </Td>
                  <Td>
                    {active ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={cancel.isPending}
                        onClick={() => cancel.mutate(run.id)}
                      >
                        {t("observer.verify.runs.cancel")}
                      </Button>
                    ) : null}
                  </Td>
                </Tr>
              );
            })}
          </Tbody>
        </Table>
      )}
    </Card>
  );
}
