import { useTranslation } from "react-i18next";

import type { FarmMember } from "@/api/farmMembers";
import { Button } from "@/components/Button";
import { displayUser, displayUserHandle } from "@/lib/userDisplay";
import { useTenantUsers } from "@/queries/users";
import { useCapability } from "@/rbac/useCapability";

interface Props {
  members: FarmMember[];
  canRevoke: boolean;
  onRevoke?: (farmScopeId: string) => void;
}

export function MembersList({ members, canRevoke, onRevoke }: Props): JSX.Element {
  const { t, i18n } = useTranslation("farms");
  // The row used to read `<Role> dac59e9d…`, which names nobody. The
  // membership id is only an identifier; the person's name comes from the
  // tenant user list, the same source the assign picker already reads.
  const canReadUsers = useCapability("user.read");
  const tenantUsers = useTenantUsers({ enabled: canReadUsers });
  const byMembershipId = new Map((tenantUsers.data ?? []).map((u) => [u.membership_id, u]));

  const active = members.filter((m) => m.revoked_at === null);
  if (active.length === 0) {
    return <p className="text-sm text-ap-muted">{t("members.empty")}</p>;
  }
  return (
    <ul className="divide-y divide-ap-line">
      {active.map((m) => {
        const person = byMembershipId.get(m.membership_id);
        // No name to show yet (still loading, or `user.read` denied): keep the
        // short id rather than an empty cell, so the row is never blank.
        const label = person
          ? displayUser(person, m.membership_id)
          : `${m.membership_id.slice(0, 8)}…`;
        const handle = person ? displayUserHandle(person) : null;
        return (
          <li key={m.id} className="flex items-center justify-between py-2 text-sm">
            <span className="min-w-0">
              <span className="block truncate font-medium text-ap-ink">{label}</span>
              <span className="block truncate text-xs text-ap-muted">
                {t(`roles.${m.role}`)}
                {handle ? ` · ${handle}` : ""}
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-3">
              <time className="text-xs text-ap-muted">
                {new Date(m.granted_at).toLocaleDateString(i18n.language)}
              </time>
              {canRevoke && onRevoke ? (
                <Button variant="ghost" className="text-ap-crit" onClick={() => onRevoke(m.id)}>
                  {t("members.revoke")}
                </Button>
              ) : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
