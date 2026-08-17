import clsx from "clsx";
import { Fragment, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { JobStatus, ObserverScene } from "@/api/observer";
import { EmptyState } from "@/components/EmptyState";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { useSceneIndices } from "@/queries/observer";

const STATUS_KIND: Record<JobStatus, "ok" | "warn" | "crit" | "neutral"> = {
  succeeded: "ok",
  pending: "neutral",
  running: "neutral",
  failed: "crit",
  skipped_cloud: "warn",
  skipped_duplicate: "warn",
  // A farm acquisition skips without saying why — same event to a reader.
  skipped: "warn",
};

function fmtPct(v: number | null): string {
  return v === null ? "—" : `${v.toFixed(1)}%`;
}

function fmtDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  return seconds < 60 ? `${seconds.toFixed(1)} s` : `${(seconds / 60).toFixed(1)} m`;
}

function ExpandedIndices({
  tenantId,
  farmId,
  scene,
}: {
  tenantId: string;
  farmId: string;
  scene: ObserverScene;
}): ReactNode {
  const { t } = useTranslation("admin");
  // A farm acquisition wrote an aggregate on every block, so it is asked for
  // by farm and comes back one row per (block, index). Asking by block would
  // send a null and return nothing — which is how a thermal scene's stored
  // values ended up with no surface in the product at all.
  const { data, isPending } = useSceneIndices(tenantId, {
    blockId: scene.block_id,
    farmId,
    productId: scene.product_id,
    sceneTime: scene.scene_datetime,
  });

  if (isPending) return <Skeleton className="h-24 w-full" />;
  if (!data || data.length === 0) {
    return <p className="text-xs text-ap-muted">{t("observer.scenes.noAggregates")}</p>;
  }

  // A whole-farm fetch wrote an aggregate on EVERY block, so this comes back
  // one row per (block, index) — three thermal codes on a four-block farm is
  // twelve rows. Without the block column that reads as unexplained
  // duplication, which is exactly how it was reported.
  const perBlock = scene.scope === "farm";
  const blockCount = perBlock ? new Set(data.map((r) => r.block_id)).size : 0;

  return (
    <>
      {perBlock ? (
        <p className="mb-2 text-xs text-ap-muted">
          {t("observer.scenes.perBlockNote", { count: blockCount })}
        </p>
      ) : null}
      <Table className="text-xs">
        <Thead>
          <Tr>
            {perBlock ? <Th>{t("observer.scenes.block")}</Th> : null}
            <Th>{t("observer.scenes.index")}</Th>
            <Th className="text-end">{t("observer.scenes.mean")}</Th>
            <Th className="text-end">{t("observer.scenes.min")}</Th>
            <Th className="text-end">P10</Th>
            <Th className="text-end">P50</Th>
            <Th className="text-end">P90</Th>
            <Th className="text-end">{t("observer.scenes.max")}</Th>
            <Th className="text-end">{t("observer.scenes.std")}</Th>
            <Th className="text-end" title={t("observer.tooltip.validTotalPx")}>
              {t("observer.scenes.validPx")}
            </Th>
            <Th className="text-end">{t("observer.scenes.baselineZ")}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {data.map((row) => (
            <Tr key={`${row.block_id ?? "farm"}-${row.index_code}`}>
              {perBlock ? <Td className="whitespace-nowrap">{row.block_name ?? "—"}</Td> : null}
              <Td className="font-medium uppercase">{row.index_code}</Td>
              <Td className="text-end tabular-nums">{row.mean ?? "—"}</Td>
              <Td className="text-end tabular-nums">{row.min ?? "—"}</Td>
              <Td className="text-end tabular-nums">{row.p10 ?? "—"}</Td>
              <Td className="text-end tabular-nums">{row.p50 ?? "—"}</Td>
              <Td className="text-end tabular-nums">{row.p90 ?? "—"}</Td>
              <Td className="text-end tabular-nums">{row.max ?? "—"}</Td>
              <Td className="text-end tabular-nums">{row.std_dev ?? "—"}</Td>
              <Td className="text-end tabular-nums">
                {row.valid_pixel_count.toLocaleString()} / {row.total_pixel_count.toLocaleString()}
              </Td>
              <Td className="text-end tabular-nums">{row.baseline_deviation ?? "—"}</Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
      <p className="mt-2 text-[0.6875rem] text-ap-muted">{t("observer.scenes.validPxExplain")}</p>
    </>
  );
}

export function SceneTable({
  tenantId,
  farmId,
  scenes,
  isLoading,
  isError = false,
  expanded,
  onToggleExpand,
}: {
  tenantId: string;
  /** Needed to expand a whole-farm row, which has no block to ask by. */
  farmId: string;
  scenes: ObserverScene[];
  isLoading: boolean;
  /** The scenes query failed. Must be distinguished from an empty result. */
  isError?: boolean;
  expanded: string | null;
  onToggleExpand: (jobId: string | null) => void;
}): ReactNode {
  const { t, i18n } = useTranslation("admin");

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  // Before the length check, not after: a failed query has no rows either, so
  // testing emptiness first reports a dead request as "no scenes match". That
  // is the worst possible answer here -- an operator reading the Observer to
  // find out whether the pipeline ran is told, authoritatively, that this farm
  // has no scenes. It happened in prod: the lock-exhaustion 500 (#378) showed
  // an empty table for weeks' worth of scenes that were all present.
  // Deliberately NOT <EmptyState>: that component is the canonical "nothing
  // here yet" surface (muted text), and its text-ap-muted would collide with a
  // critical colour passed via className.
  if (isError) {
    return (
      <p className="p-12 text-center text-sm text-ap-crit">{t("observer.scenes.loadFailed")}</p>
    );
  }
  if (scenes.length === 0) return <EmptyState message={t("observer.scenes.empty")} />;

  return (
    <Table>
      <Thead>
        <Tr>
          <Th />
          <Th>{t("observer.scenes.when")}</Th>
          <Th>{t("observer.scenes.block")}</Th>
          <Th>{t("observer.scenes.sceneId")}</Th>
          <Th>{t("observer.scenes.status")}</Th>
          <Th className="text-end" title={t("observer.tooltip.cloudPct")}>
            {t("observer.scenes.cloud")}
          </Th>
          <Th className="text-end" title={t("observer.tooltip.validPct")}>
            {t("observer.scenes.valid")}
          </Th>
          <Th className="text-end" title={t("observer.tooltip.indices")}>
            {t("observer.scenes.indices")}
          </Th>
          <Th className="text-end">{t("observer.scenes.cells")}</Th>
          <Th className="text-end">{t("observer.scenes.duration")}</Th>
          <Th>{t("observer.scenes.error")}</Th>
          <Th />
        </Tr>
      </Thead>
      <Tbody>
        {scenes.map((s) => {
          const isOpen = expanded === s.job_id;
          return (
            <Fragment key={s.job_id}>
              <Tr className={clsx(isOpen && "bg-ap-primary-soft/20")}>
                <Td>
                  <button
                    type="button"
                    className="text-ap-muted hover:text-ap-ink"
                    aria-expanded={isOpen}
                    aria-label={t("observer.scenes.expand")}
                    onClick={() => onToggleExpand(isOpen ? null : s.job_id)}
                  >
                    {isOpen ? "▾" : "▸"}
                  </button>
                </Td>
                <Td className="whitespace-nowrap tabular-nums">
                  {new Date(s.scene_datetime).toLocaleString(i18n.language, {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </Td>
                <Td>
                  <div className="flex items-center gap-1.5">
                    <span>{s.block_name ?? s.block_code ?? "—"}</span>
                    {/* Otherwise a whole-farm row is indistinguishable from a
                        block row that happens to share the farm's name. */}
                    {s.scope === "farm" ? (
                      <Pill kind="info">{t("observer.scenes.wholeFarm")}</Pill>
                    ) : null}
                  </div>
                </Td>
                <Td className="max-w-[16rem] truncate font-mono text-xs" title={s.scene_id}>
                  {s.scene_id}
                </Td>
                <Td>
                  <Pill kind={STATUS_KIND[s.status]}>
                    {t(`observer.status.${s.status}`, { defaultValue: s.status })}
                  </Pill>
                </Td>
                <Td className="text-end tabular-nums">{fmtPct(s.cloud_cover_pct)}</Td>
                <Td className="text-end tabular-nums">{fmtPct(s.valid_pixel_pct)}</Td>
                <Td className="text-end tabular-nums">
                  {s.indices_written > 0 ? (
                    s.indices_written
                  ) : (
                    <span className="text-ap-crit">0</span>
                  )}
                </Td>
                <Td className="text-end tabular-nums">
                  {/*
                   * A block with no grid governing this scene's time expects
                   * no cells. Rendering "0/0" invites reading it as a
                   * failure, so ungridded says so in words.
                   */}
                  {s.gridded ? (
                    `${s.cells_written} / ${s.cells_expected}`
                  ) : (
                    /*
                     * "not gridded" is correct but reads as a fault. Grid
                     * configs are per (block, PRODUCT), and only s2_l2a has
                     * any — thermal has never had a grid or a cell aggregate
                     * anywhere on the platform. Say which it is on hover
                     * rather than leaving the reader to guess at a defect.
                     */
                    <span
                      className="cursor-help text-ap-muted underline decoration-dotted"
                      title={t("observer.tooltip.ungridded")}
                    >
                      {t("observer.scenes.ungridded")}
                    </span>
                  )}
                </Td>
                <Td className="text-end tabular-nums">{fmtDuration(s.duration_s)}</Td>
                <Td className="max-w-[12rem] truncate text-xs" title={s.error_message ?? ""}>
                  {s.error_code ?? ""}
                </Td>
                <Td>
                  <Link
                    className="text-xs text-ap-accent underline"
                    to={`/platform/observer/scenes/${s.job_id}?tenant=${tenantId}`}
                  >
                    {t("observer.scenes.open")}
                  </Link>
                </Td>
              </Tr>
              {isOpen ? (
                <Tr>
                  <Td colSpan={12} className="bg-ap-bg/40">
                    <ExpandedIndices tenantId={tenantId} farmId={farmId} scene={s} />
                  </Td>
                </Tr>
              ) : null}
            </Fragment>
          );
        })}
      </Tbody>
    </Table>
  );
}
