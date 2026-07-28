import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { listFarms } from "@/api/farms";
import type { WorkerRole } from "@/api/resources";
import { listTenantUsers, type TenantUser } from "@/api/users";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { useCapability } from "@/rbac/useCapability";
import { useCreateResource, useResources, useUpdateResource } from "@/queries/resources";

const ROLES: WorkerRole[] = ["FarmManager", "Agronomist", "FieldOperator", "Scout", "FieldWorker"];

/** Resolve a linked membership_id to a member's display name, or null. */
function memberName(members: TenantUser[], id: string | null | undefined): string | null {
  if (!id) return null;
  return members.find((m) => m.membership_id === id)?.full_name ?? null;
}

/** Optional "link this worker to a login member" dropdown (U-3). */
function MemberSelect({
  members,
  value,
  onChange,
}: {
  members: TenantUser[];
  value: string | null;
  onChange: (id: string | null) => void;
}): ReactNode {
  const { t } = useTranslation("resources");
  return (
    <select
      className="rounded border border-ap-line px-2 py-1"
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">{t("link.none")}</option>
      {members.map((m) => (
        <option key={m.membership_id} value={m.membership_id}>
          {m.full_name || m.email}
        </option>
      ))}
    </select>
  );
}

/**
 * /settings/workers — per-farm catalog of people who can be assigned to
 * a plan activity. Master file for the board's quick-add picker (PR-4).
 */
export function ResourcesWorkersPage(): ReactNode {
  const { t } = useTranslation("resources");
  const canManage = useCapability("resource.manage");
  // U-3: link picker needs the tenant member roster. Gate the fetch on
  // user.read so a manager without it doesn't trigger a 403 — they just
  // see no linking option.
  const canReadUsers = useCapability("user.read");

  const farmsQ = useQuery({
    queryKey: ["farms", "list-tenant"],
    queryFn: () => listFarms({ limit: 100 }),
    staleTime: 60_000,
  });

  const membersQ = useQuery({
    queryKey: ["tenant_users", "list"],
    queryFn: listTenantUsers,
    enabled: canReadUsers,
    staleTime: 30_000,
  });
  const members = membersQ.data ?? [];
  const [farmId, setFarmId] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);

  // Default to the first farm once farms load. Must be computed before
  // useResources so the list query targets the same farm the rest of
  // the page (dropdown, create button) is acting on — otherwise creating
  // a worker invalidates a query the page never opened, and the new
  // row never appears.
  const effectiveFarmId = useMemo(
    () => farmId ?? farmsQ.data?.items[0]?.id ?? null,
    [farmId, farmsQ.data],
  );

  const workersQ = useResources(effectiveFarmId, {
    kind: "worker",
    include_archived: includeArchived,
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("workers.title")} subtitle={t("workers.subtitle")} />

      <div className="flex items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-ap-muted">{t("pickFarm")}</span>
          <select
            className="rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
            value={effectiveFarmId ?? ""}
            onChange={(e) => setFarmId(e.target.value || null)}
          >
            <option value="">{t("noFarm")}</option>
            {(farmsQ.data?.items ?? []).map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeArchived}
            onChange={(e) => setIncludeArchived(e.target.checked)}
          />
          <span>{t("showArchived")}</span>
        </label>
      </div>

      {!effectiveFarmId ? (
        <p className="text-sm text-ap-muted">{t("workers.empty")}</p>
      ) : workersQ.isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : workersQ.isError ? (
        <p className="text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : (
        <WorkersTable
          rows={workersQ.data ?? []}
          farmId={effectiveFarmId}
          canManage={canManage}
          members={members}
          canLink={canReadUsers}
        />
      )}
    </div>
  );
}

interface WorkersTableProps {
  rows: Awaited<ReturnType<typeof import("@/api/resources").listResources>>;
  farmId: string;
  canManage: boolean;
  members: TenantUser[];
  canLink: boolean;
}

