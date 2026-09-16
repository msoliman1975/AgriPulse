/**
 * Dry run: pick a block, read the fold per cell.
 *
 * Four columns carry the answer section 8 asks for — the finding set, whether
 * a rule matched or the text composed, and the card text itself. A cell whose
 * set is empty produces no card, and the row says so rather than showing an
 * empty text cell that reads like missing data.
 *
 * The run walks the draft, not the stored version, so an author checks the
 * edit in front of them.
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

const SELECT_CLASS = "w-full rounded-lg border border-ap-line px-2.5 py-1.5 text-sm text-ap-ink";

interface BetaDryRunPanelProps {
  blocks: AsyncState<BetaCandidateBlock[]>;
  blockId: string;
  onBlockChange: (blockId: string) => void;
  onRun: () => void;
  running: boolean;
  result: BetaDryRunResponse | null;
  error?: string | null;
}

export function BetaDryRunPanel({
  blocks,
  blockId,
  onBlockChange,
  onRun,
  running,
  result,
  error,
}: BetaDryRunPanelProps): JSX.Element {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const isAr = i18n.language === "ar";

  // The picker wants the rows, the boundary wants the state. `mapAsyncState`
  // projects one into the other without casting the query result.
  const blockOptions = mapAsyncState(blocks, (rows) => rows);

  return (
    <Card title={t("dryRun.title")} bodyClassName="flex flex-col gap-4">
      <p className="text-sm text-ap-muted">{t("dryRun.subtitle")}</p>

      <AsyncBoundary
        state={blockOptions}
        skeleton="lines"
        skeletonLines={1}
        empty={<EmptyState message={t("dryRun.noBlocks")} />}
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
            <Button onClick={onRun} disabled={!blockId || running}>
              {running ? t("dryRun.running") : t("dryRun.run")}
            </Button>
          </div>
        )}
      </AsyncBoundary>

      {error ? <StatusBanner kind="crit">{error}</StatusBanner> : null}

      {result === null ? (
        <EmptyState message={t("dryRun.empty")} />
      ) : (
        <>
          <p className="text-sm text-ap-ink">
            {t("dryRun.summary", {
              cards: result.cells_with_card,
              total: result.cells_evaluated,
            })}
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
                    {cell.finding_set.length === 0 ? (
                      <span className="text-ap-muted">{t("dryRun.noCard")}</span>
                    ) : (
                      <span dir="ltr" className="flex flex-wrap gap-1 font-mono text-xs">
                        {cell.finding_set.map((c) => (
                          <span key={c} className="rounded bg-ap-line/60 px-1.5 py-0.5 text-ap-ink">
                            {c}
                          </span>
                        ))}
                      </span>
                    )}
                  </Td>
                  <Td className="px-2 py-2">
                    {cell.finding_set.length === 0 ? (
                      "—"
                    ) : cell.matched_rule_codes ? (
                      <Pill kind="ok">{t("dryRun.ruleMatched")}</Pill>
                    ) : (
                      <Pill kind="neutral">{t("dryRun.ruleComposed")}</Pill>
                    )}
                  </Td>
                  <Td className="px-2 py-2">
                    {cell.severity ? t(`severity.${cell.severity}`) : "—"}
                  </Td>
                  <Td className="px-2 py-2">{t(`status.${cell.status}`)}</Td>
                  <Td className="px-2 py-2">
                    {cell.action_type ? t(`actionType.${cell.action_type}`) : "—"}
                  </Td>
                  <Td dir={isAr ? "rtl" : "ltr"} className="px-2 py-2 text-ap-ink">
                    {(isAr ? cell.text_ar : cell.text_en) || "—"}
                    {cell.error ? (
                      <span className="block text-meta text-ap-crit">{cell.error}</span>
                    ) : null}
                    {cell.unresolved.length > 0 ? (
                      <span className="block text-meta text-ap-warn">
                        {t("combinations.preview.unresolved", {
                          codes: cell.unresolved.join(", "),
                        })}
                      </span>
                    ) : null}
                  </Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </>
      )}
    </Card>
  );
}
