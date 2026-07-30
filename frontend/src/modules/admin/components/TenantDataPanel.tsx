import type { ReactNode } from "react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AdminTenant } from "@/api/adminTenants";
import type { TenantFarmEntity } from "@/api/purge";
import { Skeleton } from "@/components/Skeleton";
import { useOrphanScan, useTenantEntities } from "@/queries/admin/purge";

import { PurgeDialog, type PurgeTarget } from "./PurgeDialog";

interface Props {
  tenant: AdminTenant;
}

/**
 * The platform admin's only view of a tenant's farms and blocks.
 *
 * Every other farm surface in the app is tenant-scoped and resolves its tenant
 * from the JWT, so a platform admin has no way to see — let alone remove — a
 * specific farm. This tab is that surface, and purge is the reason it exists.
 */
export function TenantDataPanel({ tenant }: Props): ReactNode {
  const { t } = useTranslation("admin");
  const entities = useTenantEntities(tenant.id);
  const [target, setTarget] = useState<PurgeTarget | null>(null);

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-ap-line bg-ap-panel p-4 shadow-card">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ap-line pb-2">
          <h2 className="text-sm font-semibold text-ap-ink">
            {t("purge.data.farmsTitle", { count: entities.data?.farms.length ?? 0 })}
          </h2>
          <button
            type="button"
            onClick={() =>
              setTarget({
                kind: "tenant_data",
                id: tenant.id,
                tenantId: tenant.id,
                label: tenant.name,
              })
            }
            className="rounded-md border border-ap-crit/40 px-3 py-1.5 text-xs font-medium text-ap-crit hover:bg-ap-crit-soft"
          >
            {t("purge.data.resetAll")}
          </button>
        </div>
        <p className="mt-2 text-xs text-ap-muted">{t("purge.data.resetAllHint")}</p>

        {entities.isLoading ? (
          <Skeleton className="mt-3 h-24 w-full" />
        ) : entities.isError ? (
          <p role="alert" className="mt-3 text-sm text-ap-crit">
            {t("purge.data.loadError")}
          </p>
        ) : entities.data && entities.data.farms.length > 0 ? (
          <ul className="mt-3 divide-y divide-ap-line">
            {entities.data.farms.map((farm) => (
              <FarmRow
                key={farm.id}
                farm={farm}
                tenantId={tenant.id}
                onPurge={(target_) => setTarget(target_)}
              />
            ))}
          </ul>
        ) : (
          <p className="mt-3 text-sm text-ap-muted">{t("purge.data.noFarms")}</p>
        )}
      </section>

      <OrphanPanel />

      <PurgeDialog target={target} onClose={() => setTarget(null)} />
    </div>
  );
}

function FarmRow({
  farm,
  tenantId,
  onPurge,
}: {
  farm: TenantFarmEntity;
  tenantId: string;
  onPurge: (target: PurgeTarget) => void;
}): ReactNode {
  const { t } = useTranslation("admin");
  const [open, setOpen] = useState(false);
  const label = farm.name ?? farm.code ?? farm.id;

  return (
    <li className="py-2">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-2 text-start text-sm text-ap-ink hover:underline"
          aria-expanded={open}
        >
          <span aria-hidden="true" className="text-ap-muted">
            {open ? "▾" : "▸"}
          </span>
          <span className="truncate font-medium">{label}</span>
          <span className="text-xs text-ap-muted">
            {t("purge.data.blockCount", { count: farm.blocks.length })}
          </span>
          {farm.archived ? <ArchivedPill /> : null}
        </button>
        <PurgeButton onClick={() => onPurge({ kind: "farm", id: farm.id, tenantId, label })} />
      </div>
      {open && farm.blocks.length > 0 ? (
        <ul className="mt-1 space-y-1 ps-6">
          {farm.blocks.map((block) => {
            const blockLabel = block.code ?? block.name ?? block.id;
            return (
              <li key={block.id} className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-sm text-ap-muted">
                  {blockLabel}
                  {block.unit_type !== "block" ? (
                    <span className="ms-1 text-xs text-ap-muted/70">({block.unit_type})</span>
                  ) : null}
                  {block.archived ? <ArchivedPill /> : null}
                </span>
                <PurgeButton
                  onClick={() =>
                    onPurge({ kind: "block", id: block.id, tenantId, label: blockLabel })
                  }
                />
              </li>
            );
          })}
        </ul>
      ) : null}
    </li>
  );
}

function ArchivedPill(): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <span className="ms-2 rounded-full bg-ap-line/60 px-2 py-0.5 text-[10px] uppercase tracking-wide text-ap-muted">
      {t("purge.data.archived")}
    </span>
  );
}

function PurgeButton({ onClick }: { onClick: () => void }): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-md border border-ap-line px-2 py-1 text-xs font-medium text-ap-crit hover:bg-ap-crit-soft"
    >
      {t("purge.data.purge")}
    </button>
  );
}

/**
 * Residue left by purges that ran before the manifest existed — most visibly
 * the decision trees, backfill runs and STAC catalogues that the old
 * three-table tenant cleanup never touched.
 */
function OrphanPanel(): ReactNode {
  const { t } = useTranslation("admin");
  const [enabled, setEnabled] = useState(false);
  const scan = useOrphanScan(enabled);

  return (
    <section className="rounded-lg border border-ap-line bg-ap-panel p-4 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ap-line pb-2">
        <h2 className="text-sm font-semibold text-ap-ink">{t("purge.orphans.title")}</h2>
        <button
          type="button"
          onClick={() => {
            setEnabled(true);
            void scan.refetch();
          }}
          disabled={scan.isFetching}
          className="rounded-md border border-ap-line px-3 py-1.5 text-xs font-medium text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
        >
          {scan.isFetching ? t("purge.orphans.scanning") : t("purge.orphans.scan")}
        </button>
      </div>
      <p className="mt-2 text-xs text-ap-muted">{t("purge.orphans.hint")}</p>

      {!enabled ? null : scan.isLoading ? (
        <Skeleton className="mt-3 h-16 w-full" />
      ) : scan.isError ? (
        <p role="alert" className="mt-3 text-sm text-ap-crit">
          {t("purge.orphans.error")}
        </p>
      ) : scan.data ? (
        scan.data.orphans_found === 0 && scan.data.stray_schemas.length === 0 ? (
          <p className="mt-3 text-sm text-ap-ok">
            {t("purge.orphans.clean", { tables: scan.data.scanned_tables })}
          </p>
        ) : (
          <>
            <ul className="mt-3 divide-y divide-ap-line text-sm">
              {scan.data.orphans.map((o) => (
                <li
                  key={`${o.schema}.${o.table}.${o.column}`}
                  className="flex justify-between gap-3 py-1.5"
                >
                  <span className="truncate font-mono text-xs text-ap-muted">
                    {o.schema}.{o.table}.{o.column}
                  </span>
                  <span className="tabular-nums text-ap-crit">{o.rows.toLocaleString()}</span>
                </li>
              ))}
            </ul>
            {scan.data.stray_schemas.length > 0 ? (
              <p className="mt-3 text-sm text-ap-warn">
                {t("purge.orphans.straySchemas", {
                  schemas: scan.data.stray_schemas.join(", "),
                })}
              </p>
            ) : null}
          </>
        )
      ) : null}
    </section>
  );
}
