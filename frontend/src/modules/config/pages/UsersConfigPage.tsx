import { formatDistanceToNow, parseISO } from "date-fns";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import type { TenantUser, UserUpdatePayload } from "@/api/users";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useCapability } from "@/rbac/useCapability";
import {
  useDeleteTenantUser,
  useInviteTenantUser,
  useReactivateTenantUser,
  useSuspendTenantUser,
  useTenantUsers,
  useUpdateTenantUser,
} from "@/queries/users";

const TENANT_ROLES = ["TenantOwner", "TenantAdmin", "BillingAdmin", "Viewer"] as const;

export function UsersConfigPage(): ReactNode {
  const farmId = useActiveFarmId();
  const { t } = useTranslation("users");
  const canRead = useCapability("user.read");
  const canInvite = useCapability("user.invite");
  const canUpdate = useCapability("user.update");
  const canSuspend = useCapability("user.suspend");
  const canDelete = useCapability("user.delete");
  const [inviting, setInviting] = useState(false);
  const [editing, setEditing] = useState<TenantUser | null>(null);

  const { data, isLoading, isError } = useTenantUsers();
  const suspendMut = useSuspendTenantUser();
  const reactivateMut = useReactivateTenantUser();
  const deleteMut = useDeleteTenantUser();

  if (!farmId) {
    return <Navigate to="/" replace />;
  }
  if (!canRead) {
    return (
      <div className="mx-auto max-w-3xl py-12 text-center">
        <p className="text-sm text-ap-muted">
          {t("page.missingCapability", { capability: "user.read" })}
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ap-ink">{t("page.title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("page.subtitle")}</p>
        </div>
        {canInvite ? (
          <button
            type="button"
            onClick={() => setInviting(true)}
            className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90"
          >
            {t("page.newButton")}
          </button>
        ) : null}
      </header>

      {inviting ? <InviteForm onClose={() => setInviting(false)} /> : null}
      {editing ? (
        <EditForm user={editing} onClose={() => setEditing(null)} />
      ) : null}

      <div className="rounded-xl border border-ap-line bg-ap-panel">
        {isLoading ? (
          <div className="flex flex-col gap-2 p-4">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : isError ? (
          <p className="p-4 text-sm text-ap-crit">{t("page.loadFailed")}</p>
        ) : !data || data.length === 0 ? (
          <p className="p-12 text-center text-sm text-ap-muted">{t("page.empty")}</p>
        ) : (
          <table className="min-w-full text-sm">
            <thead className="bg-ap-bg/40 text-xs uppercase text-ap-muted">
              <tr>
                <th className="px-4 py-2 text-start">{t("table.name")}</th>
                <th className="px-4 py-2 text-start">{t("table.email")}</th>
                <th className="px-4 py-2 text-start">{t("table.tenantRoles")}</th>
                <th className="px-4 py-2 text-start">{t("table.status")}</th>
                <th className="px-4 py-2 text-start">{t("table.lastLogin")}</th>
                <th className="px-4 py-2 text-end">{t("table.actions")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ap-line">
              {data.map((user) => (
                <UserRow
                  key={user.id}
                  user={user}
                  canUpdate={canUpdate}
                  canSuspend={canSuspend}
                  canDelete={canDelete}
                  onEdit={() => setEditing(user)}
                  onSuspend={() => suspendMut.mutate(user.id)}
                  onReactivate={() => reactivateMut.mutate(user.id)}
                  onDelete={() => deleteMut.mutate(user.id)}
                />
              ))}
            </tbody>
          </table>
        )}
        {(suspendMut.isError || reactivateMut.isError || deleteMut.isError) ? (
          <p className="border-t border-ap-line p-3 text-xs text-ap-crit">
            {(suspendMut.error || reactivateMut.error || deleteMut.error)?.message}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function UserRow({
  user,
  canUpdate,
  canSuspend,
  canDelete,
  onEdit,
  onSuspend,
  onReactivate,
  onDelete,
}: {
  user: TenantUser;
  canUpdate: boolean;
  canSuspend: boolean;
  canDelete: boolean;
  onEdit: () => void;
  onSuspend: () => void;
  onReactivate: () => void;
  onDelete: () => void;
}): ReactNode {
  const { t } = useTranslation("users");
  const dateLocale = useDateLocale();
  const isPending = user.keycloak_subject?.startsWith("pending::") ?? false;
  const memberStatus = user.membership_status;
  return (
    <tr>
      <td className="px-4 py-2 text-ap-ink">{user.full_name}</td>
      <td className="px-4 py-2 font-mono text-xs text-ap-muted">{user.email}</td>
      <td className="px-4 py-2">
        <div className="flex flex-wrap gap-1">
          {user.tenant_roles.map((role) => (
            <Pill key={role} kind="info">
              {role}
            </Pill>
          ))}
        </div>
      </td>
      <td className="px-4 py-2">
        <div className="flex flex-wrap items-center gap-1">
          <Pill
            kind={
              memberStatus === "active"
                ? "ok"
                : memberStatus === "suspended"
                  ? "crit"
                  : "neutral"
            }
          >
            {t(`row.${memberStatus === "active" ? "active" : memberStatus === "suspended" ? "suspended" : "archived"}`)}
          </Pill>
          {isPending ? (
            <Pill kind="warn">{t("row.pendingProvisioning")}</Pill>
          ) : null}
        </div>
      </td>
      <td className="px-4 py-2 text-xs text-ap-muted">
        {user.last_login_at
          ? formatDistanceToNow(parseISO(user.last_login_at), {
              addSuffix: true,
              locale: dateLocale,
            })
          : t("row.never")}
      </td>
      <td className="px-4 py-2">
        <div className="flex flex-wrap justify-end gap-1">
          {canUpdate ? (
            <button
              type="button"
              onClick={onEdit}
              className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
            >
              {t("row.edit")}
            </button>
          ) : null}
          {canSuspend ? (
            memberStatus === "suspended" ? (
              <button
                type="button"
                onClick={onReactivate}
                className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
              >
                {t("row.reactivate")}
              </button>
            ) : (
              <button
                type="button"
                onClick={onSuspend}
                className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
              >
                {t("row.suspend")}
              </button>
            )
          ) : null}
          {canDelete ? (
            <button
              type="button"
              onClick={onDelete}
              className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
            >
              {t("row.delete")}
            </button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}

function InviteForm({ onClose }: { onClose: () => void }): ReactNode {
  const { t } = useTranslation("users");
  const invite = useInviteTenantUser();
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [tenantRole, setTenantRole] = useState<string>("Viewer");
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const submit = (event: React.FormEvent): void => {
    event.preventDefault();
    setSuccessMsg(null);
    invite.mutate(
      {
        email: email.trim(),
        full_name: fullName.trim(),
        phone: phone.trim() || null,
        tenant_role: tenantRole,
      },
      {
        onSuccess: (res) => {
          setSuccessMsg(
            res.keycloak_provisioning === "succeeded"
              ? t("invite.successProvisioned")
              : t("invite.successPending"),
          );
          setEmail("");
          setFullName("");
          setPhone("");
        },
      },
    );
  };

  return (
    <form
      onSubmit={submit}
      className="rounded-xl border border-ap-primary/40 bg-ap-panel p-4 shadow-sm"
    >
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ap-ink">{t("invite.title")}</h2>
        <button
          type="button"
          onClick={onClose}
          className="text-xs font-medium text-ap-muted hover:text-ap-ink"
        >
          {t("invite.cancel")}
        </button>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField label={t("invite.email")}>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={inputCls}
          />
        </FormField>
        <FormField label={t("invite.fullName")}>
          <input
            required
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className={inputCls}
          />
        </FormField>
        <FormField label={t("invite.phone")}>
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            className={inputCls}
          />
        </FormField>
        <FormField label={t("invite.tenantRole")}>
          <select
            value={tenantRole}
            onChange={(e) => setTenantRole(e.target.value)}
            className={inputCls}
          >
            {TENANT_ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </FormField>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        {successMsg ? (
          <span className="text-xs text-ap-ok">{successMsg}</span>
        ) : null}
        {invite.isError ? (
          <span className="text-xs text-ap-crit">
            {(invite.error as Error)?.message ?? t("invite.saveFailed")}
          </span>
        ) : null}
        <button
          type="submit"
          disabled={invite.isPending}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {invite.isPending ? t("invite.saving") : t("invite.save")}
        </button>
      </div>
    </form>
  );
}

function EditForm({
  user,
  onClose,
}: {
  user: TenantUser;
  onClose: () => void;
}): ReactNode {
  const { t } = useTranslation("users");
  const update = useUpdateTenantUser();
  const [fullName, setFullName] = useState(user.full_name);
  const [phone, setPhone] = useState(user.phone ?? "");
  const [language, setLanguage] = useState(user.preferences?.language ?? "en");

  const submit = (event: React.FormEvent): void => {
    event.preventDefault();
    const payload: UserUpdatePayload = {
      full_name: fullName,
      phone: phone || null,
      preferences: { language },
    };
    update.mutate({ userId: user.id, payload }, { onSuccess: onClose });
  };

  return (
    <form
      onSubmit={submit}
      className="rounded-xl border border-ap-primary/40 bg-ap-panel p-4 shadow-sm"
    >
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ap-ink">{t("edit.title")}</h2>
        <button
          type="button"
          onClick={onClose}
          className="text-xs font-medium text-ap-muted hover:text-ap-ink"
        >
          {t("edit.cancel")}
        </button>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField label={t("edit.fullName")}>
          <input
            required
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className={inputCls}
          />
        </FormField>
        <FormField label={t("edit.phone")}>
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            className={inputCls}
          />
        </FormField>
        <FormField label={t("edit.language")}>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className={inputCls}
          >
            <option value="en">English</option>
            <option value="ar">العربية</option>
          </select>
        </FormField>
      </div>
      <div className="mt-3 flex items-center justify-end gap-2">
        {update.isError ? (
          <span className="text-xs text-ap-crit">
            {(update.error as Error)?.message ?? t("edit.saveFailed")}
          </span>
        ) : null}
        <button
          type="submit"
          disabled={update.isPending}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {update.isPending ? t("edit.saving") : t("edit.save")}
        </button>
      </div>
    </form>
  );
}

const inputCls =
  "w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm text-ap-ink shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary";

function FormField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}): ReactNode {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ap-muted">{label}</span>
      {children}
    </label>
  );
}
