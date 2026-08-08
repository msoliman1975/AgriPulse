import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  BulkApplyOutcome,
  BulkCropApplyItem,
  BulkCropPreviewItem,
  BulkPreviewOutcome,
} from "@/api/bulkCropAssignment";
import { Pill, type PillKind } from "@/components/Pill";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";

type AnyItem = BulkCropPreviewItem | BulkCropApplyItem;

interface Props {
  items: AnyItem[];
}

const OUTCOME_KIND: Record<BulkPreviewOutcome | BulkApplyOutcome, PillKind> = {
  assign: "ok",
  replace: "warn",
  skip: "neutral",
  assigned: "ok",
  replaced: "warn",
  skipped: "neutral",
  failed: "crit",
};

/**
 * The before → after table, shared by the dry run and the result.
 *
 * One component for both on purpose: the preview's job is to look like the
 * result, and two components rendering "the same" rows is how a dry run comes
 * to show a column the result quietly drops. The outcome vocabulary is the
 * only difference — future tense in the preview, past tense after the write.
 */
export function BulkCropOutcomeTable({ items }: Props): ReactNode {
  const { t } = useTranslation("bulkUpdates");

  return (
    <Table>
      <Thead>
        <Tr>
          <Th>{t("outcome.col.block")}</Th>
          <Th>{t("outcome.col.now")}</Th>
          <Th aria-hidden className="w-6" />
          <Th>{t("outcome.col.after")}</Th>
          <Th>{t("outcome.col.outcome")}</Th>
        </Tr>
      </Thead>
      <Tbody>
        {items.map((item) => (
          <Tr key={item.block_id} data-testid={`outcome-row-${item.code}`}>
            <Td>
              <span className="font-medium text-ap-ink">{item.code}</span>
              {item.name ? <div className="text-xs text-ap-muted">{item.name}</div> : null}
            </Td>
            <Td className="text-ap-muted">
              {item.before ? (
                <>
                  {item.before.crop_path}
                  <div className="text-xs">{item.before.season_label}</div>
                </>
              ) : (
                t("outcome.unassigned")
              )}
            </Td>
            <Td aria-hidden className="text-center text-ap-muted">
              →
            </Td>
            <Td>
              {item.after ? (
                <>
                  <span className="font-medium text-ap-ink">{item.after.crop_path}</span>
                  <div className="text-xs text-ap-muted">
                    {item.after.season_label}
                    {item.after.planting_date ? ` · ${item.after.planting_date}` : ""}
                    {item.overridden ? (
                      <Pill kind="info" className="ms-1.5">
                        {t("outcome.override")}
                      </Pill>
                    ) : null}
                  </div>
                </>
              ) : (
                <span className="text-ap-muted">{t("outcome.noChange")}</span>
              )}
            </Td>
            <Td>
              <Pill kind={OUTCOME_KIND[item.outcome]}>{t(`outcome.verb.${item.outcome}`)}</Pill>
              {item.detail ? (
                <div className="mt-1 max-w-[38ch] text-xs text-ap-muted">{item.detail}</div>
              ) : null}
            </Td>
          </Tr>
        ))}
      </Tbody>
    </Table>
  );
}
