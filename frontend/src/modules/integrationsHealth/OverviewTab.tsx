import { formatDistanceToNow, parseISO } from "date-fns";
import { Fragment, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { AttemptStatus } from "@/api/integrationsHealth";
import { Card } from "@/components/Card";
import { Pill, type PillKind } from "@/components/Pill";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { useDateLocale } from "@/hooks/useDateLocale";
import type { Status } from "@/lib/healthStatus";
import { statusFor } from "@/lib/healthStatus";
import {
  useBlockAttempts,
  useBlockIntegrationHealth,
  useFarmIntegrationHealth,
} from "@/queries/integrationsHealth";

export interface OverviewTabProps {
  basePath: string;
}

export function OverviewTab({ basePath }: OverviewTabProps): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  const [scope, setScope] = useState<"farms" | "blocks">("farms");
  const [selectedFarmId, setSelectedFarmId] = useState<string | null>(null);

  const farmsQ = useFarmIntegrationHealth(basePath);
  const blocksQ = useBlockIntegrationHealth(scope === "blocks" ? selectedFarmId : null, basePath);

  return (
    <div className="flex flex-col gap-3">
      <SegmentedControl
        ariaLabel={t("overviewScope.label")}
        items={[
          { value: "farms", label: t("tabs.farms") },
          { value: "blocks", label: t("tabs.blocks") },
        ]}
        value={scope}
        onChange={(v) => setScope(v)}
      />

      {scope === "farms" ? (
        <FarmsTable
          isLoading={farmsQ.isLoading}
          isError={farmsQ.isError}
          rows={farmsQ.data ?? []}
          onPick={(farmId) => {
            setSelectedFarmId(farmId);
            setScope("blocks");
          }}
        />
      ) : (
        <BlocksTable
          basePath={basePath}
          farmId={selectedFarmId}
          farmOptions={farmsQ.data ?? []}
          onChangeFarm={setSelectedFarmId}
          isLoading={blocksQ.isLoading}
          isError={blocksQ.isError}
          rows={blocksQ.data ?? []}
        />
      )}
    </div>
  );
}

interface FarmRow {
  farm_id: string;
  farm_name: string;
  weather_active_subs: number;
  weather_last_sync_at: string | null;
  weather_last_failed_at: string | null;
  imagery_active_subs: number;
  imagery_last_sync_at: string | null;
  imagery_failed_24h: number;
  weather_failed_24h: number;
  weather_running_count: number;
  imagery_running_count: number;
  weather_overdue_count: number;
  imagery_overdue_count: number;
}

