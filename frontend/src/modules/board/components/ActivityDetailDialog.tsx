import { format, parseISO } from "date-fns";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { BoardActivity } from "@/api/plans";
import { Modal } from "@/components/Modal";
import { useCapability } from "@/rbac/useCapability";
import { useUpdateActivity } from "@/queries/plans";

interface ActivityDetailDialogProps {
  farmId: string;
  activity: BoardActivity;
  onClose: () => void;
}

/** Read-only activity detail with state-action buttons. Edit-drawer
 * (rescheduling, dosage, etc.) is deferred to PR-6.
 */
export function ActivityDetailDialog({
  farmId: _farmId,
  activity,
  onClose,
}: ActivityDetailDialogProps): ReactNode {
  const { t } = useTranslation("board");
  const canComplete = useCapability("plan_activity.complete");
  const update = useUpdateActivity();

  function runAction(state: "start" | "complete" | "skip") {
    update.mutate(
      { activityId: activity.id, payload: { state } },
      { onSuccess: onClose },
    );
  }

  return (
    <Modal open onClose={onClose} labelledBy="activity-detail-title" className="max-w-md">
      <h2 id="activity-detail-title" className="text-base font-semibold text-ap-ink">
        {t(`type.${activity.activity_type}`)}
      </h2>
      <dl className="mt-3 space-y-2 text-sm">
        <Row label={t("detail.date")}>
          {format(parseISO(activity.scheduled_date), "EEE, MMM d, yyyy")}
        </Row>
        <Row label={t("detail.status")}>{t(`status.${activity.status}`)}</Row>
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

      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-3 py-1.5 text-sm text-ap-muted"
        >
          {t("detail.close")}
        </button>
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
    </Modal>
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
