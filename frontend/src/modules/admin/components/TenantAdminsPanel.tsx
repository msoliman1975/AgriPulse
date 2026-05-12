import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import type { TenantAdminRow } from "@/api/platformAdmins";
import {
  useAssignFirstOwner,
  useTenantAdmins,
  useTransferOwnership,
} from "@/queries/platformAdmins";

interface Props {
  tenantId: string;
  tenantSlug: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Tenant Owner panel — Platform's only user-mgmt touchpoint after
 * tenant creation per the persona-separation rule (decision Q3:
 * "Platform = define and assign TenantOwners; Agri.Pulse = full
 * self-service" for everyone else).
 *
 * What lives here:
 *   - Read-only display of the current TenantOwner.
 *   - Transfer-ownership flow (slug-confirmation modal — same posture
 *     as the purge confirmation).
 *
 *
 * What lives here:
 *   - Read-only display of the current TenantOwner.
 *   - Transfer-ownership flow (slug-confirmation modal — same posture
 *     as the purge confirmation).
 *
 * What used to live here (PR-Reorg4 removal): the Invite TenantAdmin
 * form + per-row "Revoke admin" actions. Those moved to Agri.Pulse —
 * TenantOwner manages them via /settings/users.
 */
export function TenantAdminsPanel({ tenantId, tenantSlug }: Props): ReactNode {
  const { t } = useTranslation("admin");
  const adminsQ = useTenantAdmins(tenantId);
  const transferMut = useTransferOwnership(tenantId);
  const [openTransfer, setOpenTransfer] = useState(false);
  const [newOwnerEmail, setNewOwnerEmail] = useState("");
  const [confirmSlug, setConfirmSlug] = useState("");

  const owner = adminsQ.data?.find((r) => r.role === "TenantOwner") ?? null;
  const candidates =
    (adminsQ.data ?? []).filter((r) => r.role !== "TenantOwner") ?? [];
  const newOwner = candidates.find((c) => c.email === newOwnerEmail) ?? null;

  return (
    <section className="rounded-xl border border-ap-line bg-ap-panel p-4">
      <h2 className="text-sm font-semibold text-ap-ink">
        {t("owner.title")}
      </h2>
      <p className="mt-1 text-xs text-ap-muted">{t("owner.subtitle")}</p>

      {adminsQ.isLoading ? (
        <Skeleton className="mt-3 h-12 w-full" />
      ) : adminsQ.isError ? (
        <p className="mt-3 text-sm text-ap-crit">{t("admins.loadFailed")}</p>
      ) : owner == null ? (
        <>
          <p className="mt-3 text-sm text-ap-warn">{t("owner.none")}</p>
          <AssignFirstOwnerForm
            tenantId={tenantId}
            existingMembers={adminsQ.data ?? []}
          />
        </>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Pill kind="warn">TenantOwner</Pill>
          <span className="text-sm text-ap-ink">
            {owner.full_name ? `${owner.full_name} ` : ""}
            <span className="text-ap-muted">&lt;{owner.email}&gt;</span>
          </span>
          <button
            type="button"
            onClick={() => setOpenTransfer(true)}
            className="ms-auto rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
          >
            {t("owner.transferButton")}
          </button>
        </div>
      )}

      {/* Transfer-ownership modal */}
      {openTransfer && owner ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-xl bg-ap-panel p-4 shadow-lg">
            <h3 className="text-sm font-semibold text-ap-ink">
              {t("admins.transfer.title")}
            </h3>
            <p className="mt-2 text-xs text-ap-muted">
              {t("owner.transferIntro", {
                from: owner.full_name ?? owner.email,
              })}
            </p>
            <label className="mt-3 flex flex-col gap-1 text-xs">
              {t("owner.newOwnerLabel")}
              <select
                className="rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
                value={newOwnerEmail}
                onChange={(e) => setNewOwnerEmail(e.target.value)}
              >
                <option value="">{t("owner.pickNewOwner")}</option>
                {candidates.map((c) => (
                  <option key={c.user_id} value={c.email}>
                    {c.full_name ? `${c.full_name} ` : ""}
                    &lt;{c.email}&gt;
                  </option>
                ))}
              </select>
            </label>
            {candidates.length === 0 ? (
              <p className="mt-2 text-xs text-ap-warn">
                {t("owner.noCandidates")}
              </p>
            ) : null}
            <p className="mt-3 text-xs text-ap-warn">
              {t("admins.transfer.confirmHint", { slug: tenantSlug })}
            </p>
            <input
              autoFocus
              value={confirmSlug}
              onChange={(e) => setConfirmSlug(e.target.value)}
              className="mt-2 w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setOpenTransfer(false);
                  setNewOwnerEmail("");
                  setConfirmSlug("");
                }}
                className="rounded-md border border-ap-line bg-ap-panel px-3 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
              >
                {t("admins.transfer.cancel")}
              </button>
              <button
                type="button"
                disabled={
                  !newOwner || confirmSlug !== tenantSlug || transferMut.isPending
                }
                onClick={() => {
                  if (!newOwner) return;
                  transferMut.mutate(
                    {
                      newOwnerUserId: newOwner.user_id,
                      fromUserId: owner.user_id,
                    },
                    {
                      onSuccess: () => {
                        setOpenTransfer(false);
                        setNewOwnerEmail("");
                        setConfirmSlug("");
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

function AssignFirstOwnerForm({
  tenantId,
  existingMembers,
}: {
  tenantId: string;
  existingMembers: TenantAdminRow[];
}): ReactNode {
  const { t } = useTranslation("admin");
  const assignMut = useAssignFirstOwner(tenantId);
  const [mode, setMode] = useState<"invite" | "promote">(
    existingMembers.length > 0 ? "promote" : "invite",
  );
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [pickedUserId, setPickedUserId] = useState("");

  const inviteValid =
    EMAIL_RE.test(email.trim()) && fullName.trim().length > 0;
  const promoteValid = pickedUserId !== "";
  const canSubmit =
    mode === "invite" ? inviteValid : promoteValid && existingMembers.length > 0;

  function submit(): void {
    if (mode === "invite") {
      assignMut.mutate({ email: email.trim(), full_name: fullName.trim() });
    } else {
      assignMut.mutate({ user_id: pickedUserId });
    }
  }

  return (
    <div className="mt-3 rounded-md border border-ap-warn/40 bg-amber-50/50 p-3">
      <p className="text-sm text-ap-warn">{t("owner.none")}</p>
      <p className="mt-1 text-xs text-ap-muted">{t("owner.assignIntro")}</p>

      <div className="mt-3 flex gap-2 text-xs">
        <button
          type="button"
          onClick={() => setMode("invite")}
          className={`rounded-md border px-2 py-1 ${
            mode === "invite"
              ? "border-ap-primary bg-ap-primary/10 text-ap-ink"
              : "border-ap-line bg-ap-panel text-ap-muted"
          }`}
        >
          {t("owner.assignModeInvite")}
        </button>
        <button
          type="button"
          onClick={() => setMode("promote")}
          disabled={existingMembers.length === 0}
          className={`rounded-md border px-2 py-1 disabled:opacity-50 ${
            mode === "promote"
              ? "border-ap-primary bg-ap-primary/10 text-ap-ink"
              : "border-ap-line bg-ap-panel text-ap-muted"
          }`}
        >
          {t("owner.assignModePromote")}
        </button>
      </div>

      {mode === "invite" ? (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-ap-muted">{t("owner.assignEmail")}</span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
              autoComplete="email"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-ap-muted">{t("owner.assignFullName")}</span>
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
              autoComplete="name"
            />
          </label>
        </div>
      ) : (
        <div className="mt-3">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-ap-muted">{t("owner.assignPickMember")}</span>
            <select
              value={pickedUserId}
              onChange={(e) => setPickedUserId(e.target.value)}
              className="rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
            >
              <option value="">{t("owner.pickNewOwner")}</option>
              {existingMembers.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.full_name ? `${m.full_name} ` : ""}
                  &lt;{m.email}&gt; ({m.role})
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      <div className="mt-3 flex items-center justify-end gap-2">
        {assignMut.error ? (
          <p className="me-auto text-xs text-ap-crit">
            {(assignMut.error as Error).message}
          </p>
        ) : null}
        <button
          type="button"
          disabled={!canSubmit || assignMut.isPending}
          onClick={submit}
          className="rounded-md bg-ap-primary px-3 py-1 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {assignMut.isPending
            ? t("owner.assignSubmitting")
            : t("owner.assignSubmit")}
        </button>
      </div>
    </div>
  );
}