function WorkersTable({ rows, farmId, canManage, members, canLink }: WorkersTableProps): ReactNode {
  const { t } = useTranslation("resources");
  const [adding, setAdding] = useState(false);
  // Columns: name, role, member?, phone, status (+ actions if canManage).
  const cols = (canLink ? 5 : 4) + (canManage ? 1 : 0);

  return (
    <div className="rounded-xl border border-ap-line bg-ap-panel">
      <div className="flex items-center justify-between border-b border-ap-line p-3">
        <h2 className="text-sm font-semibold text-ap-ink">{t("workers.heading")}</h2>
        {canManage ? (
          <button
            type="button"
            className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary-700"
            onClick={() => setAdding(true)}
          >
            {t("workers.add")}
          </button>
        ) : null}
      </div>
      <table className="w-full text-sm">
        <thead className="bg-ap-bg/50 text-xs uppercase tracking-wider text-ap-muted">
          <tr>
            <th className="px-3 py-2 text-start">{t("col.name")}</th>
            <th className="px-3 py-2 text-start">{t("col.role")}</th>
            {canLink ? <th className="px-3 py-2 text-start">{t("col.member")}</th> : null}
            <th className="px-3 py-2 text-start">{t("col.phone")}</th>
            <th className="px-3 py-2 text-start">{t("col.status")}</th>
            {canManage ? <th className="w-32" /> : null}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && !adding ? (
            <tr>
              <td colSpan={cols} className="px-3 py-6 text-center text-ap-muted">
                {t("workers.emptyList")}
              </td>
            </tr>
          ) : null}
          {rows.map((r) => (
            <WorkerRow
              key={r.id}
              row={r}
              farmId={farmId}
              canManage={canManage}
              members={members}
              canLink={canLink}
            />
          ))}
          {adding ? (
            <AddWorkerRow
              farmId={farmId}
              members={members}
              canLink={canLink}
              onDone={() => setAdding(false)}
            />
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

interface WorkerRowProps {
  row: Awaited<ReturnType<typeof import("@/api/resources").listResources>>[number];
  farmId: string;
  canManage: boolean;
  members: TenantUser[];
  canLink: boolean;
}

function WorkerRow({ row, farmId, canManage, members, canLink }: WorkerRowProps): ReactNode {
  const { t } = useTranslation("resources");
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(row.name);
  const [role, setRole] = useState<WorkerRole>(row.role ?? "FieldWorker");
  const [phone, setPhone] = useState(row.phone ?? "");
  const [membershipId, setMembershipId] = useState<string | null>(row.membership_id);
  const update = useUpdateResource(farmId);

  if (editing) {
    return (
      <tr className="border-t border-ap-line">
        <td className="px-3 py-2">
          <input
            className="w-full rounded border border-ap-line px-2 py-1"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </td>
        <td className="px-3 py-2">
          <select
            className="rounded border border-ap-line px-2 py-1"
            value={role}
            onChange={(e) => setRole(e.target.value as WorkerRole)}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {t(`role.${r}`)}
              </option>
            ))}
          </select>
        </td>
        {canLink ? (
          <td className="px-3 py-2">
            <MemberSelect members={members} value={membershipId} onChange={setMembershipId} />
          </td>
        ) : null}
        <td className="px-3 py-2">
          <input
            className="w-full rounded border border-ap-line px-2 py-1"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </td>
        <td className="px-3 py-2 text-ap-muted">
          {row.archived_at ? t("status.archived") : t("status.active")}
        </td>
        <td className="px-3 py-2 text-end">
          <button
            type="button"
            disabled={update.isPending}
            className="me-2 text-sm text-ap-primary hover:underline"
            onClick={() =>
              update.mutate(
                {
                  resourceId: row.id,
                  payload: { name, role, phone: phone || null, membership_id: membershipId },
                },
                { onSuccess: () => setEditing(false) },
              )
            }
          >
            {t("action.save")}
          </button>
          <button
            type="button"
            className="text-sm text-ap-muted hover:underline"
            onClick={() => setEditing(false)}
          >
            {t("action.cancel")}
          </button>
        </td>
      </tr>
    );
  }

  return (
    <tr className="border-t border-ap-line">
      <td className="px-3 py-2">{row.name}</td>
      <td className="px-3 py-2 text-ap-muted">{t(`role.${row.role}`)}</td>
      {canLink ? (
        <td className="px-3 py-2 text-ap-muted">{memberName(members, row.membership_id) ?? "—"}</td>
      ) : null}
      <td className="px-3 py-2 text-ap-muted">{row.phone ?? "—"}</td>
      <td className="px-3 py-2 text-ap-muted">
        {row.archived_at ? t("status.archived") : t("status.active")}
      </td>
      {canManage ? (
        <td className="px-3 py-2 text-end">
          <button
            type="button"
            className="me-3 text-sm text-ap-primary hover:underline"
            onClick={() => setEditing(true)}
          >
            {t("action.edit")}
          </button>
          <button
            type="button"
            disabled={update.isPending}
            className="text-sm text-ap-muted hover:underline"
            onClick={() =>
              update.mutate({
                resourceId: row.id,
                payload: { archive: !row.archived_at },
              })
            }
          >
            {row.archived_at ? t("action.restore") : t("action.archive")}
          </button>
        </td>
      ) : null}
    </tr>
  );
}

interface AddWorkerRowProps {
  farmId: string;
  members: TenantUser[];
  canLink: boolean;
  onDone: () => void;
}

function AddWorkerRow({ farmId, members, canLink, onDone }: AddWorkerRowProps): ReactNode {
  const { t } = useTranslation("resources");
  const [name, setName] = useState("");
  const [role, setRole] = useState<WorkerRole>("FieldWorker");
  const [phone, setPhone] = useState("");
  const [membershipId, setMembershipId] = useState<string | null>(null);
  const create = useCreateResource(farmId);

  return (
    <tr className="border-t border-ap-line bg-ap-bg/30">
      <td className="px-3 py-2">
        <input
          className="w-full rounded border border-ap-line px-2 py-1"
          placeholder={t("workers.namePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </td>
      <td className="px-3 py-2">
        <select
          className="rounded border border-ap-line px-2 py-1"
          value={role}
          onChange={(e) => setRole(e.target.value as WorkerRole)}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {t(`role.${r}`)}
            </option>
          ))}
        </select>
      </td>
      {canLink ? (
        <td className="px-3 py-2">
          <MemberSelect members={members} value={membershipId} onChange={setMembershipId} />
        </td>
      ) : null}
      <td className="px-3 py-2">
        <input
          className="w-full rounded border border-ap-line px-2 py-1"
          placeholder={t("workers.phonePlaceholder")}
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
      </td>
      <td className="px-3 py-2 text-ap-muted">{t("status.active")}</td>
      <td className="px-3 py-2 text-end">
        <button
          type="button"
          disabled={!name.trim() || create.isPending}
          className="me-2 text-sm text-ap-primary hover:underline disabled:opacity-50"
          onClick={() =>
            create.mutate(
              {
                kind: "worker",
                name: name.trim(),
                role,
                phone: phone.trim() || null,
                membership_id: membershipId,
              },
              { onSuccess: onDone },
            )
          }
        >
          {t("action.create")}
        </button>
        <button type="button" className="text-sm text-ap-muted hover:underline" onClick={onDone}>
          {t("action.cancel")}
        </button>
        {create.isError ? <p className="mt-1 text-xs text-ap-crit">{t("createFailed")}</p> : null}
      </td>
    </tr>
  );
}
