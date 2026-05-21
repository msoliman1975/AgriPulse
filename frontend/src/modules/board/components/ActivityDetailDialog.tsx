import { format, parseISO } from "date-fns";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActivityType, BoardActivity } from "@/api/plans";
import type { Resource } from "@/api/resources";
import { Modal } from "@/components/Modal";
import { useCapability } from "@/rbac/useCapability";
import { useDeleteActivity, useUpdateActivity } from "@/queries/plans";
import { useAttachResource, useDetachResource } from "@/queries/board";
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

interface ActivityDetailDialogProps {
  farmId: string;
  activity: BoardActivity;
  onClose: () => void;
}

/** Activity detail with view + edit + delete. The view branch shows the
 * read-only summary + state-action buttons (start/complete/skip) that
 * `plan_activity.complete` can drive. Edit + delete are gated on
 * `plan.manage` so field operators don't see the destructive paths. */
export function ActivityDetailDialog({
  farmId: _farmId,
  activity,
  onClose,
}: ActivityDetailDialogProps): ReactNode {
  const { t } = useTranslation("board");
  const canComplete = useCapability("plan_activity.complete");
  const canManage = useCapability("plan.manage");
  const update = useUpdateActivity();
  const del = useDeleteActivity();
  const [mode, setMode] = useState<"view" | "edit" | "confirm-delete">("view");

  function runAction(state: "start" | "complete" | "skip") {
    update.mutate(
      { activityId: activity.id, payload: { state } },
      { onSuccess: onClose },
    );
  }

  function confirmDelete() {
    del.mutate(
      {
        activityId: activity.id,
        farmId: activity.farm_id,
        planId: activity.plan_id,
      },
      { onSuccess: onClose },
    );
  }

  return (
    <Modal open onClose={onClose} labelledBy="activity-detail-title" className="max-w-md">
      <h2 id="activity-detail-title" className="text-base font-semibold text-ap-ink">
        {t(`type.${activity.activity_type}`)}
      </h2>

      {mode === "view" ? (
        <ViewBody activity={activity} />
      ) : mode === "edit" ? (
        <EditBody
          activity={activity}
          farmId={_farmId}
          onClose={onClose}
          onCancel={() => setMode("view")}
        />
      ) : (
        <ConfirmDeleteBody activity={activity} />
      )}

      {mode === "view" ? (
        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-3 py-1.5 text-sm text-ap-muted"
          >
            {t("detail.close")}
          </button>
          {canManage ? (
            <>
              <button
                type="button"
                onClick={() => setMode("confirm-delete")}
                disabled={del.isPending}
                className="rounded-md border border-ap-crit/40 px-3 py-1.5 text-sm text-ap-crit hover:bg-ap-crit/10"
              >
                {t("detail.delete")}
              </button>
              <button
                type="button"
                onClick={() => setMode("edit")}
                className="rounded-md border border-ap-line px-3 py-1.5 text-sm"
              >
                {t("detail.edit")}
              </button>
            </>
          ) : null}
          {canComplete && activity.status === "scheduled" ? (
            <button
              type="button"
              onClick={() => runAction("start")}
              disabled={update.isPending}
              className="rounded-md border border-ap-line px-3 py-1.5 text-sm"
            >
              {t("detail.start")}
            </button>
          ) : null}
          {canComplete &&
          (activity.status === "scheduled" || activity.status === "in_progress") ? (
            <>
              <button
                type="button"
                onClick={() => runAction("skip")}
                disabled={update.isPending}
                className="rounded-md border border-ap-line px-3 py-1.5 text-sm"
              >
                {t("detail.skip")}
              </button>
              <button
                type="button"
                onClick={() => runAction("complete")}
                disabled={update.isPending}
                className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary-700"
              >
                {t("detail.complete")}
              </button>
            </>
          ) : null}
        </div>
      ) : null}

      {mode === "confirm-delete" ? (
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => setMode("view")}
            disabled={del.isPending}
            className="rounded-md px-3 py-1.5 text-sm text-ap-muted"
          >
            {t("detail.cancel")}
          </button>
          <button
            type="button"
            onClick={confirmDelete}
            disabled={del.isPending}
            className="rounded-md bg-ap-crit px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-crit/90 disabled:opacity-60"
          >
            {del.isPending ? t("detail.deleting") : t("detail.deleteConfirm")}
          </button>
        </div>
      ) : null}

      {del.isError ? (
        <p className="mt-2 text-xs text-ap-crit">{t("detail.deleteFailed")}</p>
      ) : null}
    </Modal>
  );
}

