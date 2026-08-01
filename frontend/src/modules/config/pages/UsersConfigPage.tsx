import { formatDistanceToNow, parseISO } from "date-fns";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { TenantUser, UserUpdatePayload } from "@/api/users";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Page } from "@/components/Page";
import { PageHeader } from "@/components/PageHeader";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { queryState } from "@/components/asyncState";
import { Pill } from "@/components/Pill";
import { useDateLocale } from "@/hooks/useDateLocale";
import { useCapability } from "@/rbac/useCapability";
import {
  useDeleteTenantUser,
  useInviteTenantUser,
  useReactivateTenantUser,
  useResendTenantUserInvite,
  useSuspendTenantUser,
  useTenantUsers,
  useUpdateTenantUser,
} from "@/queries/users";

const TENANT_ROLES = ["TenantOwner", "TenantAdmin", "BillingAdmin", "Viewer"] as const;

/** A first-login credential surfaced after invite/resend. `password` is
 * set only when SMTP was unavailable and a temp credential was minted. */
interface Credential {
  email: string;
  emailSent: boolean;
  password: string | null;
}

export function UsersConfigPage(): ReactNode {
  const { t } = useTranslation("users");
  const canRead = useCapability("user.read");
  const canInvite = useCapability("user.invite");
  const canUpdate = useCapability("user.update");
  const canSuspend = useCapability("user.suspend");
  const canDelete = useCapability("user.delete");
  const [inviting, setInviting] = useState(false);
  const [editing, setEditing] = useState<TenantUser | null>(null);
  const [credential, setCredential] = useState<Credential | null>(null);

  const users = useTenantUsers();
  const suspendMut = useSuspendTenantUser();
  const reactivateMut = useReactivateTenantUser();
  const deleteMut = useDeleteTenantUser();
  const resendMut = useResendTenantUserInvite();

  if (!canRead) {
    return <EmptyState message={t("page.missingCapability", { capability: "user.read" })} />;
  }

  return (
    // Four columns do not fill max-w-6xl — see decision 5's escape hatch.
    <Page width="standard">
      <PageHeader
        title={t("page.title")}
        subtitle={t("page.subtitle")}
        actions={
          canInvite ? (
            <Button onClick={() => setInviting(true)}>{t("page.newButton")}</Button>
          ) : null
        }
      />

      {inviting ? (
        <InviteForm onClose={() => setInviting(false)} onCredential={setCredential} />
      ) : null}
      {editing ? <EditForm user={editing} onClose={() => setEditing(null)} /> : null}
      {credential ? (
        <CredentialBanner credential={credential} onDismiss={() => setCredential(null)} />
      ) : null}

      <AsyncBoundary
        state={queryState(users)}
        skeleton="lines"
        errorMessage={t("page.loadFailed")}
        empty={
          <Card noPadding>
            <EmptyState
              message={t("page.empty")}
              action={
                canInvite ? (
                  <Button onClick={() => setInviting(true)}>{t("page.newButton")}</Button>
                ) : null
              }
            />
          </Card>
        }
      >
        {(rows) => (
          <Table>
            <Thead>
              <tr>
                <Th>{t("table.name")}</Th>
                <Th>{t("table.email")}</Th>
                <Th>{t("table.tenantRoles")}</Th>
                <Th>{t("table.status")}</Th>
                <Th>{t("table.lastLogin")}</Th>
                <Th className="text-end">{t("table.actions")}</Th>
              </tr>
            </Thead>
            <Tbody>
              {rows.map((user) => (
                <UserRow
                  key={user.id}
                  user={user}
                  canUpdate={canUpdate}
                  canSuspend={canSuspend}
                  canDelete={canDelete}
                  canInvite={canInvite}
                  isResending={resendMut.isPending && resendMut.variables === user.id}
                  onEdit={() => setEditing(user)}
                  onSuspend={() => suspendMut.mutate(user.id)}
                  onReactivate={() => reactivateMut.mutate(user.id)}
                  onDelete={() => deleteMut.mutate(user.id)}
                  onResend={() =>
                    resendMut.mutate(user.id, {
                      onSuccess: (res) =>
                        setCredential({
                          email: user.email,
                          emailSent: res.keycloak_email_sent,
                          password: res.temporary_password,
                        }),
                    })
                  }
                />
              ))}
            </Tbody>
          </Table>
        )}
      </AsyncBoundary>

      {suspendMut.isError || reactivateMut.isError || deleteMut.isError || resendMut.isError ? (
        <ErrorState
          message={
            (suspendMut.error || reactivateMut.error || deleteMut.error || resendMut.error)?.message
          }
        />
      ) : null}
    </Page>
  );
}