function FarmsTable({
  isLoading,
  isError,
  rows,
  onPick,
}: {
  isLoading: boolean;
  isError: boolean;
  rows: FarmRow[];
  onPick: (farmId: string) => void;
}): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  if (isLoading) return <Skeleton className="h-32 w-full" />;
  if (isError) return <p className="text-sm text-ap-crit">{t("loadFailed")}</p>;
  if (rows.length === 0) return <p className="text-sm text-ap-muted">{t("empty")}</p>;
  return (
    <Card noPadding className="overflow-x-auto">
      <Table>
        <Thead>
          <Tr>
            <Th>{t("col.farm")}</Th>
            <Th>{t("col.weather")}</Th>
            <Th>{t("col.imagery")}</Th>
            <Th className="text-end">{t("col.actions")}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {rows.map((r) => (
            <Tr key={r.farm_id}>
              <Td className="text-ap-ink">{r.farm_name}</Td>
              <Td>
                <StatusCell
                  status={statusFor(
                    "weather",
                    r.weather_last_sync_at,
                    r.weather_failed_24h,
                    r.weather_active_subs,
                    r.weather_last_failed_at,
                  )}
                  lastSync={r.weather_last_sync_at}
                  activeSubs={r.weather_active_subs}
                  failed24h={r.weather_failed_24h}
                  runningCount={r.weather_running_count}
                  overdueCount={r.weather_overdue_count}
                />
              </Td>
              <Td>
                <StatusCell
                  status={statusFor(
                    "imagery",
                    r.imagery_last_sync_at,
                    r.imagery_failed_24h,
                    r.imagery_active_subs,
                  )}
                  lastSync={r.imagery_last_sync_at}
                  activeSubs={r.imagery_active_subs}
                  failed24h={r.imagery_failed_24h}
                  runningCount={r.imagery_running_count}
                  overdueCount={r.imagery_overdue_count}
                />
              </Td>
              <Td className="text-end">
                <button
                  type="button"
                  onClick={() => onPick(r.farm_id)}
                  className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
                >
                  {t("col.viewBlocks")}
                </button>
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </Card>
  );
}

interface BlockRow {
  block_id: string;
  farm_id: string;
  block_name: string;
  weather_active_subs: number;
  weather_last_sync_at: string | null;
  weather_last_failed_at: string | null;
  imagery_active_subs: number;
  imagery_last_sync_at: string | null;
  imagery_failed_24h: number;
  weather_failed_24h: number;
  weather_running_count: number;
  imagery_running_count: number;
  weather_overdue_count: number;
  imagery_overdue_count: number;
}

function BlocksTable({
  basePath,
  farmId,
  farmOptions,
  onChangeFarm,
  isLoading,
  isError,
  rows,
}: {
  basePath: string;
  farmId: string | null;
  farmOptions: FarmRow[];
  onChangeFarm: (id: string | null) => void;
  isLoading: boolean;
  isError: boolean;
  rows: BlockRow[];
}): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  // Which block's run log is open. One at a time: the log is the answer to
  // "why is this row red", and that question is asked about one row.
  const [expanded, setExpanded] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-3">
      <label className="flex items-center gap-2 text-sm">
        <span className="text-ap-muted">{t("blockTab.farmLabel")}</span>
        <select
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
          value={farmId ?? ""}
          onChange={(e) => onChangeFarm(e.target.value || null)}
        >
          <option value="">{t("blockTab.pickFarm")}</option>
          {farmOptions.map((f) => (
            <option key={f.farm_id} value={f.farm_id}>
              {f.farm_name}
            </option>
          ))}
        </select>
      </label>
      {!farmId ? (
        <p className="text-sm text-ap-muted">{t("blockTab.pickPrompt")}</p>
      ) : isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : isError ? (
        <p className="text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-ap-muted">{t("blockTab.empty")}</p>
      ) : (
        <Card noPadding className="overflow-x-auto">
          <Table>
            <Thead>
              <Tr>
                <Th>{t("col.block")}</Th>
                <Th>{t("col.weather")}</Th>
                <Th>{t("col.imagery")}</Th>
                <Th className="text-end">{t("col.actions")}</Th>
              </Tr>
            </Thead>
            <Tbody>
              {rows.map((r) => {
                const isOpen = expanded === r.block_id;
                return (
                  <Fragment key={r.block_id}>
                    <Tr>
                      <Td className="text-ap-ink">{r.block_name}</Td>
                      <Td>
                        <StatusCell
                          status={statusFor(
                            "weather",
                            r.weather_last_sync_at,
                            r.weather_failed_24h,
                            r.weather_active_subs,
                            r.weather_last_failed_at,
                          )}
                          lastSync={r.weather_last_sync_at}
                          activeSubs={r.weather_active_subs}
                          failed24h={r.weather_failed_24h}
                          runningCount={r.weather_running_count}
                          overdueCount={r.weather_overdue_count}
                        />
                      </Td>
                      <Td>
                        <StatusCell
                          status={statusFor(
                            "imagery",
                            r.imagery_last_sync_at,
                            r.imagery_failed_24h,
                            r.imagery_active_subs,
                          )}
                          lastSync={r.imagery_last_sync_at}
                          activeSubs={r.imagery_active_subs}
                          failed24h={r.imagery_failed_24h}
                          runningCount={r.imagery_running_count}
                          overdueCount={r.imagery_overdue_count}
                        />
                      </Td>
                      <Td className="text-end">
                        {/* The run log answers "why". Its endpoint has
                            existed since PR-IH3 and nothing on this page
                            called it, so a reader who saw a red block had
                            nowhere to go. */}
                        <button
                          type="button"
                          aria-expanded={isOpen}
                          onClick={() => setExpanded(isOpen ? null : r.block_id)}
                          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
                        >
                          {isOpen ? t("blockTab.hideRuns") : t("blockTab.viewRuns")}
                        </button>
                      </Td>
                    </Tr>
                    {isOpen ? (
                      <Tr className="bg-ap-bg/30">
                        <Td colSpan={4} className="py-3">
                          <BlockRunLog basePath={basePath} blockId={r.block_id} />
                        </Td>
                      </Tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </Tbody>
          </Table>
        </Card>
      )}
    </div>
  );
}

/**
 * The last runs that covered one block, newest first.
 *
 * "Covered" includes the farm-scoped runs of the block's own farm. A block
 * on a farm that acquires as one AOI records no runs of its own, so keying
 * on the block alone would show an empty log for a block ingested every
 * day. The Scope column says which of the two a row was.
 */
function BlockRunLog({ basePath, blockId }: { basePath: string; blockId: string }): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  const dateLocale = useDateLocale();
  const q = useBlockAttempts(blockId, undefined, basePath);
  const rows = q.data ?? [];

  if (q.isLoading) return <Skeleton className="h-20 w-full" />;
  if (q.isError) return <p className="text-xs text-ap-crit">{t("loadFailed")}</p>;
  if (rows.length === 0) return <p className="text-xs text-ap-muted">{t("blockTab.runsEmpty")}</p>;

  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-xs font-medium uppercase text-ap-muted">{t("blockTab.runsTitle")}</h3>
      <ul className="divide-y divide-ap-line text-xs">
        {rows.slice(0, 20).map((a) => (
          <li key={a.attempt_id} className="flex flex-wrap items-center gap-2 py-1.5">
            <span className="w-16 shrink-0 text-ap-ink">{t(`kind.${a.kind}`)}</span>
            <Pill kind={a.scope === "farm" ? "info" : "neutral"}>{t(`scope.${a.scope}`)}</Pill>
            <Pill kind={pillForAttempt(a.status)}>{t(`attemptStatus.${a.status}`)}</Pill>
            <span className="font-mono text-ap-muted">{a.provider_code ?? "—"}</span>
            <span className="text-ap-muted">
              {formatDistanceToNow(parseISO(a.started_at), {
                addSuffix: true,
                locale: dateLocale,
              })}
            </span>
            {a.error_code ? (
              <span className="truncate text-ap-crit" title={a.error_message ?? ""}>
                {a.error_code}
              </span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function pillForAttempt(status: AttemptStatus): PillKind {
  switch (status) {
    case "succeeded":
      return "ok";
    case "failed":
      return "crit";
    case "running":
      return "info";
    case "skipped":
      return "neutral";
  }
}

function StatusCell({
  status,
  lastSync,
  activeSubs,
  failed24h,
  runningCount,
  overdueCount,
}: {
  status: Status;
  lastSync: string | null;
  activeSubs: number;
  failed24h?: number;
  runningCount?: number;
  overdueCount?: number;
}): ReactNode {
  const { t } = useTranslation("integrationsHealth");
  const dateLocale = useDateLocale();
  const kind = status === "neutral" ? "neutral" : status;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <Pill kind={kind}>{t(`status.${status}`)}</Pill>
        <span className="text-xs text-ap-muted">
          {activeSubs === 0
            ? t("noActive")
            : lastSync
              ? t("lastSync", {
                  when: formatDistanceToNow(parseISO(lastSync), {
                    addSuffix: true,
                    locale: dateLocale,
                  }),
                })
              : t("neverSynced")}
        </span>
      </div>
      {(failed24h && failed24h > 0) ||
      (runningCount && runningCount > 0) ||
      (overdueCount && overdueCount > 0) ? (
        <div className="flex flex-wrap gap-1.5">
          {failed24h && failed24h > 0 ? (
            <Pill kind="crit">{t("badge.failed24h", { n: failed24h })}</Pill>
          ) : null}
          {runningCount && runningCount > 0 ? (
            <Pill kind="info">{t("badge.running", { n: runningCount })}</Pill>
          ) : null}
          {overdueCount && overdueCount > 0 ? (
            <Pill kind="warn">{t("badge.overdue", { n: overdueCount })}</Pill>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