function ViewBody({ activity }: { activity: BoardActivity }): ReactNode {
  const { t } = useTranslation("board");
  return (
    <dl className="mt-3 space-y-2 text-sm">
      <Row label={t("detail.date")}>
        {format(parseISO(activity.scheduled_date), "EEE, MMM d, yyyy")}
      </Row>
      <Row label={t("detail.status")}>{t(`status.${activity.status}`)}</Row>
      {activity.product_name ? (
        <Row label={t("detail.product")}>{activity.product_name}</Row>
      ) : null}
      {activity.dosage ? (
        <Row label={t("detail.dosage")}>{activity.dosage}</Row>
      ) : null}
      {activity.notes ? (
        <Row label={t("detail.notes")}>{activity.notes}</Row>
      ) : null}
      {activity.resources.length > 0 ? (
        <Row label={t("detail.assigned")}>
          <div className="flex flex-wrap gap-1">
            {activity.resources.map((r) => (
              <span
                key={r.id}
                className="rounded bg-ap-bg/50 px-2 py-0.5 text-xs"
              >
                {r.kind === "worker" ? "👤" : "🔧"} {r.name}
              </span>
            ))}
          </div>
        </Row>
      ) : null}
    </dl>
  );
}

function EditBody({
  activity,
  farmId,
  onClose,
  onCancel,
}: {
  activity: BoardActivity;
  farmId: string;
  onClose: () => void;
  onCancel: () => void;
}): ReactNode {
  const { t } = useTranslation("board");
  const update = useUpdateActivity();
  const attach = useAttachResource(farmId);
  const detach = useDetachResource(farmId);
  const [activityType, setActivityType] = useState<ActivityType>(
    activity.activity_type,
  );
  const [scheduledDate, setScheduledDate] = useState(activity.scheduled_date);
  const [notes, setNotes] = useState(activity.notes ?? "");
  const [productName, setProductName] = useState(activity.product_name ?? "");
  const [dosage, setDosage] = useState(activity.dosage ?? "");
  // Resources are managed via separate attach/detach endpoints (not
  // through PATCH activity). Track desired set vs current; on save
  // we diff and fire the minimal set of mutations.
  const [resourceIds, setResourceIds] = useState<Set<string>>(
    () => new Set(activity.resources.map((r) => r.id)),
  );

  const resourcesQ = useResources(farmId, { include_archived: false });
  const workers = useMemo(
    () => (resourcesQ.data ?? []).filter((r) => r.kind === "worker"),
    [resourcesQ.data],
  );
  const equipment = useMemo(
    () => (resourcesQ.data ?? []).filter((r) => r.kind === "equipment"),
    [resourcesQ.data],
  );

  function toggleResource(id: string) {
    setResourceIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function submit() {
    // PATCH only sends fields that actually changed so the audit trail
    // reflects intent, not "everything got re-written".
    const payload: {
      activity_type?: ActivityType;
      scheduled_date?: string;
      notes?: string | null;
      product_name?: string | null;
      dosage?: string | null;
    } = {};
    if (activityType !== activity.activity_type) payload.activity_type = activityType;
    if (scheduledDate !== activity.scheduled_date) payload.scheduled_date = scheduledDate;
    if ((notes || null) !== (activity.notes ?? null)) payload.notes = notes.trim() || null;
    if ((productName || null) !== (activity.product_name ?? null)) {
      payload.product_name = productName.trim() || null;
    }
    if ((dosage || null) !== (activity.dosage ?? null)) {
      payload.dosage = dosage.trim() || null;
    }

    // Diff assigned resources to compute attach/detach work.
    const currentIds = new Set(activity.resources.map((r) => r.id));
    const toAttach = Array.from(resourceIds).filter((id) => !currentIds.has(id));
    const toDetach = Array.from(currentIds).filter((id) => !resourceIds.has(id));

    if (
      Object.keys(payload).length === 0 &&
      toAttach.length === 0 &&
      toDetach.length === 0
    ) {
      onCancel();
      return;
    }

    if (Object.keys(payload).length > 0) {
      await update.mutateAsync({ activityId: activity.id, payload });
    }
    // Resources: ignore individual failures so a partial save still
    // produces a usable activity (mirrors QuickAddDialog policy).
    await Promise.allSettled([
      ...toAttach.map((rid) =>
        attach.mutateAsync({ activityId: activity.id, resourceId: rid }),
      ),
      ...toDetach.map((rid) =>
        detach.mutateAsync({ activityId: activity.id, resourceId: rid }),
      ),
    ]);
    onClose();
  }

  const isSubmitting = update.isPending || attach.isPending || detach.isPending;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      className="mt-3 flex flex-col gap-3 text-sm"
    >
      <label className="flex flex-col gap-1">
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
      <label className="flex flex-col gap-1">
        <span className="text-ap-muted">{t("detail.date")}</span>
        <input
          type="date"
          className="rounded-md border border-ap-line bg-white px-2 py-1.5"
          value={scheduledDate}
          onChange={(e) => setScheduledDate(e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-ap-muted">{t("detail.product")}</span>
        <input
          type="text"
          maxLength={255}
          className="rounded-md border border-ap-line bg-white px-2 py-1.5"
          value={productName}
          onChange={(e) => setProductName(e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-ap-muted">{t("detail.dosage")}</span>
        <input
          type="text"
          maxLength={128}
          className="rounded-md border border-ap-line bg-white px-2 py-1.5"
          value={dosage}
          onChange={(e) => setDosage(e.target.value)}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-ap-muted">{t("detail.notes")}</span>
        <textarea
          className="min-h-[60px] rounded-md border border-ap-line bg-white px-2 py-1.5"
          maxLength={4000}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </label>

      <div className="flex flex-col gap-1">
        <span className="text-ap-muted">{t("quickAdd.assigned")}</span>
        {resourcesQ.isLoading ? (
          <p className="text-xs text-ap-muted">…</p>
        ) : workers.length + equipment.length === 0 ? (
          <p className="text-xs text-ap-muted">{t("quickAdd.noResources")}</p>
        ) : (
          <div className="flex max-h-40 flex-col gap-1 overflow-y-auto rounded border border-ap-line p-2">
            <ResourceGroup
              label={t("quickAdd.workers")}
              items={workers}
              selected={resourceIds}
              onToggle={toggleResource}
            />
            <ResourceGroup
              label={t("quickAdd.equipment")}
              items={equipment}
              selected={resourceIds}
              onToggle={toggleResource}
            />
          </div>
        )}
      </div>

      {update.isError ? (
        <p className="text-xs text-ap-crit">{t("detail.editFailed")}</p>
      ) : null}

      <div className="mt-1 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={isSubmitting}
          className="rounded-md px-3 py-1.5 text-sm text-ap-muted"
        >
          {t("detail.cancel")}
        </button>
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary-700 disabled:opacity-60"
        >
          {isSubmitting ? t("detail.saving") : t("detail.save")}
        </button>
      </div>
    </form>
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

function ConfirmDeleteBody({
  activity,
}: {
  activity: BoardActivity;
}): ReactNode {
  const { t } = useTranslation("board");
  return (
    <div className="mt-3 rounded-md border border-ap-crit/30 bg-ap-crit/5 p-3 text-sm">
      <p className="font-medium text-ap-crit">{t("detail.deleteHeading")}</p>
      <p className="mt-1 text-ap-ink">
        {t("detail.deleteBody", {
          type: t(`type.${activity.activity_type}`),
          date: format(parseISO(activity.scheduled_date), "EEE, MMM d"),
        })}
      </p>
    </div>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}): ReactNode {
  return (
    <div className="flex gap-2">
      <dt className="w-24 flex-shrink-0 text-ap-muted">{label}</dt>
      <dd className="flex-1 text-ap-ink">{children}</dd>
    </div>
  );
}
