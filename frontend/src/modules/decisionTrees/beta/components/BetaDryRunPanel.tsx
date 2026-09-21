/**
 * Dry run: pick a block, read the fold per cell.
 *
 * Four columns carry the answer section 8 asks for — the finding set, whether
 * a rule matched or the text composed, and the card text itself. A cell whose
 * set is empty produces no card, and the row says so rather than showing an
 * empty text cell that reads like missing data.
 *
 * Three answers that are not a failure, and each says which one it is:
 *
 *   * a platform account has no blocks to point the run at, because farms and
 *     blocks are a tenant's;
 *   * an unsaved edit cannot be run, because the route walks the stored
 *     version and would quietly answer about the previous body;
 *   * a block with no grid returns no cells, which is a fact about the block.
 *
 * Every row carries a "why" button, the healthy and the errored ones included.
 * "Why did this cell find nothing" and "where did this walk fall over" are the
 * same question as "why this card", and the walk answers all three.
 */

import { useTranslation } from "react-i18next";

import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Field } from "@/components/Field";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { mapAsyncState, type AsyncState } from "@/components/asyncState";
import { localizedField } from "@/lib/localizedField";
import type { BetaCandidateBlock, BetaDryRunResponse } from "@/api/decisionTreesBeta";

import { useFindingStatusLabel } from "../lib/useStatusLabel";

const SELECT_CLASS = "w-full rounded-lg border border-ap-line px-2.5 py-1.5 text-sm text-ap-ink";

interface BetaDryRunPanelProps {
  blocks: AsyncState<BetaCandidateBlock[]>;
  blockId: string;
  onBlockChange: (blockId: string) => void;
  onRun: () => void;
  running: boolean;
  result: BetaDryRunResponse | null;
  /** True for a caller with no tenant. The picker is not shown at all. */
  platformScope?: boolean;
  /** True while the editor holds unsaved changes. The run is held back. */
  dirty?: boolean;
  error?: string | null;
  /** Open the walk explainer on one row. Left out hides the column. */
  onShowDetails?: (cell: BetaDryRunResponse["cells"][number]) => void;
}

