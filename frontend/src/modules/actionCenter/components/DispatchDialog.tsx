import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import type { ActionItem } from "@/api/actionCenter";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { defaultAssignee } from "@/modules/actionCenter/lib/assignee";
import { buildAssigneeOptions } from "@/modules/actionCenter/lib/assigneeOptions";
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
 * **People come from the tenant user list, not from farm membership.** That is
 * deliberate and it is a fix: the block-edit form sets a block's responsible
 * member from `listTenantUsers()`, so sourcing this picker from `farm_scopes`
 * meant the two lists could disagree. A block owner who was not also a farm
 * member could not be rendered *or* re-selected here — the select held a value
 * with no matching option — and a farm with no `farm_scopes` rows produced an
 * empty dropdown even though block assignment worked fine. Farm membership is
 * still read, but only to annotate a person with their role on this farm.
 *
 * The select is ALWAYS rendered. Whatever the roster does — forbidden, failed,
 * empty — the user must still be able to choose someone, so a failure degrades
 * to a smaller list plus an explanation rather than to no control at all.
 */
export function DispatchDialog({ farmId, items, onClose, onDispatched }: Props): ReactNode {
  const { t } = useTranslation("actionCenter");
  const canReadMembers = useCapability("farm.member.read", { farmId });
  const canReadUsers = useCapability("user.read");
  // Roles are a nice-to-have annotation; names are the thing that matters.
  const members = useFarmMembers(canReadMembers ? farmId : null);
  const users = useTenantUsers();
  const dispatch = useDispatchActionItems();

  const blockCodes = [...new Set(items.map((i) => i.block_code))];
  const cellCount = items.filter((i) => i.cell !== null).length;

  const options = useMemo(
    () => buildAssigneeOptions(users.data ?? [], members.data ?? [], defaultAssignee(items)),
    [members.data, users.data, items],
  );

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

  // A note ABOUT the list, not a replacement FOR it — the select renders
  // either way. `null` means there is nothing worth saying.
  const rosterNote = users.isPending
    ? "membersLoading"
    : !canReadUsers
      ? "namesForbidden"
      : users.isError
        ? "membersError"
        : options.length === 0
          ? "membersEmpty"
          : null;

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

            <select
              id="dispatch-assignee"
              className="input"
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
            >
              <option value="">{t("dispatch.useBlockResponsible")}</option>
              {options.map((o) => (
                <option key={o.membershipId} value={o.membershipId}>
                  {o.role === null ? o.name : `${o.name} — ${o.role}`}
                </option>
              ))}
            </select>
            {rosterNote === null ? null : (
              <p className="mt-1 text-meta text-ap-warn">{t(`dispatch.${rosterNote}`)}</p>
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
              {/* "Set an owner in block settings" is useless advice without a
                  route: the field lives on the block edit form and nothing
                  links to it. Only offered for a single block, since a batch
                  spanning blocks has no one page to send them to. */}
              {noOneResponsible && singleBlock ? (
                <>
                  {" "}
                  <Link
                    className="text-ap-accent hover:underline"
                    to={`/farms/${farmId}/blocks/${items[0].block_id}/edit`}
                  >
                    {t("dispatch.setResponsible", { block: blockCodes[0] })}
                  </Link>
                </>
              ) : null}
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
