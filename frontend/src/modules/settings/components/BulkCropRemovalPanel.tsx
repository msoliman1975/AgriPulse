import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useMutation } from "@tanstack/react-query";

import {
  previewBulkCropRemoval,
  removeBulkCropAssignments,
  type BulkCropRemoval,
  type BulkCropRemovalPayload,
} from "@/api/bulkCropAssignment";
import { isApiError } from "@/api/errors";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";

interface Props {
  farmId: string;
  payload: BulkCropRemovalPayload;
  /** Refetch whatever list the caller is showing. */
  onRemoved: (result: BulkCropRemoval) => void;
  onCancel?: () => void;
}

/** Typed exactly to arm the button. A destructive action with no undo should
 *  cost more than one click, and a checkbox is one click. */
const CONFIRM_WORD = "REMOVE";

/**
 * Dry run → confirm → permanently delete crop assignments.
 *
 * Shared by the Bulk Updates wizard and the Farm Console block drawer so the
 * dangerous path is written once. The preview is not a courtesy here: these
 * rows are hard-deleted, their crop-field values and growth-stage history go
 * with them, and nothing can bring any of it back.
 */
export function BulkCropRemovalPanel({ farmId, payload, onRemoved, onCancel }: Props): ReactNode {
  const { t } = useTranslation("bulkUpdates");
  const [preview, setPreview] = useState<BulkCropRemoval | null>(null);
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);

  const previewMutation = useMutation({
    mutationFn: () => previewBulkCropRemoval(farmId, payload),
    onSuccess: (data) => {
      setPreview(data);
      setError(null);
    },
    onError: (err: unknown) =>
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : t("errors.preview")),
  });

  const removeMutation = useMutation({
    mutationFn: () => removeBulkCropAssignments(farmId, payload),
    onSuccess: (data) => {
      setError(null);
      onRemoved(data);
    },
    onError: (err: unknown) =>
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : t("errors.remove")),
  });

  if (preview === null) {
    return (
      <Card title={t("remove.title")}>
        <StatusBanner kind="warn">{t("remove.warning")}</StatusBanner>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button
            variant="secondary"
            onClick={() => previewMutation.mutate()}
            disabled={previewMutation.isPending}
          >
            {previewMutation.isPending ? t("remove.checking") : t("remove.check")}
          </Button>
          {onCancel ? (
            <Button variant="ghost" onClick={onCancel}>
              {t("remove.cancel")}
            </Button>
          ) : null}
        </div>
        {error ? (
          <div className="mt-3">
            <StatusBanner kind="crit">{error}</StatusBanner>
          </div>
        ) : null}
      </Card>
    );
  }

  const nothingToDo = preview.assignment_count === 0;
  const armed = confirm.trim().toUpperCase() === CONFIRM_WORD;

  return (
    <div className="flex flex-col gap-3">
      <StatusBanner kind={nothingToDo ? "info" : "crit"}>
        {nothingToDo
          ? t("remove.nothing")
          : t("remove.summary", {
              assignments: preview.assignment_count,
              blocks: preview.block_count,
            })}
      </StatusBanner>

      {!nothingToDo ? (
        <Card title={t("remove.alsoGoes")}>
          <ul className="flex flex-col gap-1 text-sm text-ap-ink">
            <li>{t("remove.cascade.attributes", { count: preview.attribute_value_count })}</li>
            <li>{t("remove.cascade.history", { count: preview.attribute_value_log_count })}</li>
            <li>{t("remove.cascade.stages", { count: preview.growth_stage_log_count })}</li>
            <li>
              {t("remove.cascade.recommendations", {
                count: preview.recommendation_unlink_count,
              })}
            </li>
          </ul>
          {preview.reopened_count > 0 ? (
            <p className="mt-3 text-sm text-ap-muted">
              {t("remove.reopen", { count: preview.reopened_count })}
            </p>
          ) : null}
        </Card>
      ) : null}

      <Table>
        <Thead>
          <Tr>
            <Th>{t("outcome.col.block")}</Th>
            <Th>{t("remove.col.assignments")}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {preview.items.map((item) => (
            <Tr key={item.block_id} data-testid={`removal-row-${item.code}`}>
              <Td>
                <span className="font-medium text-ap-ink">{item.code}</span>
                {item.name ? <div className="text-xs text-ap-muted">{item.name}</div> : null}
              </Td>
              <Td>
                {item.assignments.length === 0 ? (
                  <span className="text-ap-muted">{item.detail ?? t("remove.none")}</span>
                ) : (
                  <ul className="flex flex-col gap-1">
                    {item.assignments.map((a) => (
                      <li key={a.block_crop_id} className="flex flex-wrap items-center gap-1.5">
                        <span className="text-ap-ink">{a.crop_path}</span>
                        <span className="text-ap-muted">{a.season_label}</span>
                        <span className="text-xs text-ap-muted">
                          {a.effective_from} → {a.effective_to ?? "…"}
                        </span>
                        {a.is_current ? <Pill kind="warn">{t("remove.current")}</Pill> : null}
                      </li>
                    ))}
                  </ul>
                )}
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>

      {error ? <StatusBanner kind="crit">{error}</StatusBanner> : null}

      <Card>
        {nothingToDo ? (
          <Button variant="secondary" onClick={() => onCancel?.()}>
            {t("remove.close")}
          </Button>
        ) : (
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1 text-sm text-ap-ink" htmlFor="removal-confirm">
              {t("remove.confirmLabel", { word: CONFIRM_WORD })}
              <input
                id="removal-confirm"
                className="max-w-[220px] rounded-md border border-ap-line bg-ap-panel px-2.5 py-1.5 text-sm"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="off"
              />
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="danger"
                disabled={!armed || removeMutation.isPending}
                onClick={() => removeMutation.mutate()}
              >
                {removeMutation.isPending
                  ? t("remove.removing")
                  : t("remove.confirm", { count: preview.assignment_count })}
              </Button>
              <Button
                variant="ghost"
                onClick={() => {
                  setPreview(null);
                  setConfirm("");
                }}
              >
                {t("remove.back")}
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
