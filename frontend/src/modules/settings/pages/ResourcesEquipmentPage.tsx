import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { listFarms } from "@/api/farms";
import type { EquipmentType } from "@/api/resources";
import { AsyncBoundary } from "@/components/AsyncBoundary";
import { localizedName } from "@/lib/localizedField";
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

const TYPES: EquipmentType[] = ["tractor", "sprayer", "irrigation_pump", "harvester", "other"];

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
        <EmptyState message={t("equipment.empty")} action={null} />
      ) : (
        <AsyncBoundary
          state={queryState(itemsQ)}
          errorMessage={t("loadFailed")}
          isEmpty={() => false}
          empty={<EmptyState message={t("equipment.emptyList")} action={null} />}
        >
          {(rows) => <EquipmentTable rows={rows} farmId={effectiveFarmId} canManage={canManage} />}
        </AsyncBoundary>
      )}
    </div>
  );
}

interface EquipmentTableProps {
  rows: Awaited<ReturnType<typeof import("@/api/resources").listResources>>;
  farmId: string;
  canManage: boolean;
}

function EquipmentTable({ rows, farmId, canManage }: EquipmentTableProps): ReactNode {
  const { t } = useTranslation("resources");
  const [adding, setAdding] = useState(false);

  return (
    <Card
      noPadding
      title={t("equipment.heading")}
      actions={
        canManage ? (
          <Button size="sm" onClick={() => setAdding(true)}>
            {t("equipment.add")}
          </Button>
        ) : null
      }
    >
      <Table>
        <Thead>
          <Tr>
            <Th>{t("col.name")}</Th>
            <Th>{t("col.type")}</Th>
            <Th>{t("col.status")}</Th>
            {canManage ? <Th className="w-32" /> : null}
          </Tr>
        </Thead>
        <Tbody>
          {rows.length === 0 && !adding ? (
            <Tr>
              <Td colSpan={canManage ? 4 : 3} className="px-3 py-6 text-center text-ap-muted">
                {t("equipment.emptyList")}
              </Td>
            </Tr>
          ) : null}
          {rows.map((r) => (
            <EquipmentRow key={r.id} row={r} farmId={farmId} canManage={canManage} />
          ))}
          {adding ? <AddEquipmentRow farmId={farmId} onDone={() => setAdding(false)} /> : null}
        </Tbody>
      </Table>
    </Card>
  );
}

interface EquipmentRowProps {
  row: Awaited<ReturnType<typeof import("@/api/resources").listResources>>[number];
  farmId: string;
  canManage: boolean;
}

function EquipmentRow({ row, farmId, canManage }: EquipmentRowProps): ReactNode {
  const { t, i18n } = useTranslation("resources");
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(row.name);
  const [nameAr, setNameAr] = useState(row.name_ar ?? "");
  const [type, setType] = useState<EquipmentType>(row.equipment_type ?? "other");
  const update = useUpdateResource(farmId);

  if (editing) {
    return (
      <Tr className="border-t border-ap-line">
        <Td>
          {/* Both names in one cell — see ResourcesWorkersPage. */}
          <input
            className="w-full rounded border border-ap-line px-2 py-1"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label={t("col.name")}
          />
          <input
            className="mt-1 w-full rounded border border-ap-line px-2 py-1"
            dir="rtl"
            lang="ar"
            placeholder={t("col.nameAr")}
            aria-label={t("col.nameAr")}
            value={nameAr}
            onChange={(e) => setNameAr(e.target.value)}
          />
        </Td>
        <Td>
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
                  payload: { name, name_ar: nameAr.trim() || null, equipment_type: type },
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
      <Td>{localizedName(i18n.language, row.name, row.name_ar)}</Td>
      <Td className="text-ap-muted">{t(`equipmentType.${row.equipment_type}`)}</Td>
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

interface AddEquipmentRowProps {
  farmId: string;
  onDone: () => void;
}

function AddEquipmentRow({ farmId, onDone }: AddEquipmentRowProps): ReactNode {
  const { t } = useTranslation("resources");
  const [name, setName] = useState("");
  const [nameAr, setNameAr] = useState("");
  const [type, setType] = useState<EquipmentType>("tractor");
  const create = useCreateResource(farmId);

  return (
    <Tr className="border-t border-ap-line bg-ap-bg/30">
      <Td>
        <input
          className="w-full rounded border border-ap-line px-2 py-1"
          placeholder={t("equipment.namePlaceholder")}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className="mt-1 w-full rounded border border-ap-line px-2 py-1"
          dir="rtl"
          lang="ar"
          placeholder={t("col.nameAr")}
          aria-label={t("col.nameAr")}
          value={nameAr}
          onChange={(e) => setNameAr(e.target.value)}
        />
      </Td>
      <Td>
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
                kind: "equipment",
                name: name.trim(),
                name_ar: nameAr.trim() || null,
                equipment_type: type,
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
