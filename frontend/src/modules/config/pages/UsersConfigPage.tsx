import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow, parseISO } from "date-fns";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { listFarms, type Farm } from "@/api/farms";
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
  useAssignTenantUserRole,
  useDeleteTenantUser,
  useInviteTenantUser,
  useReactivateTenantUser,
  useResendTenantUserInvite,
  useSuspendTenantUser,
  useTenantUsers,
  useUpdateTenantUser,
} from "@/queries/users";
import { ASSIGNABLE_ROLES, needsFarms, roleTier } from "@/rbac/assignableRoles";

/**
 * The farms a farm-tier role can be granted on.
 *
 * Only live farms, and only the first page: a picker is not a farm browser,
 * and a tenant large enough to page here should be granting through Farm ->
 * Members instead. `hasMore` is surfaced in the UI rather than hidden, so a
 * missing farm reads as "not listed here" rather than "does not exist".
 */
function useFarmOptions(enabled: boolean) {
  return useQuery({
    queryKey: ["farms", "role-picker"] as const,
    queryFn: () => listFarms({ limit: 100 }),
    enabled,
    staleTime: 60_000,
  });
}

/** Farm id -> name, for rendering a grant the API returns as ids only. */
function useFarmNames(): Map<string, string> {
  const farms = useFarmOptions(true);
  return useMemo(() => {
    const map = new Map<string, string>();
    for (const farm of farms.data?.items ?? []) map.set(farm.id, farm.name);
    return map;
  }, [farms.data]);
}

/**
 * Role select, plus a farm picker when the chosen role needs one.
 *
 * The two tiers are stored in different tables and the server rejects a
 * mismatched pair, so the farm list appears and disappears with the role
 * rather than sitting there permanently greyed out.
 */
