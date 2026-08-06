import clsx from "clsx";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { VerificationRow, Verdict, VerifyMode } from "@/api/observer";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Pill } from "@/components/Pill";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { useVerifyScene } from "@/queries/observer";

/**
 * Single-scene verification: recompute from the stored raster, diff against
 * the stored aggregates, show the result.
 *
 * Synchronous because it is one scene and the operator is already looking at
 * it. Anything wider is a named run — see the Verify runs card.
 *
 * The panel is explicit that nothing was repaired. A drift verdict is a
 * signal; the fix is a re-run from the Backfill Console, which owns provider
 * quota. An Observer that silently corrected an aggregate would destroy the
 * evidence of the defect it just found.
 */

const VERDICT_KIND: Record<Verdict, "ok" | "warn" | "crit" | "neutral"> = {
  match: "ok",
  drift: "crit",
  source_missing: "warn",
  error: "warn",
};

function fmt(v: number | null): string {
  return v === null ? "—" : v.toFixed(4);
}

export function VerifyPanel({ tenantId, jobId }: { tenantId: string; jobId: string }): ReactNode {
  const { t } = useTranslation("admin");
  const [mode, setMode] = useState<VerifyMode>("full");
  const verify = useVerifyScene(tenantId);
  const result: VerificationRow | undefined = verify.data;

  return (
    <Card
      title={t("observer.verify.title")}
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
            onClick={() => verify.mutate({ jobId, mode })}
            disabled={verify.isPending}
          >
            {verify.isPending ? t("observer.verify.running") : t("observer.verify.run")}
          </Button>
        </div>
      }
    >
      <p className="mb-3 text-xs text-ap-muted">
        {mode === "full" ? t("observer.verify.explainFull") : t("observer.verify.explainFast")}
      </p>

      {verify.isError ? (
        <p className="text-sm text-ap-crit">{t("observer.verify.failed")}</p>
      ) : null}

      {result ? (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
            <Pill kind={VERDICT_KIND[result.verdict]}>
              {t(`observer.verify.verdict.${result.verdict}`)}
            </Pill>
            <span className="text-ap-muted">
              {t("observer.verify.tookMs", { ms: result.duration_ms ?? 0 })}
            </span>
            {result.calc_version_stored ? (
              <span className="font-mono text-ap-muted">
                {t("observer.verify.storedBy", { version: result.calc_version_stored })}
              </span>
            ) : null}
          </div>

          <Table className="text-xs">
            <Thead>
              <Tr>
                <Th>{t("observer.scenes.index")}</Th>
                <Th className="text-end">{t("observer.verify.stored")}</Th>
                <Th className="text-end">{t("observer.verify.recomputed")}</Th>
                <Th className="text-end">Δ</Th>
                <Th className="text-end">{t("observer.verify.storedValid")}</Th>
                <Th className="text-end">{t("observer.verify.recomputedValid")}</Th>
                <Th>{t("observer.verify.verdictCol")}</Th>
              </Tr>
            </Thead>
            <Tbody>
              {Object.entries(result.per_index).map(([code, row]) => (
                <Tr key={code}>
                  <Td className="font-medium uppercase">{code}</Td>
                  <Td className="text-end tabular-nums">{fmt(row.stored_mean)}</Td>
                  <Td className="text-end tabular-nums">{fmt(row.recomputed_mean)}</Td>
                  <Td
                    className={clsx(
                      "text-end tabular-nums",
                      row.verdict === "drift" && "font-semibold text-ap-crit",
                    )}
                  >
                    {fmt(row.delta_mean)}
                  </Td>
                  <Td className="text-end tabular-nums">
                    {row.stored_valid?.toLocaleString() ?? "—"}
                  </Td>
                  <Td className="text-end tabular-nums">
                    {row.recomputed_valid?.toLocaleString() ?? "—"}
                  </Td>
                  <Td>
                    <Pill kind={VERDICT_KIND[row.verdict]}>
                      {t(`observer.verify.verdict.${row.verdict}`)}
                    </Pill>
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>

          <p className="mt-3 border-s-2 border-ap-accent ps-3 text-xs text-ap-muted">
            {t("observer.verify.neverRepairs")}
          </p>
        </>
      ) : null}
    </Card>
  );
}
