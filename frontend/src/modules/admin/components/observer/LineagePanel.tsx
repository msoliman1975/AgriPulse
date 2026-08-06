import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { LineageConsumer } from "@/api/observer";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { useIndexLineage } from "@/queries/observer";

/**
 * What this index produced: the alerts and recommendations whose conditions
 * actually read it, plus the cell anomalies for the scene.
 *
 * These are stored edges, not a timestamp proxy — the decision engine records
 * what each condition read in its evaluation snapshot — so each row comes
 * back with the value the tree saw. "Fired on NDMI = 0.2871" is a finding;
 * "fired the same afternoon" is not, and the ribbon's consumer count is
 * labelled as the latter for exactly that reason.
 */

function ConsumerRows({
  rows,
  kind,
}: {
  rows: LineageConsumer[];
  kind: "recommendation" | "alert";
}): ReactNode {
  const { t, i18n } = useTranslation("admin");
  return (
    <>
      {rows.map((row) => (
        <Tr key={row.id}>
          <Td>
            <Pill kind={kind === "alert" ? "warn" : "info"}>
              {t(`observer.lineage.kind.${kind}`)}
            </Pill>
          </Td>
          <Td>{row.tree_code ?? row.rule_code ?? "—"}</Td>
          <Td>{row.action_type ?? row.severity ?? "—"}</Td>
          <Td className="font-mono text-[0.6875rem]">{row.snapshot_key}</Td>
          <Td className="text-end font-semibold tabular-nums">{row.observed_value ?? "—"}</Td>
          <Td>{row.cell_id ? t("observer.lineage.perCell") : t("observer.lineage.block")}</Td>
          <Td className="tabular-nums">{new Date(row.created_at).toLocaleString(i18n.language)}</Td>
        </Tr>
      ))}
    </>
  );
}

export function LineagePanel({
  tenantId,
  blockId,
  indexCode,
  windowFrom,
  windowTo,
  productId,
  sceneTime,
}: {
  tenantId: string;
  blockId: string;
  indexCode: string;
  windowFrom: string;
  windowTo: string;
  productId?: string | null;
  sceneTime?: string | null;
}): ReactNode {
  const { t } = useTranslation("admin");
  const lineage = useIndexLineage(tenantId, {
    blockId,
    indexCode,
    from: windowFrom,
    to: windowTo,
    productId,
    sceneTime,
  });

  if (lineage.isPending) return <Skeleton className="h-40 w-full" />;
  if (!lineage.data) return null;

  const l = lineage.data;
  const consumers = l.recommendations.length + l.alerts.length;

  return (
    <Card
      title={t("observer.lineage.title", { index: indexCode.toUpperCase() })}
      actions={l.exact ? <Pill kind="ok">{t("observer.lineage.exact")}</Pill> : null}
    >
      <p className="mb-3 text-xs text-ap-muted">{t("observer.lineage.explain")}</p>

      {consumers === 0 ? (
        <EmptyState message={t("observer.lineage.none")} />
      ) : (
        <Table className="text-xs">
          <Thead>
            <Tr>
              <Th>{t("observer.lineage.what")}</Th>
              <Th>{t("observer.lineage.source")}</Th>
              <Th>{t("observer.lineage.outcome")}</Th>
              <Th>{t("observer.lineage.readKey")}</Th>
              <Th className="text-end">{t("observer.lineage.readValue")}</Th>
              <Th>{t("observer.lineage.scope")}</Th>
              <Th>{t("observer.lineage.when")}</Th>
            </Tr>
          </Thead>
          <Tbody>
            <ConsumerRows rows={l.alerts} kind="alert" />
            <ConsumerRows rows={l.recommendations} kind="recommendation" />
          </Tbody>
        </Table>
      )}

      {l.cell_anomalies.length > 0 ? (
        <div className="mt-4">
          <p className="mb-1 text-[0.6875rem] font-semibold uppercase tracking-wide text-ap-muted">
            {t("observer.lineage.anomalies", { n: l.cell_anomalies.length })}
          </p>
          <p className="mb-2 text-xs text-ap-muted">
            {/*
             * The threshold's tier is transmitted because the tenant-level
             * setting is not re-resolved here — `module_default` must not be
             * mistaken for the number the nightly sweep actually used.
             */}
            {t("observer.lineage.threshold", {
              k: l.anomaly_threshold,
              source: l.anomaly_threshold_source,
            })}
          </p>
          <div className="flex flex-wrap gap-2">
            {l.cell_anomalies.map((a) => (
              <span
                key={a.cell_id}
                className="rounded border border-ap-crit/40 bg-ap-crit-soft/40 px-2 py-1 text-xs"
              >
                R{a.row_idx}C{a.col_idx} · z −{a.z.toFixed(2)}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  );
}