function RolePicker({
  role,
  farmIds,
  onRoleChange,
  onFarmIdsChange,
  idPrefix,
}: {
  role: string;
  farmIds: string[];
  onRoleChange: (role: string) => void;
  onFarmIdsChange: (farmIds: string[]) => void;
  idPrefix: string;
}): ReactNode {
  const { t } = useTranslation("users");
  const wantsFarms = needsFarms(role);
  const farms = useFarmOptions(wantsFarms);

  const toggle = (farmId: string): void => {
    onFarmIdsChange(
      farmIds.includes(farmId) ? farmIds.filter((f) => f !== farmId) : [...farmIds, farmId],
    );
  };

  return (
    <>
      {/* The hint sits outside FormField on purpose. FormField renders a
          <label> around its children, so a <p> inside it becomes part of the
          field's accessible name — a screen reader would announce the whole
          sentence as the label of the select. */}
      <div>
        <FormField label={t("invite.tenantRole")}>
          <select
            id={`${idPrefix}-role`}
            value={role}
            onChange={(e) => {
              onRoleChange(e.target.value);
              // Switching to the tenant tier must clear the farms, or the
              // request carries a pair the server refuses with a 422.
              if (!needsFarms(e.target.value)) onFarmIdsChange([]);
            }}
            className={inputCls}
          >
            {ASSIGNABLE_ROLES.map((r) => (
              <option key={r} value={r}>
                {t(`roles.${r}`)}
              </option>
            ))}
          </select>
        </FormField>
        <p className="mt-1 text-xs text-ap-muted">{t(`roleHints.${role}`)}</p>
      </div>

      {wantsFarms ? (
        <fieldset className="flex flex-col gap-1">
          <legend className="text-xs font-medium text-ap-muted">{t("invite.farms")}</legend>
          {farms.isPending ? (
            <p className="text-xs text-ap-muted">{t("invite.farmsLoading")}</p>
          ) : farms.isError ? (
            <p className="text-xs text-ap-crit">{t("invite.farmsFailed")}</p>
          ) : (farms.data?.items.length ?? 0) === 0 ? (
            <p className="text-xs text-ap-warn">{t("invite.farmsEmpty")}</p>
          ) : (
            <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-ap-line bg-ap-panel p-2">
              {(farms.data?.items ?? []).map((farm: Farm) => (
                <label
                  key={farm.id}
                  className="flex cursor-pointer items-center gap-2 text-sm text-ap-ink"
                >
                  <input
                    type="checkbox"
                    checked={farmIds.includes(farm.id)}
                    onChange={() => toggle(farm.id)}
                  />
                  <span>{farm.name}</span>
                  <span className="font-mono text-xs text-ap-muted">{farm.code}</span>
                </label>
              ))}
            </div>
          )}
          <p className="mt-1 text-xs text-ap-muted">{t("invite.farmsHint")}</p>
          {farms.data?.next_cursor ? (
            <p className="mt-1 text-xs text-ap-warn">{t("invite.farmsTruncated")}</p>
          ) : null}
        </fieldset>
      ) : null}
    </>
  );
}

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
  const farmNames = useFarmNames();
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
      {editing ? <EditPanel user={editing} onClose={() => setEditing(null)} /> : null}
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
                  farmNames={farmNames}
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
  farmNames,
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
  farmNames: Map<string, string>;
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
              {t(`roles.${role}`, { defaultValue: role })}
            </Pill>
          ))}
          {/* A farm-tier member has no tenant role at all, so without these
              the column is empty and reads as "no access". */}
          {user.farm_roles.map((grant) => (
            <Pill key={`${grant.farm_id}:${grant.role}`} kind="neutral">
              {t("row.farmRole", {
                role: t(`roles.${grant.role}`, { defaultValue: grant.role }),
                farm: farmNames.get(grant.farm_id) ?? t("row.unknownFarm"),
              })}
            </Pill>
          ))}
          {user.tenant_roles.length === 0 && user.farm_roles.length === 0 ? (
            <Pill kind="warn">{t("row.noRole")}</Pill>
          ) : null}
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
  // TenantAdmin, not Viewer. The old default put every invite on the tier
  // that grants the least, and a tenant-wide Viewer granted nothing at all.
  // A default that needs a farm chosen would also make the form invalid on
  // open, which is a worse first impression than a role that has to be
  // narrowed down.
  const [role, setRole] = useState<string>("TenantAdmin");
  const [farmIds, setFarmIds] = useState<string[]>([]);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const missingFarms = needsFarms(role) && farmIds.length === 0;

  const submit = (event: React.FormEvent): void => {
    event.preventDefault();
    setSuccessMsg(null);
    const invitedEmail = email.trim();
    invite.mutate(
      {
        email: invitedEmail,
        full_name: fullName.trim(),
        phone: phone.trim() || null,
        role,
        farm_ids: needsFarms(role) ? farmIds : [],
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
          setFarmIds([]);
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
        <RolePicker
          role={role}
          farmIds={farmIds}
          onRoleChange={setRole}
          onFarmIdsChange={setFarmIds}
          idPrefix="invite"
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        {successMsg ? <span className="text-xs text-ap-ok">{successMsg}</span> : null}
        {invite.isError ? (
          <span className="text-xs text-ap-crit">
            {invite.error?.message ?? t("invite.saveFailed")}
          </span>
        ) : null}
        {missingFarms ? (
          <span className="text-xs text-ap-warn">{t("invite.farmsRequired")}</span>
        ) : null}
        <button
          type="submit"
          disabled={invite.isPending || missingFarms}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {invite.isPending ? t("invite.saving") : t("invite.save")}
        </button>
      </div>
    </form>
  );
}

/**
 * Change which role a member holds.
 *
 * Separate from the profile form above because it is a different endpoint
 * (`PUT /v1/users/{id}/role`) behind a different capability
 * (`role.assign_tenant`, which only TenantOwner and TenantAdmin hold). A
 * member who may edit a name is not automatically allowed to grant
 * themselves administration.
 *
 * The server replaces rather than adds: whatever the member held is revoked
 * in the same transaction. That is stated on the form, because "set role"
 * and "add role" look identical until someone checks what happened to the
 * old one.
 */
function RoleForm({ user }: { user: TenantUser }): ReactNode {
  const { t } = useTranslation("users");
  const canAssign = useCapability("role.assign_tenant");
  const assign = useAssignTenantUserRole();

  const currentRole = user.tenant_roles[0] ?? user.farm_roles[0]?.role ?? "";
  const [role, setRole] = useState<string>(currentRole || "TenantAdmin");
  const [farmIds, setFarmIds] = useState<string[]>(user.farm_roles.map((grant) => grant.farm_id));
  const [done, setDone] = useState(false);

  if (!canAssign) return null;

  const missingFarms = needsFarms(role) && farmIds.length === 0;
  const unchanged =
    role === currentRole &&
    (roleTier(role) !== "farm" ||
      // Same farms, order-insensitive: the picker builds the list in click
      // order, so a plain join would call an unchanged grant a change.
      (farmIds.length === user.farm_roles.length &&
        farmIds.every((id) => user.farm_roles.some((g) => g.farm_id === id))));

  const submit = (event: React.FormEvent): void => {
    event.preventDefault();
    setDone(false);
    assign.mutate(
      {
        userId: user.id,
        payload: { role, farm_ids: needsFarms(role) ? farmIds : [] },
      },
      { onSuccess: () => setDone(true) },
    );
  };

  return (
    <form onSubmit={submit} className="mt-3 rounded-lg border border-ap-line bg-ap-bg p-3">
      <h3 className="mb-1 text-sm font-semibold text-ap-ink">{t("role.title")}</h3>
      <p className="mb-3 text-xs text-ap-muted">{t("role.replaceNotice")}</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <RolePicker
          role={role}
          farmIds={farmIds}
          onRoleChange={setRole}
          onFarmIdsChange={setFarmIds}
          idPrefix={`role-${user.id}`}
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        {done ? <span className="text-xs text-ap-ok">{t("role.saved")}</span> : null}
        {missingFarms ? (
          <span className="text-xs text-ap-warn">{t("invite.farmsRequired")}</span>
        ) : null}
        {assign.isError ? (
          <span className="text-xs text-ap-crit">
            {assign.error?.message ?? t("role.saveFailed")}
          </span>
        ) : null}
        <button
          type="submit"
          disabled={assign.isPending || missingFarms || unchanged}
          className="rounded-md border border-ap-primary bg-ap-panel px-3 py-1.5 text-sm font-medium text-ap-primary hover:bg-ap-primary/10 disabled:opacity-60"
        >
          {assign.isPending ? t("role.saving") : t("role.save")}
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

/**
 * The edit panel: profile above, role below.
 *
 * Two sibling forms, not one nested inside the other — nesting a `<form>`
 * inside a `<form>` is invalid HTML, and the browser drops the inner one, so
 * its submit button would silently save the profile instead of the role.
 */
function EditPanel({ user, onClose }: { user: TenantUser; onClose: () => void }): ReactNode {
  return (
    <div>
      <EditForm user={user} onClose={onClose} />
      <RoleForm user={user} />
    </div>
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
