import {
  endOfMonth,
  format,
  isWithinInterval,
  parseISO,
  startOfMonth,
} from "date-fns";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActivityType } from "@/api/plans";
import type { Resource } from "@/api/resources";
import { Modal } from "@/components/Modal";
import { useCreateFlatActivity, useAttachResource } from "@/queries/board";
import { useResources } from "@/queries/resources";

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

interface QuickAddDialogProps {
  farmId: string;
  blockId: string;
  /** ISO date the cell represents: the day itself (day-unit columns)
   *  or the 1st of the month (month-unit columns, i.e. season view). */
  columnStart: string;
  /** Cell unit. "day" means the scheduled date IS columnStart — the
   *  dialog shows a read-only label with no date editor. "month"
   *  shows a date input bounded to that calendar month so the author
   *  can pick which day in the month. */
  columnUnit: "day" | "month";
  onClose: () => void;
}

/**
 * Quick-add popover for one (block × column) cell. Per the design spec:
 *   - type (required, defaults to "irrigation")
 *   - day picker — 7 dots in week mode, free date input bounded to the
 *     month in month/season mode
 *   - assigned resources picker (multi-select from master file)
 *   - optional note
 * Submit creates the activity then attaches resources in sequence.
 */
export function QuickAddDialog({
  farmId,
  blockId,
  columnStart,
  columnUnit,
  onClose,
}: QuickAddDialogProps): ReactNode {
  const { t } = useTranslation("board");
  const colStartDate = parseISO(columnStart);

  // Default scheduled date.
  //  - "day": the clicked day itself. No editor.
  //  - "month": today-if-in-month, else first-of-month. User can pick.
  const initialScheduledIso = useMemo(() => {
    if (columnUnit === "day") return columnStart;
    const monthStart = startOfMonth(colStartDate);
    const monthEnd = endOfMonth(colStartDate);
    const today = new Date();
    if (isWithinInterval(today, { start: monthStart, end: monthEnd })) {
      return format(today, "yyyy-MM-dd");
    }
    return columnStart;
  }, [columnUnit, columnStart, colStartDate]);

  const [scheduledIso, setScheduledIso] = useState(initialScheduledIso);
  const [activityType, setActivityType] = useState<ActivityType>("irrigation");
  const [selectedResourceIds, setSelectedResourceIds] = useState<Set<string>>(
    new Set(),
  );
  const [notes, setNotes] = useState("");

  // Month-mode date bounds: lock to this column's month so the user
  // can't accidentally schedule into the next column.
  const monthInputMin =
    columnUnit === "month"
      ? format(startOfMonth(colStartDate), "yyyy-MM-dd")
      : undefined;
  const monthInputMax =
    columnUnit === "month"
      ? format(endOfMonth(colStartDate), "yyyy-MM-dd")
      : undefined;

  const resourcesQ = useResources(farmId, { include_archived: false });
  const workers = useMemo(
    () => (resourcesQ.data ?? []).filter((r) => r.kind === "worker"),
    [resourcesQ.data],
  );
  const equipment = useMemo(
    () => (resourcesQ.data ?? []).filter((r) => r.kind === "equipment"),
    [resourcesQ.data],
  );

  const create = useCreateFlatActivity(farmId);
  const attach = useAttachResource(farmId);

  const scheduledDate = columnUnit === "day" ? columnStart : scheduledIso;

  async function submit() {
    const activity = await create.mutateAsync({
      block_id: blockId,
      activity_type: activityType,
      scheduled_date: scheduledDate,
      notes: notes.trim() || null,
    });
    // Attach resources in parallel; ignore individual failures so a
    // partial save still produces a usable activity.
    await Promise.allSettled(
      Array.from(selectedResourceIds).map((rid) =>
        attach.mutateAsync({ activityId: activity.id, resourceId: rid }),
      ),
    );
    onClose();
  }

  const isSubmitting = create.isPending || attach.isPending;

  return (
    <Modal open onClose={onClose} labelledBy="quickadd-title" className="max-w-md">
      <h2 id="quickadd-title" className="text-base font-semibold text-ap-ink">
        {t("quickAdd.title")}
      </h2>
      <p className="mt-1 text-xs text-ap-muted">
        {t("quickAdd.scope", {
          date: format(parseISO(scheduledDate), "EEE, MMM d"),
        })}
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

        {columnUnit === "month" ? (
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-ap-muted">{t("quickAdd.date")}</span>
            <input
              type="date"
              className="rounded-md border border-ap-line bg-white px-2 py-1.5"
              value={scheduledIso}
              min={monthInputMin}
              max={monthInputMax}
              onChange={(e) => setScheduledIso(e.target.value)}
            />
          </label>
        ) : null}

        <div className="flex flex-col gap-1 text-sm">
          <span className="text-ap-muted">{t("quickAdd.assigned")}</span>
          {resourcesQ.isLoading ? (
            <p className="text-xs text-ap-muted">…</p>
          ) : workers.length + equipment.length === 0 ? (
            <p className="text-xs text-ap-muted">
              {t("quickAdd.noResources")}
            </p>
          ) : (
            <div className="flex max-h-40 flex-col gap-1 overflow-y-auto rounded border border-ap-line p-2">
              <ResourceGroup
                label={t("quickAdd.workers")}
                items={workers}
                selected={selectedResourceIds}
                onToggle={(id) =>
                  setSelectedResourceIds((prev) => {
                    const next = new Set(prev);
                    if (next.has(id)) next.delete(id);
                    else next.add(id);
                    return next;
                  })
                }
              />
              <ResourceGroup
                label={t("quickAdd.equipment")}
                items={equipment}
                selected={selectedResourceIds}
                onToggle={(id) =>
                  setSelectedResourceIds((prev) => {
                    const next = new Set(prev);
                    if (next.has(id)) next.delete(id);
                    else next.add(id);
                    return next;
                  })
                }
              />
            </div>
          )}
        </div>

        <label className="flex flex-col gap-1 text-sm">
          <span className="text-ap-muted">{t("quickAdd.note")}</span>
          <textarea
            className="min-h-[60px] rounded-md border border-ap-line bg-white px-2 py-1.5"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            maxLength={500}
          />
        </label>

        {create.isError ? (
          <p className="text-xs text-ap-crit">{t("quickAdd.failed")}</p>
        ) : null}

        <div className="mt-2 flex justify-end gap-2">
          <button
            type="button"
            className="rounded-md px-3 py-1.5 text-sm text-ap-muted"
            onClick={onClose}
            disabled={isSubmitting}
          >
            {t("quickAdd.cancel")}
          </button>
          <button
            type="submit"
            className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary-700 disabled:opacity-50"
            disabled={isSubmitting}
          >
            {isSubmitting ? t("quickAdd.saving") : t("quickAdd.save")}
          </button>
        </div>
      </form>
    </Modal>
  );
}

interface ResourceGroupProps {
  label: string;
  items: Resource[];
  selected: Set<string>;
  onToggle: (id: string) => void;
}

function ResourceGroup({
  label,
  items,
  selected,
  onToggle,
}: ResourceGroupProps): ReactNode {
  if (items.length === 0) return null;
  return (
    <div>
      <div className="px-1 text-[11px] uppercase tracking-wider text-ap-muted">
        {label}
      </div>
      <ul className="flex flex-col">
        {items.map((r) => (
          <li key={r.id}>
            <label className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 hover:bg-ap-bg/50">
              <input
                type="checkbox"
                checked={selected.has(r.id)}
                onChange={() => onToggle(r.id)}
              />
              <span className="text-sm">
                {r.kind === "worker" ? "👤" : "🔧"} {r.name}
                {r.role ? (
                  <span className="ms-1 text-xs text-ap-muted">({r.role})</span>
                ) : null}
                {r.equipment_type ? (
                  <span className="ms-1 text-xs text-ap-muted">
                    ({r.equipment_type})
                  </span>
                ) : null}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
