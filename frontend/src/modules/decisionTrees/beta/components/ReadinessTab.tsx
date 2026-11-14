// Readiness (decision D15): what this tree needs before it can run, and which
// blocks have it. A tree whose data is missing does not fail; it stays silent.
// This tab says why.
//
// A tenant sees every targeted block with what it lacks and, for an admin, a
// link to where it is fixed. A platform admin sees counts per tenant only:
// block detail belongs to the tenant.

import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { Card } from "@/components/Card";
import { FIELD_CONTROL_CLASS } from "@/components/Field";
import { Pill, type PillKind } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";

import {
  READINESS_STATUSES,
  readinessFixPath,
  useTreeReadiness,
  useTreeReadinessSummary,
  type ReadinessBlock,
  type ReadinessCounts,
  type ReadinessRequirement,
  type ReadinessStatus,
} from "../lib/readinessApi";

const STATUS_PILL: Record<ReadinessStatus, PillKind> = {
  ready: "ok",
  partial: "warn",
  not_ready: "crit",
};

interface Props {
  treeId: string | null;
  scope: "platform" | "tenant";
  /** Tenant admins get fix links; viewers see what is missing only. */
  canFix: boolean;
}

export function ReadinessTab({ treeId, scope, canFix }: Props): ReactNode {
  const { t } = useTranslation("decisionTreesBeta");
  const tenantQ = useTreeReadiness(treeId, scope === "tenant");
  const summaryQ = useTreeReadinessSummary(treeId, scope === "platform");
  const q = scope === "tenant" ? tenantQ : summaryQ;

  if (!treeId) return <StatusBanner kind="info">{t("readiness.saveFirst")}</StatusBanner>;
  if (q.isLoading) return <p className="text-sm text-ap-muted">{t("readiness.loading")}</p>;
  if (q.isError || !q.data) {
    return <StatusBanner kind="crit">{t("readiness.loadFailed")}</StatusBanner>;
  }

  return (
    <div className="flex flex-col gap-4">
      <BeforeItCanRun
        requirements={q.data.requirements}
        noteEn={q.data.readiness_note_en}
        noteAr={q.data.readiness_note_ar}
      />
      {scope === "tenant" && tenantQ.data ? (
        <BlockList
          blocks={tenantQ.data.blocks}
          counts={tenantQ.data.counts}
          targeted={tenantQ.data.blocks_targeted}
          assessed={tenantQ.data.blocks_assessed}
          canFix={canFix}
        />
      ) : null}
      {scope === "platform" && summaryQ.data ? (
        <TenantCounts tenants={summaryQ.data.tenants} />
      ) : null}
    </div>
  );
}

export function RequirementLabel({ req }: { req: ReadinessRequirement }): ReactNode {
  const { t } = useTranslation("decisionTreesBeta");
  // One requirement per tree whatever is read, so the key says nothing.
  if (req.kind === "weather" || req.kind === "water_balance" || req.kind === "heat_units") {
    return <>{t(`readiness.kind.${req.kind}`)}</>;
  }
  return (
    <>
      {t(`readiness.kind.${req.kind}`)}: <code className="font-mono text-[11px]">{req.key}</code>
    </>
  );
}

