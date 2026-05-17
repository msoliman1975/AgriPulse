import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useCapability } from "@/rbac/useCapability";
import {
  useInvitePlatformAdmin,
  usePlatformAdmins,
  useRemovePlatformAdmin,
  type PlatformAdminRow,
} from "@/queries/platformAdminsRoles";

const ROLES = ["PlatformAdmin", "PlatformSupport"] as const;

/**
 * /platform/admins — self-service add/remove for platform-tier role
 * holders. The seeded PlatformAdmin (env-var bootstrap, PR-Reorg6)
 * uses this page to grow the team.
 */
export function PlatformAdminsPage(): ReactNode {
  const { t } = useTranslation("admin");
  const canManage = useCapability("platform.manage_platform_admins");
  const adminsQ = usePlatformAdmins();
  const invite = useInvitePlatformAdmin();
  const remove = useRemovePlatformAdmin();

  const [openInvite, setOpenInvite] = useState(false);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<(typeof ROLES)[number]>("PlatformAdmin");

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ap-ink">{t("platformAdmins.title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("platformAdmins.subtitle")}</p>
        </div>
        {canManage ? (
          <button
            type="button"
            onClick={() => setOpenInvite(true)}
            className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90"
          >
            {t("platformAdmins.inviteButton")}
          </button>
        ) : null}
      </header>

      <section className="rounded-xl border border-ap-line bg-ap-panel">
        {adminsQ.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : adminsQ.isError ? (
          <p className="p-4 text-sm text-ap-crit">{t("platformAdmins.loadFailed")}</p>
        ) : (adminsQ.data ?? []).length === 0 ? (
          <p className="p-12 text-center text-sm text-ap-muted">{t("platformAdmins.empty")}</p>
        ) : (
          <table className="min-w-full text-sm">
            <thead className="bg-ap-bg/40 text-xs uppercase text-ap-muted">
              <tr>
                <th className="px-4 py-2 text-start">{t("platformAdmins.col.user")}</th>
                <th className="px-4 py-2 text-start">{t("platformAdmins.col.role")}</th>
                <th className="px-4 py-2 text-end">{t("platformAdmins.col.actions")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ap-line">
              {(adminsQ.data ?? []).map((row) => (
                <Row
                  key={`${row.user_id}-${row.role}`}
                  row={row}
                  canManage={canManage}
                  onRemove={() => remove.mutate({ userId: row.user_id, role: row.role })}
                  removing={remove.isPending}
                />
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Invite modal */}
      {openInvite ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-xl bg-ap-panel p-4 shadow-lg">
            <h3 className="text-sm font-semibold text-ap-ink">{t("platformAdmins.inviteTitle")}</h3>
            <p className="mt-2 text-xs text-ap-muted">{t("platformAdmins.inviteHint")}</p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (!email.trim() || !fullName.trim()) return;
                invite.mutate(
                  { email: email.trim(), full_name: fullName.trim(), role },
                  {
                    onSuccess: () => {
                      setOpenInvite(false);
                      setEmail("");
                      setFullName("");
                      setRole("PlatformAdmin");
                    },
                  },
                );
              }}
              className="mt-3 flex flex-col gap-3"
            >
              <label className="flex flex-col text-xs">
                {t("platformAdmins.invite.email")}
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="mt-1 rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
                />
              </label>
              <label className="flex flex-col text-xs">
                {t("platformAdmins.invite.fullName")}
                <input
                  required
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="mt-1 rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
                />
              </label>
              <label className="flex flex-col text-xs">
                {t("platformAdmins.invite.role")}
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value as (typeof ROLES)[number])}
                  className="mt-1 rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setOpenInvite(false);
                    setEmail("");
                    setFullName("");
                    setRole("PlatformAdmin");
                  }}
                  className="rounded-md border border-ap-line bg-ap-panel px-3 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
                >
                  {t("platformAdmins.invite.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={invite.isPending}
                  className="rounded-md bg-ap-primary px-3 py-1 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
                >
                  {invite.isPending
                    ? t("platformAdmins.invite.submitting")
                    : t("platformAdmins.invite.submit")}
                </button>
              </div>
              {invite.error ? <p className="text-xs text-ap-crit">{invite.error.message}</p> : null}
              {invite.data ? (
                <p className="text-xs text-ap-muted">
                  {invite.data.keycloak_provisioning === "succeeded"
                    ? t("platformAdmins.invite.kcOk")
                    : t("platformAdmins.invite.kcPending")}
                </p>
              ) : null}
            </form>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Row({
  row,
  canManage,
  onRemove,
  removing,
}: {
  row: PlatformAdminRow;
  canManage: boolean;
  onRemove: () => void;
  removing: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <tr>
      <td className="px-4 py-2 text-ap-ink">
        {row.full_name ? `${row.full_name} ` : ""}
        <span className="text-ap-muted">&lt;{row.email}&gt;</span>
        {row.keycloak_subject?.startsWith("pending::") ? (
          <span className="ms-2 text-[11px] text-ap-warn">{t("platformAdmins.pendingKc")}</span>
        ) : null}
      </td>
      <td className="px-4 py-2">
        <Pill kind={row.role === "PlatformAdmin" ? "warn" : "info"}>{row.role}</Pill>
      </td>
      <td className="px-4 py-2 text-end">
        {canManage ? (
          <button
            type="button"
            onClick={onRemove}
            disabled={removing}
            className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-crit hover:bg-rose-50 disabled:opacity-60"
          >
            {t("platformAdmins.removeButton")}
          </button>
        ) : null}
      </td>
    </tr>
  );
}
