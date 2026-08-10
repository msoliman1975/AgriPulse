import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ActionItem } from "@/api/actionCenter";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { defaultAssignee } from "@/modules/actionCenter/lib/assignee";
import { useDispatchActionItems } from "@/queries/actionCenter";
import { useFarmMembers } from "@/queries/farmMembers";
import { useTenantUsers } from "@/queries/users";
import { useCapability } from "@/rbac/useCapability";

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
 * The assignee defaults to the block's responsible member
 * (`blocks.agronomist_membership_id`, carried on every item as
 * `responsible_membership_id`). When the blocks in the batch disagree, or name
 * nobody, the dialog stays on "each block's responsible member" and lets the
 * server resolve per item — which is strictly better than picking one name for
 * a mixed batch.
 *
 * The picker needs two capabilities the queue itself does not: `farm.member.read`
 * to list who is on the farm, and `user.read` to turn membership ids into names.
 * Missing either one used to render an empty dropdown with no explanation; the
 * states are now distinct, because "you cannot see the roster" and "this farm
 * has no members" need different fixes from the person reading it.
 */
export function DispatchDialog({ farmId, items, onClose, onDispatched }: Props): ReactNode {
  const { t } = useTranslation("actionCenter");
  const canReadMembers = useCapability("farm.member.read", { farmId });
  const canReadUsers = useCapability("user.read");
  const members = useFarmMembers(canReadMembers ? farmId : null);
  const users = useTenantUsers();
  const dispatch = useDispatchActionItems();

  const blockCodes = [...new Set(items.map((i) => i.block_code))];
  const cellCount = items.filter((i) => i.cell !== null).length;

  const options = useMemo(() => {
    const byMembership = new Map((users.data ?? []).map((u) => [u.membership_id, u]));
    return (members.data ?? [])
      .filter((m) => m.revoked_at === null)
      .map((m) => ({
        membershipId: m.membership_id,
        role: m.role,
        // Fall back to a short id rather than blank: an unnamed row is still
        // selectable, and a blank option looks like a broken list.
        name: byMembership.get(m.membership_id)?.full_name ?? m.membership_id.slice(0, 8),
      }));
  }, [members.data, users.data]);

  // The batch's default: the block owner, but only when every item agrees on
  // one. Mixed blocks fall back to per-item resolution on the server.
  const responsible = useMemo(() => defaultAssignee(items), [items]);

  const [assignee, setAssignee] = useState<string>(responsible);
  const [date, setDate] = useState<string>(today());
  const [notes, setNotes] = useState<string>("");

  const assigneeName = (id: string): string =>
    options.find((o) => o.membershipId === id)?.name ?? id.slice(0, 8);

  const singleBlock = blockCodes.length === 1;
  const noOneResponsible = items.every((i) => i.responsible_membership_id === null);

  const pickerState = !canReadMembers
    ? "forbidden"
    : members.isPending || users.isPending
      ? "loading"
      : members.isError
        ? "error"
        : options.length === 0
          ? "empty"
          : "ready";

  const submit = (): void => {
    dispatch.mutate(
      {
        farmId,
        payload: {
          item_ids: items.map((i) => i.id),
          // Empty means "let the server default each item to its own block's
          // responsible member" — per-item, so better than anything this
          // dialog could pick for a multi-block batch.
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

            {pickerState === "ready" ? (
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
            ) : (
              <p className="rounded-lg border border-ap-line bg-ap-bg/60 p-2 text-xs text-ap-muted">
                {pickerState === "loading"
                  ? t("dispatch.membersLoading")
                  : pickerState === "forbidden"
                    ? t("dispatch.membersForbidden")
                    : pickerState === "error"
                      ? t("dispatch.membersError")
                      : t("dispatch.membersEmpty")}
              </p>
            )}

            <p className="mt-1 text-meta text-ap-muted">
              {assignee !== ""
                ? t("dispatch.explicitExplained", { name: assigneeName(assignee) })
                : noOneResponsible
                  ? t("dispatch.noResponsibleExplained")
                  : singleBlock && responsible !== ""
                    ? t("dispatch.blockDefaultExplained", {
                        name: assigneeName(responsible),
                        block: blockCodes[0],
                      })
                    : t("dispatch.perBlockExplained")}
            </p>
            {!canReadUsers && pickerState === "ready" ? (
              <p className="mt-1 text-meta text-ap-warn">{t("dispatch.namesForbidden")}</p>
            ) : null}
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
