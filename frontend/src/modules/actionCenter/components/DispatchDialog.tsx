import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActionItem } from "@/api/actionCenter";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { useDispatchActionItems } from "@/queries/actionCenter";
import { useFarmMembers } from "@/queries/farmMembers";
import { useTenantUsers } from "@/queries/users";

interface Props {
  farmId: string;
  items: ActionItem[];
  onClose: () => void;
  onDispatched: () => void;
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Dispatch — assign items to a team member as board activities.
 *
 * The assignee defaults to the block's responsible member. When the block
 * names nobody the server still picks one, and this dialog *says so*: a silent
 * arbitrary assignment is worse than no default, because the supervisor has no
 * way to know the name in front of them was a coin toss.
 */
export function DispatchDialog({ farmId, items, onClose, onDispatched }: Props): ReactNode {
  const { t } = useTranslation("actionCenter");
  const members = useFarmMembers(farmId);
  const users = useTenantUsers();
  const dispatch = useDispatchActionItems();

  const blockCodes = [...new Set(items.map((i) => i.block_code))];
  const cellCount = items.filter((i) => i.cell !== null).length;

  // Assignable people = this farm's members, named via the tenant user list.
  const options = useMemo(() => {
    const byMembership = new Map((users.data ?? []).map((u) => [u.membership_id, u]));
    return (members.data ?? [])
      .filter((m) => m.revoked_at === null)
      .map((m) => ({
        membershipId: m.membership_id,
        role: m.role,
        name: byMembership.get(m.membership_id)?.full_name ?? m.membership_id.slice(0, 8),
      }));
  }, [members.data, users.data]);

  // Default from the first item's block. Only meaningful when the batch is one
  // block; with several we still have to start somewhere, and the supervisor
  // can override for the whole batch.
  const blockDefault = items[0]?.block_id;
  const defaultMembership = useMemo(() => {
    const sameBlock = items.filter((i) => i.block_id === blockDefault);
    return sameBlock.find((i) => i.assigned_membership_id !== null)?.assigned_membership_id ?? "";
  }, [items, blockDefault]);

  const [assignee, setAssignee] = useState<string>(defaultMembership);
  const [date, setDate] = useState<string>(today());
  const [notes, setNotes] = useState<string>("");

  const submit = (): void => {
    dispatch.mutate(
      {
        farmId,
        payload: {
          item_ids: items.map((i) => i.id),
          // Empty means "let the server default to each block's responsible
          // member" — which is per-item and therefore better than anything
          // this dialog could pick for a multi-block batch.
          assigned_membership_id: assignee === "" ? null : assignee,
          scheduled_date: date,
          notes: notes === "" ? null : notes,
        },
      },
      { onSuccess: onDispatched },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ap-ink/30 p-4">
      <Card noPadding className="w-full max-w-lg">
        <div className="flex items-start justify-between gap-3 border-b border-ap-line p-4">
          <div>
            <h3 className="text-section-title font-semibold">{t("dispatch.title")}</h3>
            <p className="text-xs text-ap-muted">
              {t("dispatch.summary", { count: items.length, blocks: blockCodes.length })}
              {cellCount > 0 ? ` · ${t("group.atCellLevel", { count: cellCount })}` : ""}
            </p>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose} aria-label={t("dispatch.close")}>
            ✕
          </Button>
        </div>

        <div className="p-4">
          <div className="mb-3">
            <label className="label" htmlFor="dispatch-assignee">
              {t("dispatch.assignTo")}
            </label>
            <select
              id="dispatch-assignee"
              className="input"
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
            >
              <option value="">{t("dispatch.useBlockResponsible")}</option>
              {options.map((o) => (
                <option key={o.membershipId} value={o.membershipId}>
                  {o.name} — {o.role}
                </option>
              ))}
            </select>
            <p className="mt-1 text-meta text-ap-muted">
              {assignee === "" ? t("dispatch.defaultExplained") : t("dispatch.explicitExplained")}
            </p>
          </div>

          <div className="mb-3">
            <label className="label" htmlFor="dispatch-date">
              {t("dispatch.scheduledDate")}
            </label>
            <input
              id="dispatch-date"
              type="date"
              className="input"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>

          <div className="mb-3">
            <label className="label" htmlFor="dispatch-notes">
              {t("dispatch.notes")}
            </label>
            <textarea
              id="dispatch-notes"
              className="input"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder={t("dispatch.notesPlaceholder")}
            />
          </div>

          {dispatch.isError ? (
            <p className="mb-3 rounded-lg bg-ap-crit-soft p-2 text-xs text-ap-crit">
              {t("dispatch.failed")}
            </p>
          ) : null}

          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              {t("dispatch.cancel")}
            </Button>
            <Button onClick={submit} disabled={dispatch.isPending}>
              {dispatch.isPending ? t("dispatch.sending") : t("dispatch.send")}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
