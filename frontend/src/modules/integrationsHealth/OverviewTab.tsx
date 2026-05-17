import { formatDistanceToNow, parseISO, differenceInHours } from "date-fns";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Pill } from "@/components/Pill";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Skeleton } from "@/components/Skeleton";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useBlockIntegrationHealth, useFarmIntegrationHealth } from "@/queries/integrationsHealth";

type Status = "ok" | "warn" | "crit" | "neutral";

function statusFor(
  lastSyncIso: string | null,
  lastFailedIso: string | null,
  failed24h: number,
  activeSubs: number,
): Status {
  if (activeSubs === 0) return "neutral";
  const now = new Date();
  if (failed24h > 0) return "crit";
  if (!lastSyncIso) return "crit";
  const hours = differenceInHours(now, parseISO(lastSyncIso));
  if (hours > 24) return "crit";
  if (hours > 6) return "warn";
  if (lastFailedIso) {
    const failedHours = differenceInHours(now, parseISO(lastFailedIso));
    if (failedHours < 24) return "warn";
  }
  return "ok";
}

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
    <div className="overflow-x-auto rounded-xl border border-ap-line bg-ap-panel">
      <table className="min-w-full text-sm">
        <thead className="bg-ap-bg/40 text-xs uppercase text-ap-muted">
          <tr>
            <th className="px-3 py-2 text-start">{t("col.farm")}</th>
            <th className="px-3 py-2 text-start">{t("col.weather")}</th>
            <th className="px-3 py-2 text-start">{t("col.imagery")}</th>
            <th className="px-3 py-2 text-end">{t("col.actions")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ap-line">
          {rows.map((r) => (
            <tr key={r.farm_id}>
              <td className="px-3 py-2 text-ap-ink">{r.farm_name}</td>
              <td className="px-3 py-2">
                <StatusCell
                  status={statusFor(
                    r.weather_last_sync_at,
                    r.weather_last_failed_at,
                    r.weather_failed_24h,
                    r.weather_active_subs,
                  )}
                  lastSync={r.weather_last_sync_at}
                  activeSubs={r.weather_active_subs}
                  failed24h={r.weather_failed_24h}
                  runningCount={r.weather_running_count}
                  overdueCount={r.weather_overdue_count}
                />
              </td>
              <td className="px-3 py-2">
                <StatusCell
                  status={statusFor(
                    r.imagery_last_sync_at,
                    null,
                    r.imagery_failed_24h,
                    r.imagery_active_subs,
                  )}
                  lastSync={r.imagery_last_sync_at}
                  activeSubs={r.imagery_active_subs}
                  failed24h={r.imagery_failed_24h}
                  runningCount={r.imagery_running_count}
                  overdueCount={r.imagery_overdue_count}
                />
              </td>
              <td className="px-3 py-2 text-end">
                <button
                  type="button"
                  onClick={() => onPick(r.farm_id)}
                  className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
                >
                  {t("col.viewBlocks")}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
  farmId,
  farmOptions,
  onChangeFarm,
  isLoading,
  isError,
  rows,
}: {
  farmId: string | null;
  farmOptions: FarmRow[];
  onChangeFarm: (id: string | null) => void;
  isLoading: boolean;
  isError: boolean;
  rows: BlockRow[];
}): ReactNode {
  const { t } = useTranslation("integrationsHealth");
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
        <div className="overflow-x-auto rounded-xl border border-ap-line bg-ap-panel">
          <table className="min-w-full text-sm">
            <thead className="bg-ap-bg/40 text-xs uppercase text-ap-muted">
              <tr>
                <th className="px-3 py-2 text-start">{t("col.block")}</th>
                <th className="px-3 py-2 text-start">{t("col.weather")}</th>
                <th className="px-3 py-2 text-start">{t("col.imagery")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ap-line">
              {rows.map((r) => (
                <tr key={r.block_id}>
                  <td className="px-3 py-2 text-ap-ink">{r.block_name}</td>
                  <td className="px-3 py-2">
                    <StatusCell
                      status={statusFor(
                        r.weather_last_sync_at,
                        r.weather_last_failed_at,
                        r.weather_failed_24h,
                        r.weather_active_subs,
                      )}
                      lastSync={r.weather_last_sync_at}
                      activeSubs={r.weather_active_subs}
                      failed24h={r.weather_failed_24h}
                      runningCount={r.weather_running_count}
                      overdueCount={r.weather_overdue_count}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <StatusCell
                      status={statusFor(
                        r.imagery_last_sync_at,
                        null,
                        r.imagery_failed_24h,
                        r.imagery_active_subs,
                      )}
                      lastSync={r.imagery_last_sync_at}
                      activeSubs={r.imagery_active_subs}
                      failed24h={r.imagery_failed_24h}
                      runningCount={r.imagery_running_count}
                      overdueCount={r.imagery_overdue_count}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
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
