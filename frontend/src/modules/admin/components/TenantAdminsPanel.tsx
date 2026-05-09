import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import {
  useInviteTenantAdmin,
  useRemoveTenantAdmin,
  useTenantAdmins,
  useTransferOwnership,
  type TenantAdminRow,
} from "@/queries/platformAdmins";

interface Props {
  tenantId: string;
  tenantSlug: string;
}

/**
 * Bottom-of-detail-page panel: list / invite / remove TenantAdmins
 * and transfer TenantOwner. Mounted on TenantAdminDetailPage.
 *
 * Transfer-ownership is a slug-confirmation flow (matches the purge
 * UX so the action feels equally weighty).
 */
export function TenantAdminsPanel({ tenantId, tenantSlug }: Props): ReactNode {
  const { t } = useTranslation("admin");
  const adminsQ = useTenantAdmins(tenantId);
  const inviteMut = useInviteTenantAdmin(tenantId);
  const removeMut = useRemoveTenantAdmin(tenantId);
  const transferMut = useTransferOwnership(tenantId);
  const [invEmail, setInvEmail] = useState("");
  const [invName, setInvName] = useState("");
  const [transferring, setTransferring] = useState<TenantAdminRow | null>(null);
  const [transferConfirm, setTransferConfirm] = useState("");

  const owner = adminsQ.data?.find((r) => r.role === "TenantOwner") ?? null;

  return (
    <section className="rounded-xl border border-ap-line bg-ap-panel p-4">
      <h2 className="text-sm font-semibold text-ap-ink">
        {t("admins.title")}
      </h2>
      <p className="mt-1 text-xs text-ap-muted">{t("admins.subtitle")}</p>

      {adminsQ.isLoading ? (
        <Skeleton className="mt-3 h-24 w-full" />
      ) : adminsQ.isError ? (
        <p className="mt-3 text-sm text-ap-crit">{t("admins.loadFailed")}</p>
      ) : (adminsQ.data ?? []).length === 0 ? (
        <p className="mt-3 text-sm text-ap-muted">{t("admins.empty")}</p>
      ) : (
        <table className="mt-3 min-w-full text-sm">
          <thead className="text-xs uppercase text-ap-muted">
            <tr>
              <th className="px-2 py-1 text-start">{t("admins.col.email")}</th>
              <th className="px-2 py-1 text-start">{t("admins.col.role")}</th>
              <th className="px-2 py-1 text-end">{t("admins.col.actions")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ap-line">
            {(adminsQ.data ?? []).map((row) => (
              <tr key={`${row.user_id}-${row.role}`}>
                <td className="px-2 py-2 text-ap-ink">
                  {row.full_name ? `${row.full_name} ` : ""}
                  <span className="text-ap-muted">&lt;{row.email}&gt;</span>
                </td>
                <td className="px-2 py-2">
                  <Pill kind={row.role === "TenantOwner" ? "warn" : "info"}>
                    {row.role}
                  </Pill>
                </td>
                <td className="px-2 py-2 text-end">
                  {row.role === "TenantOwner" ? (
                    <span className="text-xs text-ap-muted">
                      {t("admins.ownerHint")}
                    </span>
                  ) : (
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => setTransferring(row)}
                        className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
                      >
                        {t("admins.transferToButton")}
                      </button>
                      <button
                        type="button"
                        onClick={() => removeMut.mutate(row.user_id)}
                        disabled={removeMut.isPending}
                        className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-crit hover:bg-rose-50"
                      >
                        {t("admins.removeButton")}
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* Invite form */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!invEmail.trim() || !invName.trim()) return;
          inviteMut.mutate(
            { email: invEmail.trim(), full_name: invName.trim() },
            {
              onSuccess: () => {
                setInvEmail("");
                setInvName("");
              },
            },
          );
        }}
        className="mt-4 flex flex-wrap items-end gap-2 border-t border-ap-line pt-3"
      >
        <h3 className="w-full text-xs font-semibold uppercase text-ap-muted">
          {t("admins.inviteHeading")}
        </h3>
        <label className="flex flex-col text-xs">
          {t("admins.invite.email")}
          <input
            type="email"
            required
            value={invEmail}
            onChange={(e) => setInvEmail(e.target.value)}
            className="mt-1 rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
          />
        </label>
        <label className="flex flex-col text-xs">
          {t("admins.invite.fullName")}
          <input
            required
            value={invName}
            onChange={(e) => setInvName(e.target.value)}
            className="mt-1 rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
          />
        </label>
        <button
          type="submit"
          disabled={inviteMut.isPending}
          className="rounded-md bg-ap-primary px-3 py-1 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {inviteMut.isPending ? t("admins.invite.submitting") : t("admins.invite.submit")}
        </button>
        {inviteMut.error ? (
          <p className="basis-full text-xs text-ap-crit">
            {(inviteMut.error as Error).message}
          </p>
        ) : null}
        {inviteMut.data ? (
          <p className="basis-full text-xs text-ap-muted">
            {inviteMut.data.keycloak_provisioning === "succeeded"
              ? t("admins.invite.kcOk")
              : t("admins.invite.kcPending")}
          </p>
        ) : null}
      </form>

      {/* Transfer-ownership modal */}
      {transferring && owner ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-xl bg-ap-panel p-4 shadow-lg">
            <h3 className="text-sm font-semibold text-ap-ink">
              {t("admins.transfer.title")}
            </h3>
            <p className="mt-2 text-xs text-ap-muted">
              {t("admins.transfer.body", {
                from: owner.full_name ?? owner.email,
                to: transferring.full_name ?? transferring.email,
              })}
            </p>
            <p className="mt-2 text-xs text-ap-warn">
              {t("admins.transfer.confirmHint", { slug: tenantSlug })}
            </p>
            <input
              autoFocus
              value={transferConfirm}
              onChange={(e) => setTransferConfirm(e.target.value)}
              className="mt-2 w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setTransferring(null);
                  setTransferConfirm("");
                }}
                className="rounded-md border border-ap-line bg-ap-panel px-3 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
              >
                {t("admins.transfer.cancel")}
              </button>
              <button
                type="button"
                disabled={
                  transferConfirm !== tenantSlug || transferMut.isPending
                }
                onClick={() => {
                  transferMut.mutate(
                    {
                      newOwnerUserId: transferring.user_id,
                      fromUserId: owner.user_id,
                    },
                    {
                      onSuccess: () => {
                        setTransferring(null);
                        setTransferConfirm("");
                      },
                    },
                  );
                }}
                className="rounded-md bg-ap-warn px-3 py-1 text-xs font-medium text-white hover:bg-ap-warn/90 disabled:opacity-60"
              >
                {transferMut.isPending
                  ? t("admins.transfer.submitting")
                  : t("admins.transfer.submit")}
              </button>
            </div>
            {transferMut.error ? (
              <p className="mt-2 text-xs text-ap-crit">
                {(transferMut.error as Error).message}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}
