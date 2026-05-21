import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActivityType } from "@/api/plans";
import { Modal } from "@/components/Modal";
import { useBulkCreateActivities } from "@/queries/board";

const ACTIVITY_TYPES: ActivityType[] = [
  "irrigation",
  "fertilizing",
  "spraying",
  "observation",
  "planting",
  "harvesting",
  "pruning",
  "soil_prep",
];

export interface SelectedCell {
  /** block id */
  blockId: string;
  /** ISO date the cell represents — the specific day for the activity. */
  weekStart: string;
  /** Human-readable block code, for the summary list */
  blockCode: string;
}

interface BulkAddDialogProps {
  farmId: string;
  cells: SelectedCell[];
  onClose: () => void;
  /** Called after a successful save. Caller clears selection. */
  onSaved: () => void;
}

/**
 * Bulk-add: same activity to N cells. Each (block, week) cell becomes
 * one activity row on Monday of that week. The server's `skip_existing`
 * defends against re-runs creating duplicates.
 */
export function BulkAddDialog({
  farmId,
  cells,
  onClose,
  onSaved,
}: BulkAddDialogProps): ReactNode {
  const { t } = useTranslation("board");
  const [activityType, setActivityType] = useState<ActivityType>("irrigation");
  const [notes, setNotes] = useState("");
  const [skipExisting, setSkipExisting] = useState(true);

  const mutation = useBulkCreateActivities(farmId);

  async function submit() {
    // Each selected cell already encodes the exact day — the dialog
    // no longer needs a dayOffset since the grid is day-granular.
    const result = await mutation.mutateAsync({
      cells: cells.map((c) => ({
        block_id: c.blockId,
        scheduled_date: c.weekStart,
      })),
      activity_type: activityType,
      notes: notes.trim() || null,
      skip_existing: skipExisting,
    });
    onSaved();
    onClose();
    // Hand the skip-summary to a toast — for V1 we just close; PR-7
    // can wire a toast bus.
    if (result.skipped.length > 0) {
      // eslint-disable-next-line no-console
      console.info(
        `[board] bulk-add skipped ${result.skipped.length}/${cells.length} cells`,
      );
    }
  }

  return (
    <Modal open onClose={onClose} labelledBy="bulk-title" className="max-w-md">
      <h2 id="bulk-title" className="text-base font-semibold text-ap-ink">
        {t("bulkAdd.title", { count: cells.length })}
      </h2>
      <p className="mt-1 text-xs text-ap-muted">
        {cells.slice(0, 6).map((c) => c.blockCode).join(", ")}
        {cells.length > 6 ? ` +${cells.length - 6}` : ""}
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
        className="mt-4 flex flex-col gap-4"
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ap-muted">{t("quickAdd.type")}</span>
          <select
            autoFocus
            className="rounded-md border border-ap-line bg-white px-2 py-1.5"
            value={activityType}
            onChange={(e) => setActivityType(e.target.value as ActivityType)}
          >
            {ACTIVITY_TYPES.map((typ) => (
              <option key={typ} value={typ}>
                {t(`type.${typ}`)}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ap-muted">{t("quickAdd.note")}</span>
          <textarea
            className="min-h-[60px] rounded-md border border-ap-line bg-white px-2 py-1.5"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={500}
          />
        </label>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={skipExisting}
            onChange={(e) => setSkipExisting(e.target.checked)}
          />
          <span>{t("bulkAdd.skipExisting")}</span>
        </label>

        {mutation.isError ? (
          <p className="text-xs text-ap-crit">{t("quickAdd.failed")}</p>
        ) : null}

        <div className="mt-2 flex justify-end gap-2">
          <button
            type="button"
            className="rounded-md px-3 py-1.5 text-sm text-ap-muted"
            onClick={onClose}
            disabled={mutation.isPending}
          >
            {t("quickAdd.cancel")}
          </button>
          <button
            type="submit"
            className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary-700 disabled:opacity-50"
            disabled={mutation.isPending}
          >
            {mutation.isPending
              ? t("quickAdd.saving")
              : t("bulkAdd.create", { count: cells.length })}
          </button>
        </div>
      </form>
    </Modal>
  );
}
