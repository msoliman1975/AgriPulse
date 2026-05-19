// FarmMembersTab — assign / revoke per-farm role assignments. Embedded
// in FarmDrawer's "Members" panel. Mirrors the legacy /farms/:id/members
// page (FarmMembersPage) but without the page chrome and tightened for
// the horizontal drawer's narrower row layout. End goal is to retire
// the legacy page once parity is reached.

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  assignFarmMember,
  listFarmMembers,
  revokeFarmMember,
  type FarmMember,
  type FarmMemberRole,
} from "@/api/farmMembers";
import { isApiError } from "@/api/errors";
import { useCapability } from "@/rbac/useCapability";
import { useTenantUsers } from "@/queries/users";
import { MembersList } from "@/modules/farms/components/MembersList";

const ROLES: FarmMemberRole[] = ["FarmManager", "Agronomist", "FieldOperator", "Scout", "Viewer"];

interface Props {
  farmId: string;
}

export function FarmMembersTab({ farmId }: Props): JSX.Element {
  const { t } = useTranslation("farms");
  const canAssign = useCapability("role.assign_farm", { farmId });
  const canReadUsers = useCapability("user.read");
  const tenantUsers = useTenantUsers();

  const [members, setMembers] = useState<FarmMember[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [membershipId, setMembershipId] = useState("");
  const [role, setRole] = useState<FarmMemberRole>("FarmManager");
  const [busy, setBusy] = useState(false);

  async function refresh(): Promise<void> {
    try {
      const data = await listFarmMembers(farmId);
      setMembers(data);
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [farmId]);

  async function handleAssign(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await assignFarmMember(farmId, membershipId, role);
      setMembershipId("");
      await refresh();
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleRevoke(farmScopeId: string): Promise<void> {
    setBusy(true);
    try {
      await revokeFarmMember(farmId, farmScopeId);
      await refresh();
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3">
      {error ? (
        <p role="alert" className="rounded bg-red-50 px-2 py-1 text-[11px] text-red-700">
          {error}
        </p>
      ) : null}

      <MembersList members={members} canRevoke={canAssign} onRevoke={handleRevoke} />

      {canAssign ? (
        <form
          onSubmit={handleAssign}
          className="grid grid-cols-1 gap-2 rounded border border-slate-200 bg-slate-50 p-2 md:grid-cols-[1fr_auto_auto] md:items-end"
        >
          <label className="block text-[11px]">
            <span className="text-slate-500">{t("members.membershipId")}</span>
            {canReadUsers && tenantUsers.data && tenantUsers.data.length > 0 ? (
              <select
                className="mt-0.5 w-full rounded border border-slate-300 bg-white px-2 py-1 text-[12px]"
                value={membershipId}
                onChange={(e) => setMembershipId(e.target.value)}
                required
              >
                <option value="" disabled>
                  —
                </option>
                {tenantUsers.data
                  .filter((u) => !members.some((m) => m.membership_id === u.membership_id))
                  .map((u) => (
                    <option key={u.membership_id} value={u.membership_id}>
                      {u.full_name} — {u.email}
                    </option>
                  ))}
              </select>
            ) : (
              <input
                className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-[12px]"
                value={membershipId}
                onChange={(e) => setMembershipId(e.target.value)}
                required
                placeholder="00000000-0000-0000-0000-000000000000"
              />
            )}
          </label>
          <label className="block text-[11px]">
            <span className="text-slate-500">{t("members.role")}</span>
            <select
              className="mt-0.5 w-full rounded border border-slate-300 bg-white px-2 py-1 text-[12px]"
              value={role}
              onChange={(e) => setRole(e.target.value as FarmMemberRole)}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(`roles.${r}`)}
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            className="rounded bg-slate-900 px-3 py-1 text-[12px] font-medium text-white hover:bg-slate-800 disabled:opacity-50"
            disabled={busy}
          >
            {t("members.submit")}
          </button>
        </form>
      ) : null}
    </div>
  );
}
