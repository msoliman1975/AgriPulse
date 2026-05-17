import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
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
import { MembersList } from "../components/MembersList";

const ROLES: FarmMemberRole[] = ["FarmManager", "Agronomist", "FieldOperator", "Scout", "Viewer"];

export function FarmMembersPage(): JSX.Element {
  const { farmId = "" } = useParams<{ farmId: string }>();
  const { t } = useTranslation("farms");
  const canAssign = useCapability("role.assign_farm", { farmId });
  const canReadUsers = useCapability("user.read");
  const tenantUsers = useTenantUsers();
  const [members, setMembers] = useState<FarmMember[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [membershipId, setMembershipId] = useState("");
  const [role, setRole] = useState<FarmMemberRole>("FarmManager");
  const [busy, setBusy] = useState(false);

  const refresh = async (): Promise<void> => {
    try {
      const data = await listFarmMembers(farmId);
      setMembers(data);
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    }
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [farmId]);

  const handleAssign = async (e: React.FormEvent): Promise<void> => {
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
  };

  const handleRevoke = async (farmScopeId: string): Promise<void> => {
    setBusy(true);
    try {
      await revokeFarmMember(farmId, farmScopeId);
      await refresh();
    } catch (err) {
      setError(isApiError(err) ? (err.problem.detail ?? err.problem.title) : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-brand-800">{t("members.heading")}</h1>
        <Link to={`/farms/${farmId}`} className="btn btn-ghost">
          {t("block.back")}
        </Link>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}

      <div className="card">
        <MembersList members={members} canRevoke={canAssign} onRevoke={handleRevoke} />
      </div>

      {canAssign ? (
        <form onSubmit={handleAssign} className="card flex items-end gap-3">
          <div className="flex-1">
            <label className="label" htmlFor="membership-id">
              {t("members.membershipId")}
            </label>
            {canReadUsers && tenantUsers.data && tenantUsers.data.length > 0 ? (
              <select
                id="membership-id"
                className="input"
                value={membershipId}
                onChange={(e) => setMembershipId(e.target.value)}
                required
              >
                <option value="" disabled>
                  —
                </option>
                {tenantUsers.data
                  // Hide users already assigned to this farm so the dropdown
                  // doesn't suggest re-adding them.
                  .filter((u) => !members.some((m) => m.membership_id === u.membership_id))
                  .map((u) => (
                    <option key={u.membership_id} value={u.membership_id}>
                      {u.full_name} — {u.email}
                    </option>
                  ))}
              </select>
            ) : (
              <input
                id="membership-id"
                className="input"
                value={membershipId}
                onChange={(e) => setMembershipId(e.target.value)}
                required
                placeholder="00000000-0000-0000-0000-000000000000"
              />
            )}
          </div>
          <div>
            <label className="label" htmlFor="member-role">
              {t("members.role")}
            </label>
            <select
              id="member-role"
              className="input"
              value={role}
              onChange={(e) => setRole(e.target.value as FarmMemberRole)}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(`roles.${r}`)}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {t("members.submit")}
          </button>
        </form>
      ) : null}
    </div>
  );
}
