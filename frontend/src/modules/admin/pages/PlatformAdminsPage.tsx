import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Page } from "@/components/Page";
import { Pill } from "@/components/Pill";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { queryState } from "@/components/asyncState";
import { useCapability } from "@/rbac/useCapability";
import {
  useInvitePlatformAdmin,
  usePlatformAdmins,
  useRemovePlatformAdmin,
  useSetPlatformAdminAlertEmails,
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
  const alertEmails = useSetPlatformAdminAlertEmails();

  const [openInvite, setOpenInvite] = useState(false);
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<(typeof ROLES)[number]>("PlatformAdmin");

  return (
    <Page>
      <PageHeader
        title={t("platformAdmins.title")}
        subtitle={t("platformAdmins.subtitle")}
        actions={
          canManage ? (
            <Button onClick={() => setOpenInvite(true)}>{t("platformAdmins.inviteButton")}</Button>
          ) : null
        }
      />

      <AsyncBoundary
        state={queryState(adminsQ)}
        skeleton="lines"
        errorMessage={t("platformAdmins.loadFailed")}
        empty={
          <Card noPadding>
            <EmptyState
              message={t("platformAdmins.empty")}
              action={
                canManage ? (
                  <Button onClick={() => setOpenInvite(true)}>
                    {t("platformAdmins.inviteButton")}
                  </Button>
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
                <Th>{t("platformAdmins.col.user")}</Th>
                <Th>{t("platformAdmins.col.role")}</Th>
                <Th className="w-48">{t("platformAdmins.col.alertEmails")}</Th>
                <Th className="text-end">{t("platformAdmins.col.actions")}</Th>
              </tr>
            </Thead>
            <Tbody>
              {rows.map((row) => (
                <Row
                  key={`${row.user_id}-${row.role}`}
                  row={row}
                  canManage={canManage}
                  onRemove={() => remove.mutate({ userId: row.user_id, role: row.role })}
                  removing={remove.isPending}
                  onAlertEmailsChange={(enabled) =>
                    alertEmails.mutate({ userId: row.user_id, role: row.role, enabled })
                  }
                  savingAlertEmails={alertEmails.isPending}
                />
              ))}
            </Tbody>
          </Table>
        )}
      </AsyncBoundary>

      {/* Invite modal */}
      {openInvite ? (
        <Modal
          open
          onClose={() => {
            setOpenInvite(false);
            setEmail("");
            setFullName("");
            setRole("PlatformAdmin");
          }}
          labelledBy="invite-admin-title"
          className="max-w-md p-4"
        >
          <h3 id="invite-admin-title" className="text-sm font-semibold text-ap-ink">
            {t("platformAdmins.inviteTitle")}
          </h3>
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
        </Modal>
      ) : null}
    </Page>
  );
}

function Row({
  row,
  canManage,
  onRemove,
  removing,
  onAlertEmailsChange,
  savingAlertEmails,
}: {
  row: PlatformAdminRow;
  canManage: boolean;
  onRemove: () => void;
  removing: boolean;
  onAlertEmailsChange: (enabled: boolean) => void;
  savingAlertEmails: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <Tr>
      <Td className="text-ap-ink">
        {row.full_name ? `${row.full_name} ` : ""}
        <span className="text-ap-muted">&lt;{row.email}&gt;</span>
        {row.keycloak_subject?.startsWith("pending::") ? (
          <span className="ms-2 text-[11px] text-ap-warn">{t("platformAdmins.pendingKc")}</span>
        ) : null}
      </Td>
      <Td>
        <Pill kind={row.role === "PlatformAdmin" ? "warn" : "info"}>{row.role}</Pill>
      </Td>
      <Td>
        {/* Who gets paged when the platform breaks. Disabled rather than
            hidden without the manage capability, so a support user can see
            who is on the list without being able to change it. */}
        <label className="flex items-center gap-2 text-xs text-ap-muted">
          <input
            type="checkbox"
            checked={row.receives_alert_emails}
            disabled={!canManage || savingAlertEmails}
            onChange={(e) => onAlertEmailsChange(e.target.checked)}
            className="h-4 w-4 rounded border-ap-line text-ap-primary focus:ring-ap-primary disabled:opacity-60"
          />
          {row.receives_alert_emails
            ? t("platformAdmins.alertEmails.on")
            : t("platformAdmins.alertEmails.off")}
        </label>
      </Td>
      <Td className="text-end">
        {canManage ? (
          <button
            type="button"
            onClick={onRemove}
            disabled={removing}
            className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-crit hover:bg-ap-crit-soft disabled:opacity-60"
          >
            {t("platformAdmins.removeButton")}
          </button>
        ) : null}
      </Td>
    </Tr>
  );
}
