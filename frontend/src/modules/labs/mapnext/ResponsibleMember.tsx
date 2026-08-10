import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { updateBlock } from "@/api/blocks";
import { useTenantUsers } from "@/queries/users";
import { useCapability } from "@/rbac/useCapability";

interface Props {
  farmId: string;
  blockId: string;
  /** `blocks.agronomist_membership_id` — the block's responsible member. */
  value: string | null;
  onChanged: (membershipId: string | null) => void;
}

/**
 * Who is responsible for this block.
 *
 * This is `blocks.agronomist_membership_id`, and it is the field the Action
 * Center's dispatch defaults to. Until now the only way to set it was a legacy
 * block-edit form that nothing in the console linked to — you had to go through
 * the *imagery & weather* config page to reach it, which is not a route anyone
 * would guess for "who owns this block".
 *
 * Read-only when the caller lacks `block.update_metadata`: the name still shows,
 * because knowing who is responsible is useful even to someone who cannot
 * change it. Hiding the whole row on a missing capability is what made this
 * invisible in the first place.
 */
export function ResponsibleMember({ farmId, blockId, value, onChanged }: Props): ReactNode {
  const { t } = useTranslation("farmConsole");
  const canEdit = useCapability("block.update_metadata", { farmId });
  const canReadUsers = useCapability("user.read");
  const users = useTenantUsers();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);

  const nameOf = (membershipId: string): string => {
    const u = (users.data ?? []).find((x) => x.membership_id === membershipId);
    return u?.full_name || u?.email || membershipId.slice(0, 8);
  };

  const save = async (next: string): Promise<void> => {
    setSaving(true);
    setError(false);
    try {
      await updateBlock(blockId, { agronomist_membership_id: next === "" ? null : next });
      onChanged(next === "" ? null : next);
    } catch {
      // Leave the previous value on screen rather than showing a change that
      // did not persist.
      setError(true);
    } finally {
      setSaving(false);
    }
  };

  // Without `user.read` there is no roster to pick from and no name to show,
  // so state the id rather than pretending the field is empty.
  if (!canReadUsers) {
    return (
      <p className="text-sm text-ap-muted">
        {value === null ? t("responsible.none") : t("responsible.hiddenName")}
      </p>
    );
  }

  if (!canEdit) {
    return (
      <p className="text-sm text-ap-ink">
        {value === null ? t("responsible.none") : nameOf(value)}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-1">
      <select
        className="input"
        aria-label={t("responsible.label")}
        value={value ?? ""}
        disabled={saving}
        onChange={(e) => void save(e.target.value)}
      >
        <option value="">{t("responsible.none")}</option>
        {(users.data ?? []).map((u) => (
          <option key={u.membership_id} value={u.membership_id}>
            {u.full_name || u.email}
          </option>
        ))}
      </select>
      {error ? <p className="text-meta text-ap-crit">{t("responsible.saveFailed")}</p> : null}
      <p className="text-meta text-ap-muted">{t("responsible.hint")}</p>
    </div>
  );
}