function BeforeItCanRun({
  requirements,
  noteEn,
  noteAr,
}: {
  requirements: ReadinessRequirement[];
  noteEn: string | null;
  noteAr: string | null;
}): ReactNode {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const note = i18n.language.startsWith("ar") ? (noteAr ?? noteEn) : (noteEn ?? noteAr);
  return (
    <Card title={t("readiness.beforeTitle")}>
      {note ? <p className="mb-3 whitespace-pre-line text-sm text-ap-ink">{note}</p> : null}
      {requirements.length === 0 ? (
        <p className="text-sm text-ap-muted">{t("readiness.noRequirements")}</p>
      ) : (
        <ul className="list-disc space-y-1 ps-5 text-sm text-ap-ink">
          {requirements.map((req) => (
            <li key={`${req.kind}:${req.key}`}>
              <RequirementLabel req={req} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function CountPills({ counts }: { counts: Partial<ReadinessCounts> }): ReactNode {
  const { t } = useTranslation("decisionTreesBeta");
  return (
    <span className="flex flex-wrap gap-2">
      {READINESS_STATUSES.map((s) => (
        <Pill key={s} kind={STATUS_PILL[s]}>
          {t(`readiness.status.${s}`)}: {counts[s] ?? 0}
        </Pill>
      ))}
    </span>
  );
}

function BlockList({
  blocks,
  counts,
  targeted,
  assessed,
  canFix,
}: {
  blocks: ReadinessBlock[];
  counts: ReadinessCounts;
  targeted: number;
  assessed: number;
  canFix: boolean;
}): ReactNode {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const ar = i18n.language.startsWith("ar");
  const [filter, setFilter] = useState<ReadinessStatus | "all">("all");
  const shown = useMemo(
    () => (filter === "all" ? blocks : blocks.filter((b) => b.status === filter)),
    [blocks, filter],
  );

  if (targeted === 0) {
    return <StatusBanner kind="info">{t("readiness.noBlocks")}</StatusBanner>;
  }

  return (
    <Card title={t("readiness.blocksTitle", { count: targeted })}>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <CountPills counts={counts} />
        <select
          aria-label={t("readiness.filter")}
          className={`ms-auto ${FIELD_CONTROL_CLASS}`}
          value={filter}
          onChange={(e) => setFilter(e.target.value as ReadinessStatus | "all")}
        >
          <option value="all">{t("readiness.filterAll")}</option>
          {READINESS_STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`readiness.status.${s}`)}
            </option>
          ))}
        </select>
      </div>
      {assessed < targeted ? (
        <p className="mb-2 text-[11px] text-ap-muted">
          {t("readiness.truncated", { assessed, targeted })}
        </p>
      ) : null}
      <ul className="divide-y divide-ap-line rounded-md border border-ap-line">
        {shown.map((b) => {
          const blockName = (ar ? b.block_name_ar : null) ?? b.block_name ?? b.block_code;
          const farmName = (ar ? b.farm_name_ar : null) ?? b.farm_name;
          return (
            <li key={b.block_id} className="flex flex-col gap-1 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <Pill kind={STATUS_PILL[b.status]}>{t(`readiness.status.${b.status}`)}</Pill>
                <span className="text-sm text-ap-ink">{blockName}</span>
                {farmName ? <span className="text-[11px] text-ap-muted">{farmName}</span> : null}
                <span className="ms-auto text-[11px] text-ap-muted">
                  {t("readiness.met", { met: b.met, total: b.total })}
                </span>
              </div>
              {b.missing.length > 0 ? (
                <ul className="flex flex-col gap-1 ps-2 text-[12px] text-ap-muted">
                  {b.missing.map((req) => {
                    const fix = canFix ? readinessFixPath(b, req.kind) : null;
                    return (
                      <li key={`${req.kind}:${req.key}`} className="flex flex-wrap gap-2">
                        <span>
                          {t("readiness.missing")} <RequirementLabel req={req} />
                        </span>
                        {fix ? (
                          <Link className="text-ap-accent underline" to={fix}>
                            {t(`readiness.fix.${req.kind}`)}
                          </Link>
                        ) : null}
                      </li>
                    );
                  })}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function TenantCounts({
  tenants,
}: {
  tenants: {
    tenant_id: string;
    tenant_name: string | null;
    blocks_targeted: number;
    counts: ReadinessCounts;
    error: string | null;
  }[];
}): ReactNode {
  const { t } = useTranslation("decisionTreesBeta");
  if (tenants.length === 0) {
    return <StatusBanner kind="info">{t("readiness.noTenants")}</StatusBanner>;
  }
  return (
    <Card title={t("readiness.tenantsTitle")}>
      <p className="mb-3 text-[11px] text-ap-muted">{t("readiness.platformNote")}</p>
      <ul className="divide-y divide-ap-line rounded-md border border-ap-line">
        {tenants.map((row) => (
          <li key={row.tenant_id} className="flex flex-wrap items-center gap-2 px-3 py-2">
            <span className="text-sm text-ap-ink">{row.tenant_name ?? row.tenant_id}</span>
            {row.error ? (
              <Pill kind="crit">{t("readiness.tenantError")}</Pill>
            ) : (
              <>
                <span className="text-[11px] text-ap-muted">
                  {t("readiness.blocksTargeted", { count: row.blocks_targeted })}
                </span>
                <span className="ms-auto">
                  <CountPills counts={row.counts} />
                </span>
              </>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