function UserRow({
  user,
  canUpdate,
  canSuspend,
  canDelete,
  canInvite,
  isResending,
  onEdit,
  onSuspend,
  onReactivate,
  onDelete,
  onResend,
}: {
  user: TenantUser;
  canUpdate: boolean;
  canSuspend: boolean;
  canDelete: boolean;
  canInvite: boolean;
  isResending: boolean;
  onEdit: () => void;
  onSuspend: () => void;
  onReactivate: () => void;
  onDelete: () => void;
  onResend: () => void;
}): ReactNode {
  const { t } = useTranslation("users");
  const dateLocale = useDateLocale();
  const isPending = user.keycloak_subject?.startsWith("pending::") ?? false;
  const memberStatus = user.membership_status;
  return (
    <Tr>
      <Td className="text-ap-ink">{user.full_name}</Td>
      <Td className="font-mono text-xs text-ap-muted">{user.email}</Td>
      <Td>
        <div className="flex flex-wrap gap-1">
          {user.tenant_roles.map((role) => (
            <Pill key={role} kind="info">
              {role}
            </Pill>
          ))}
        </div>
      </Td>
      <Td>
        <div className="flex flex-wrap items-center gap-1">
          <Pill
            kind={
              memberStatus === "active" ? "ok" : memberStatus === "suspended" ? "crit" : "neutral"
            }
          >
            {t(
              `row.${memberStatus === "active" ? "active" : memberStatus === "suspended" ? "suspended" : "archived"}`,
            )}
          </Pill>
          {isPending ? <Pill kind="warn">{t("row.pendingProvisioning")}</Pill> : null}
        </div>
      </Td>
      <Td className="text-xs text-ap-muted">
        {user.last_login_at
          ? formatDistanceToNow(parseISO(user.last_login_at), {
              addSuffix: true,
              locale: dateLocale,
            })
          : t("row.never")}
      </Td>
      <Td>
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
          {canInvite && !isPending ? (
            <button
              type="button"
              onClick={onResend}
              disabled={isResending}
              className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
            >
              {isResending ? t("row.resending") : t("row.resend")}
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
      </Td>
    </Tr>
  );
}

function InviteForm({
  onClose,
  onCredential,
}: {
  onClose: () => void;
  onCredential: (credential: Credential) => void;
}): ReactNode {
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
    const invitedEmail = email.trim();
    invite.mutate(
      {
        email: invitedEmail,
        full_name: fullName.trim(),
        phone: phone.trim() || null,
        tenant_role: tenantRole,
      },
      {
        onSuccess: (res) => {
          if (res.keycloak_provisioning === "succeeded") {
            // Surface the credential banner (email-sent or temp password).
            onCredential({
              email: invitedEmail,
              emailSent: res.keycloak_email_sent,
              password: res.temporary_password,
            });
            setSuccessMsg(null);
            onClose();
          } else {
            setSuccessMsg(t("invite.successPending"));
          }
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
          <input value={phone} onChange={(e) => setPhone(e.target.value)} className={inputCls} />
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
        {successMsg ? <span className="text-xs text-ap-ok">{successMsg}</span> : null}
        {invite.isError ? (
          <span className="text-xs text-ap-crit">
            {invite.error?.message ?? t("invite.saveFailed")}
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

function EditForm({ user, onClose }: { user: TenantUser; onClose: () => void }): ReactNode {
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
          <input value={phone} onChange={(e) => setPhone(e.target.value)} className={inputCls} />
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
            {update.error?.message ?? t("edit.saveFailed")}
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

function CredentialBanner({
  credential,
  onDismiss,
}: {
  credential: Credential;
  onDismiss: () => void;
}): ReactNode {
  const { t } = useTranslation("users");
  const [copied, setCopied] = useState(false);

  const copy = (): void => {
    if (!credential.password) return;
    void navigator.clipboard.writeText(credential.password).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    });
  };

  if (credential.emailSent) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-xl border border-ap-ok/40 bg-ap-ok/10 p-3 text-sm text-ap-ink">
        <span>{t("credential.emailSent", { email: credential.email })}</span>
        <button
          type="button"
          onClick={onDismiss}
          className="text-xs font-medium text-ap-muted hover:text-ap-ink"
        >
          {t("credential.dismiss")}
        </button>
      </div>
    );
  }

  if (!credential.password) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-xl border border-ap-warn/40 bg-ap-warn/10 p-3 text-sm text-ap-ink">
        <span>{t("credential.pending")}</span>
        <button
          type="button"
          onClick={onDismiss}
          className="text-xs font-medium text-ap-muted hover:text-ap-ink"
        >
          {t("credential.dismiss")}
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-ap-primary/40 bg-ap-primary/5 p-4 text-sm">
      <div className="mb-2 flex items-start justify-between gap-3">
        <h2 className="font-semibold text-ap-ink">
          {t("credential.tempTitle", { email: credential.email })}
        </h2>
        <button
          type="button"
          onClick={onDismiss}
          className="text-xs font-medium text-ap-muted hover:text-ap-ink"
        >
          {t("credential.dismiss")}
        </button>
      </div>
      <p className="mb-3 text-xs text-ap-muted">{t("credential.tempHint")}</p>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-ap-muted">{t("credential.tempPassword")}</span>
        <code className="rounded-md border border-ap-line bg-white px-2 py-1 font-mono text-sm text-ap-ink">
          {credential.password}
        </code>
        <button
          type="button"
          onClick={copy}
          className="rounded-md bg-ap-primary px-2 py-1 text-xs font-medium text-white hover:bg-ap-primary/90"
        >
          {copied ? t("credential.copied") : t("credential.copy")}
        </button>
      </div>
    </div>
  );
}

const inputCls =
  "w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm text-ap-ink shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary";

function FormField({ label, children }: { label: string; children: ReactNode }): ReactNode {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ap-muted">{label}</span>
      {children}
    </label>
  );
}