export function BetaDryRunPanel({
  blocks,
  blockId,
  onBlockChange,
  onRun,
  running,
  result,
  platformScope = false,
  dirty = false,
  error,
  onShowDetails,
}: BetaDryRunPanelProps): JSX.Element {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const statusLabel = useFindingStatusLabel();
  const isAr = i18n.language === "ar";

  // The picker wants the rows, the boundary wants the state. `mapAsyncState`
  // projects one into the other without casting the query result.
  const blockOptions = mapAsyncState(blocks, (rows) => rows);

  return (
    <Card title={t("dryRun.title")} bodyClassName="flex flex-col gap-4">
      <p className="text-sm text-ap-muted">{t("dryRun.subtitle")}</p>

      {platformScope ? <StatusBanner kind="info">{t("dryRun.platformScope")}</StatusBanner> : null}
      {!platformScope && dirty ? (
        <StatusBanner kind="warn">{t("dryRun.saveFirst")}</StatusBanner>
      ) : null}

      <AsyncBoundary
        state={platformScope ? { status: "success", data: [] } : blockOptions}
        skeleton="lines"
        skeletonLines={1}
        errorMessage={t("dryRun.blocksFailed")}
        empty={
          <EmptyState message={t(platformScope ? "dryRun.platformScope" : "dryRun.noBlocks")} />
        }
      >
        {(rows) => (
          <div className="flex flex-wrap items-end gap-3">
            <Field label={t("dryRun.block")} className="min-w-64">
              {(props) => (
                <select
                  {...props}
                  value={blockId}
                  onChange={(e) => onBlockChange(e.target.value)}
                  className={SELECT_CLASS}
                >
                  <option value="">{t("dryRun.pickBlock")}</option>
                  {rows.map((b) => (
                    <option key={b.block_id} value={b.block_id}>
                      {localizedField(i18n.language, b.label, b.label_ar)}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            <Button onClick={onRun} disabled={!blockId || running || dirty}>
              {running ? t("dryRun.running") : t("dryRun.run")}
            </Button>
          </div>
        )}
      </AsyncBoundary>

      {error ? <StatusBanner kind="crit">{error}</StatusBanner> : null}

      {result === null ? (
        <EmptyState message={t("dryRun.empty")} />
      ) : result.cells.length === 0 ? (
        // Not an error and not an empty state: the block answered, and the
        // answer is that it has no cells to fold.
        <StatusBanner kind="info">{t("dryRun.noCells")}</StatusBanner>
      ) : (
        <>
          <p className="text-sm text-ap-ink">
            {t("dryRun.summary", {
              cards: result.cells_carded,
              total: result.cells_evaluated,
            })}
            {result.cells_errored > 0 ? (
              // An errored cell is not a healthy one. The summary counted
              // cards and total only, so a walk that fell over read as a cell
              // with nothing to say.
              <span className="ms-2 text-ap-crit">
                {t("dryRun.errored", { count: result.cells_errored })}
              </span>
            ) : null}
          </p>
          <Table>
            <caption className="sr-only">{t("dryRun.title")}</caption>
            <Thead>
              <Tr className="border-b border-ap-line text-meta uppercase text-ap-muted">
                <Th className="px-2 py-2 text-start">{t("dryRun.columns.cell")}</Th>
                <Th className="px-2 py-2 text-start">{t("dryRun.columns.set")}</Th>
                <Th className="px-2 py-2 text-start">{t("dryRun.columns.rule")}</Th>
                <Th className="px-2 py-2 text-start">{t("dryRun.columns.severity")}</Th>
                <Th className="px-2 py-2 text-start">{t("dryRun.columns.status")}</Th>
                <Th className="px-2 py-2 text-start">{t("dryRun.columns.actionType")}</Th>
                <Th className="px-2 py-2 text-start">{t("dryRun.columns.text")}</Th>
                {onShowDetails ? (
                  <Th className="px-2 py-2 text-start">{t("dryRun.columns.details")}</Th>
                ) : null}
              </Tr>
            </Thead>
            <Tbody>
              {result.cells.map((cell) => (
                <Tr key={cell.cell_id} className="align-top">
                  <Td className="px-2 py-2 whitespace-nowrap">
                    {cell.cell_row !== null && cell.cell_col !== null
                      ? t("dryRun.cellLabel", { row: cell.cell_row, col: cell.cell_col })
                      : cell.cell_id}
                  </Td>
                  <Td className="px-2 py-2">
                    {cell.identity.length === 0 ? (
                      <span className="text-ap-muted">{t("dryRun.noCard")}</span>
                    ) : (
                      <span dir="ltr" className="flex flex-wrap gap-1 font-mono text-xs">
                        {cell.identity.map((c) => (
                          <span key={c} className="rounded bg-ap-line/60 px-1.5 py-0.5 text-ap-ink">
                            {c}
                          </span>
                        ))}
                      </span>
                    )}
                  </Td>
                  <Td className="px-2 py-2">
                    {cell.identity.length === 0 ? (
                      "—"
                    ) : cell.composed ? (
                      <Pill kind="neutral">{t("dryRun.ruleComposed")}</Pill>
                    ) : (
                      // The rule's own code, when the compiler kept one. A
                      // rule with no code still matched, and saying so beats
                      // showing nothing.
                      <Pill kind="ok">{cell.rule_code ?? t("dryRun.ruleMatched")}</Pill>
                    )}
                  </Td>
                  <Td className="px-2 py-2">
                    {cell.severity ? t(`severity.${cell.severity}`) : "—"}
                  </Td>
                  <Td className="px-2 py-2">{cell.status ? statusLabel(cell.status) : "—"}</Td>
                  <Td className="px-2 py-2">
                    {cell.action_type ? t(`actionType.${cell.action_type}`) : "—"}
                  </Td>
                  <Td dir={isAr ? "rtl" : "ltr"} className="px-2 py-2 text-ap-ink">
                    {(isAr ? cell.text_ar : cell.text_en) || "—"}
                    {cell.error ? (
                      <span className="block text-meta text-ap-crit">{cell.error}</span>
                    ) : null}
                    {cell.error === null && cell.stopped_at !== null && cell.identity.length > 0 ? (
                      <span className="block text-meta text-ap-muted">
                        {t("dryRun.stoppedAt", { node: cell.stopped_at })}
                      </span>
                    ) : null}
                  </Td>
                  {onShowDetails ? (
                    <Td className="px-2 py-2 whitespace-nowrap">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => onShowDetails(cell)}
                        aria-label={t("explainer.openFor", {
                          cell:
                            cell.cell_row !== null && cell.cell_col !== null
                              ? t("dryRun.cellLabel", { row: cell.cell_row, col: cell.cell_col })
                              : cell.cell_id,
                        })}
                      >
                        {t("explainer.open")}
                      </Button>
                    </Td>
                  ) : null}
                </Tr>
              ))}
            </Tbody>
          </Table>
        </>
      )}
    </Card>
  );
}
