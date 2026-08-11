import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { listFarms } from "@/api/farms";
import type { WorkerRole } from "@/api/resources";
import { listTenantUsers, type TenantUser } from "@/api/users";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { FilterChip } from "@/components/FilterChip";
import { PageHeader } from "@/components/PageHeader";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import { Toolbar } from "@/components/Toolbar";
import { queryState } from "@/components/asyncState";
import { useCapability } from "@/rbac/useCapability";
import { useCreateResource, useResources, useUpdateResource } from "@/queries/resources";
import { displayUser } from "@/lib/userDisplay";

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
          {displayUser(m, m.membership_id)}
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

      <Toolbar
        right={
          <label className="flex items-center gap-2 text-sm">
            <span className="text-ap-muted">{t("pickFarm")}</span>
            <select
              className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-sm text-ap-ink"
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
        }
        chips={
          <FilterChip active={includeArchived} onToggle={() => setIncludeArchived((v) => !v)}>
            {t("showArchived")}
          </FilterChip>
        }
      />

      {!effectiveFarmId ? (
        <EmptyState message={t("workers.empty")} action={null} />
      ) : (
        <AsyncBoundary
          state={queryState(workersQ)}
          errorMessage={t("loadFailed")}
          isEmpty={() => false}
          empty={<EmptyState message={t("workers.emptyList")} action={null} />}
        >
          {(rows) => (
            <WorkersTable
              rows={rows}
              farmId={effectiveFarmId}
              canManage={canManage}
              members={members}
              canLink={canReadUsers}
            />
          )}
        </AsyncBoundary>
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
    <Card
      noPadding
      title={t("workers.heading")}
      actions={
        canManage ? (
          <Button size="sm" onClick={() => setAdding(true)}>
            {t("workers.add")}
          </Button>
        ) : null
      }
    >
      <Table>
        <Thead>
          <Tr>
            <Th>{t("col.name")}</Th>
            <Th>{t("col.role")}</Th>
            {canLink ? <Th>{t("col.member")}</Th> : null}
            <Th>{t("col.phone")}</Th>
            <Th>{t("col.status")}</Th>
            {canManage ? <Th className="w-32" /> : null}
          </Tr>
        </Thead>
        <Tbody>
          {rows.length === 0 && !adding ? (
            <Tr>
              <Td colSpan={cols} className="p-0">
                {t("workers.emptyList")}
              </Td>
            </Tr>
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
        </Tbody>
      </Table>
    </Card>
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
      <Tr className="border-t border-ap-line">
        <Td>
          <input
            className="w-full rounded border border-ap-line px-2 py-1"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Td>
        <Td>
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
        </Td>
        {canLink ? (
          <Td>
            <MemberSelect members={members} value={membershipId} onChange={setMembershipId} />
          </Td>
        ) : null}
        <Td>
          <input
            className="w-full rounded border border-ap-line px-2 py-1"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </Td>
        <Td className="text-ap-muted">
          {row.archived_at ? t("status.archived") : t("status.active")}
        </Td>
        <Td className="text-end">
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
        </Td>
      </Tr>
    );
  }

  return (
    <Tr className="border-t border-ap-line">
      <Td>{row.name}</Td>
      <Td className="text-ap-muted">{t(`role.${row.role}`)}</Td>
      {canLink ? (
        <Td className="text-ap-muted">{memberName(members, row.membership_id) ?? "—"}</Td>
      ) : null}
      <Td className="text-ap-muted">{row.phone ?? "—"}</Td>
      <Td className="text-ap-muted">
        {row.archived_at ? t("status.archived") : t("status.active")}
      </Td>
      {canManage ? (
        <Td className="text-end">
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
        </Td>
      ) : null}
    </Tr>
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
    <Tr className="border-t border-ap-line bg-ap-bg/30">
      <Td>
        <input
          className="w-full rounded border border-ap-line px-2 py-1"
          placeholder={t("workers.namePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </Td>
      <Td>
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
      </Td>
      {canLink ? (
        <Td>
          <MemberSelect members={members} value={membershipId} onChange={setMembershipId} />
        </Td>
      ) : null}
      <Td>
        <input
          className="w-full rounded border border-ap-line px-2 py-1"
          placeholder={t("workers.phonePlaceholder")}
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
        />
      </Td>
      <Td className="text-ap-muted">{t("status.active")}</Td>
      <Td className="text-end">
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
      </Td>
    </Tr>
  );
}
