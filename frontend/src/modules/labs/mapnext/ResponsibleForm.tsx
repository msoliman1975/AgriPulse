import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  listBlockResponsibleHistory,
  setBlockResponsible,
  type BlockResponsibleLogEntry,
} from "@/api/blocks";
import { Button } from "@/components/Button";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useTenantUsers } from "@/queries/users";
import { useCapability } from "@/rbac/useCapability";
import { displayUser } from "@/lib/userDisplay";

interface Props {
  blockId: string;
  farmId: string;
  /** Current value, so the form opens on the truth without waiting on a fetch. */
  current: string | null;
  onSaved: () => void;
}

/**
 * Who is responsible for this block — form plus handover history.
 *
 * This is `blocks.agronomist_membership_id`, the field the Action Center
 * defaults dispatch to. It lives under Manage rather than on the overview
 * because it is a decision someone makes deliberately, not a stat to read: an
 * inline picker that saved on change gave no room for the reason, and no way
 * to see who it came from.
 *
 * Current value + history + form on one panel, the same shape
 * `CropAssignmentPanel` uses — reassigning without seeing who you are
 * replacing is how a block quietly loses its owner.
 */
export function ResponsibleForm({ blockId, farmId, current, onSaved }: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const dateLocale = useDateLocale();
  const qc = useQueryClient();
  const canEdit = useCapability("block.update_metadata", { farmId });
  const canReadUsers = useCapability("user.read");
  const users = useTenantUsers();

  const history = useQuery({
    queryKey: ["block_responsible_history", blockId] as const,
    queryFn: () => listBlockResponsibleHistory(blockId),
  });

  const [membershipId, setMembershipId] = useState<string>(current ?? "");
  const [note, setNote] = useState("");

  const save = useMutation<BlockResponsibleLogEntry[], Error, void>({
    mutationFn: () =>
      setBlockResponsible(blockId, {
        membership_id: membershipId === "" ? null : membershipId,
        note: note.trim() === "" ? null : note.trim(),
      }),
    onSuccess: (entries) => {
      // The response IS the refreshed history, so seed it rather than refetch.
      qc.setQueryData(["block_responsible_history", blockId], entries);
      setNote("");
      onSaved();
    },
  });

  const nameOf = (membership: string | null): string => {
    if (membership === null) return t("responsible.none");
    const u = (users.data ?? []).find((x) => x.membership_id === membership);
    return u ? displayUser(u, membership) : membership.slice(0, 8);
  };

  const when = (iso: string): string =>
    new Date(iso).toLocaleString(dateLocale.code ?? undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });

  const dirty = (membershipId === "" ? null : membershipId) !== current || note.trim() !== "";

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-xl border border-ap-line p-3">
        <h3 className="mb-2 text-card-title font-semibold">{t("responsible.formTitle")}</h3>

        <p className="mb-3 text-sm text-ap-muted">{t("responsible.hint")}</p>

        <label className="label" htmlFor="responsible-member">
          {t("responsible.label")}
        </label>
        <select
          id="responsible-member"
          className="input"
          value={membershipId}
          disabled={!canEdit || !canReadUsers || save.isPending}
          onChange={(e) => setMembershipId(e.target.value)}
        >
          <option value="">{t("responsible.none")}</option>
          {(users.data ?? []).map((u) => (
            <option key={u.membership_id} value={u.membership_id}>
              {displayUser(u, u.membership_id)}
            </option>
          ))}
        </select>

        <label className="label mt-3" htmlFor="responsible-note">
          {t("responsible.noteLabel")}
        </label>
        <textarea
          id="responsible-note"
          className="input"
          rows={2}
          value={note}
          disabled={!canEdit || save.isPending}
          placeholder={t("responsible.notePlaceholder")}
          onChange={(e) => setNote(e.target.value)}
        />

        {!canReadUsers ? (
          <p className="mt-2 text-meta text-ap-warn">{t("responsible.namesForbidden")}</p>
        ) : null}
        {!canEdit ? (
          <p className="mt-2 text-meta text-ap-muted">{t("responsible.readOnly")}</p>
        ) : null}
        {save.isError ? (
          <p className="mt-2 rounded-lg bg-ap-crit-soft p-2 text-xs text-ap-crit">
            {t("responsible.saveFailed")}
          </p>
        ) : null}

        <div className="mt-3 flex justify-end gap-2">
          <Button
            variant="secondary"
            disabled={!dirty || save.isPending}
            onClick={() => {
              setMembershipId(current ?? "");
              setNote("");
            }}
          >
            {t("responsible.reset")}
          </Button>
          <Button disabled={!canEdit || !dirty || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? t("responsible.saving") : t("responsible.save")}
          </Button>
        </div>
      </section>

      <section className="rounded-xl border border-ap-line p-3">
        <h3 className="mb-2 text-card-title font-semibold">{t("responsible.historyTitle")}</h3>
        {history.isPending ? (
          <p className="text-sm text-ap-muted">{t("responsible.historyLoading")}</p>
        ) : history.isError ? (
          <p className="text-sm text-ap-crit">{t("responsible.historyFailed")}</p>
        ) : (history.data ?? []).length === 0 ? (
          <p className="text-sm text-ap-muted">{t("responsible.historyEmpty")}</p>
        ) : (
          <ol className="flex flex-col gap-2">
            {(history.data ?? []).map((h) => (
              <li key={h.id} className="rounded-lg bg-ap-bg/60 px-3 py-2 text-sm">
                <div className="text-ap-ink">
                  {h.previous_membership_id === null
                    ? t("responsible.entryFirst", { to: nameOf(h.new_membership_id) })
                    : t("responsible.entryHandover", {
                        from: nameOf(h.previous_membership_id),
                        to: nameOf(h.new_membership_id),
                      })}
                </div>
                <div className="text-meta text-ap-muted">{when(h.changed_at)}</div>
                {h.note !== null ? <div className="mt-1 text-ap-muted">“{h.note}”</div> : null}
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
