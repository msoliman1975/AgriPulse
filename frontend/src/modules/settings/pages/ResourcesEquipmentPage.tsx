import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { listFarms } from "@/api/farms";
import type { EquipmentType } from "@/api/resources";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { useCapability } from "@/rbac/useCapability";
import {
  useCreateResource,
  useResources,
  useUpdateResource,
} from "@/queries/resources";

const TYPES: EquipmentType[] = [
  "tractor",
  "sprayer",
  "irrigation_pump",
  "harvester",
  "other",
];

/**
 * /settings/equipment — per-farm catalog of machinery. Master file for
 * the board's quick-add picker (PR-4).
 */
export function ResourcesEquipmentPage(): ReactNode {
  const { t } = useTranslation("resources");
  const canManage = useCapability("resource.manage");

  const farmsQ = useQuery({
    queryKey: ["farms", "list-tenant"],
    queryFn: () => listFarms({ limit: 100 }),
    staleTime: 60_000,
  });
  const [farmId, setFarmId] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);

  // Default to the first farm once farms load. Computed before
  // useResources so the list query and the create button act on the
  // same farm; otherwise create succeeds but invalidation misses the
  // disabled `farmId=null` query and the row never appears.
  const effectiveFarmId = useMemo(
    () => farmId ?? farmsQ.data?.items[0]?.id ?? null,
    [farmId, farmsQ.data],
  );

  const itemsQ = useResources(effectiveFarmId, {
    kind: "equipment",
    include_archived: includeArchived,
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("equipment.title")} subtitle={t("equipment.subtitle")} />

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
        <p className="text-sm text-ap-muted">{t("equipment.empty")}</p>
      ) : itemsQ.isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : itemsQ.isError ? (
        <p className="text-sm text-ap-crit">{t("loadFailed")}</p>
      ) : (
        <EquipmentTable
          rows={itemsQ.data ?? []}
          farmId={effectiveFarmId}
          canManage={canManage}
        />
      )}
    </div>
  );
}

interface EquipmentTableProps {
  rows: Awaited<ReturnType<typeof import("@/api/resources").listResources>>;
  farmId: string;
  canManage: boolean;
}

function EquipmentTable({
  rows,
  farmId,
  canManage,
}: EquipmentTableProps): ReactNode {
  const { t } = useTranslation("resources");
  const [adding, setAdding] = useState(false);

  return (
    <div className="rounded-xl border border-ap-line bg-ap-panel">
      <div className="flex items-center justify-between border-b border-ap-line p-3">
        <h2 className="text-sm font-semibold text-ap-ink">
          {t("equipment.heading")}
        </h2>
        {canManage ? (
          <button
            type="button"
            className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary-700"
            onClick={() => setAdding(true)}
          >
            {t("equipment.add")}
          </button>
        ) : null}
      </div>
      <table className="w-full text-sm">
        <thead className="bg-ap-bg/50 text-xs uppercase tracking-wider text-ap-muted">
          <tr>
            <th className="px-3 py-2 text-left">{t("col.name")}</th>
            <th className="px-3 py-2 text-left">{t("col.type")}</th>
            <th className="px-3 py-2 text-left">{t("col.status")}</th>
            {canManage ? <th className="w-32" /> : null}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && !adding ? (
            <tr>
              <td
                colSpan={canManage ? 4 : 3}
                className="px-3 py-6 text-center text-ap-muted"
              >
                {t("equipment.emptyList")}
              </td>
            </tr>
          ) : null}
          {rows.map((r) => (
            <EquipmentRow
              key={r.id}
              row={r}
              farmId={farmId}
              canManage={canManage}
            />
          ))}
          {adding ? (
            <AddEquipmentRow farmId={farmId} onDone={() => setAdding(false)} />
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

interface EquipmentRowProps {
  row: Awaited<ReturnType<typeof import("@/api/resources").listResources>>[number];
  farmId: string;
  canManage: boolean;
}

function EquipmentRow({ row, farmId, canManage }: EquipmentRowProps): ReactNode {
  const { t } = useTranslation("resources");
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(row.name);
  const [type, setType] = useState<EquipmentType>(row.equipment_type ?? "other");
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
            value={type}
            onChange={(e) => setType(e.target.value as EquipmentType)}
          >
            {TYPES.map((tp) => (
              <option key={tp} value={tp}>
                {t(`equipmentType.${tp}`)}
              </option>
            ))}
          </select>
        </td>
        <td className="px-3 py-2 text-ap-muted">
          {row.archived_at ? t("status.archived") : t("status.active")}
        </td>
        <td className="px-3 py-2 text-right">
          <button
            type="button"
            disabled={update.isPending}
            className="mr-2 text-sm text-ap-primary hover:underline"
            onClick={() =>
              update.mutate(
                {
                  resourceId: row.id,
                  payload: { name, equipment_type: type },
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
      <td className="px-3 py-2 text-ap-muted">
        {t(`equipmentType.${row.equipment_type}`)}
      </td>
      <td className="px-3 py-2 text-ap-muted">
        {row.archived_at ? t("status.archived") : t("status.active")}
      </td>
      {canManage ? (
        <td className="px-3 py-2 text-right">
          <button
            type="button"
            className="mr-3 text-sm text-ap-primary hover:underline"
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

interface AddEquipmentRowProps {
  farmId: string;
  onDone: () => void;
}

function AddEquipmentRow({ farmId, onDone }: AddEquipmentRowProps): ReactNode {
  const { t } = useTranslation("resources");
  const [name, setName] = useState("");
  const [type, setType] = useState<EquipmentType>("tractor");
  const create = useCreateResource(farmId);

  return (
    <tr className="border-t border-ap-line bg-ap-bg/30">
      <td className="px-3 py-2">
        <input
          autoFocus
          className="w-full rounded border border-ap-line px-2 py-1"
          placeholder={t("equipment.namePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </td>
      <td className="px-3 py-2">
        <select
          className="rounded border border-ap-line px-2 py-1"
          value={type}
          onChange={(e) => setType(e.target.value as EquipmentType)}
        >
          {TYPES.map((tp) => (
            <option key={tp} value={tp}>
              {t(`equipmentType.${tp}`)}
            </option>
          ))}
        </select>
      </td>
      <td className="px-3 py-2 text-ap-muted">{t("status.active")}</td>
      <td className="px-3 py-2 text-right">
        <button
          type="button"
          disabled={!name.trim() || create.isPending}
          className="mr-2 text-sm text-ap-primary hover:underline disabled:opacity-50"
          onClick={() =>
            create.mutate(
              {
                kind: "equipment",
                name: name.trim(),
                equipment_type: type,
              },
              { onSuccess: onDone },
            )
          }
        >
          {t("action.create")}
        </button>
        <button
          type="button"
          className="text-sm text-ap-muted hover:underline"
          onClick={onDone}
        >
          {t("action.cancel")}
        </button>
        {create.isError ? (
          <p className="mt-1 text-xs text-ap-crit">{t("createFailed")}</p>
        ) : null}
      </td>
    </tr>
  );
}
