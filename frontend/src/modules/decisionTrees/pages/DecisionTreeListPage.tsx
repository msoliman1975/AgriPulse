import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import type { DecisionTree, DecisionTreeListStatus } from "@/api/decisionTrees";
import { listCountries } from "@/api/countries";
import { Button } from "@/components/Button";
import { DataTable, RowActions } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { LinkButton } from "@/components/LinkButton";
import { Modal } from "@/components/Modal";
import { PageHeader } from "@/components/PageHeader";
import { Page } from "@/components/Page";
import { Pill } from "@/components/Pill";
import { Toolbar, ToolbarChips, type FilterValues } from "@/components/Toolbar";
import { mapAsyncState, queryState } from "@/components/asyncState";
import { useCapability } from "@/rbac/useCapability";
import {
  useArchiveDecisionTree,
  useDecisionTrees,
  useRestoreDecisionTree,
} from "@/queries/decisionTrees";

export function DecisionTreeListPage(): ReactNode {
  const { t, i18n } = useTranslation("decisionTrees");
  const isAr = i18n.language === "ar";
  const canManage = useCapability("decision_tree.manage");

  const [status, setStatus] = useState<DecisionTreeListStatus>("active");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<FilterValues>({});
  const [archiveTarget, setArchiveTarget] = useState<DecisionTree | null>(null);

  const trees = useDecisionTrees(status);
  const data = trees.data;
  const countriesQ = useQuery({
    queryKey: ["decision_trees", "countries"],
    queryFn: () => listCountries(),
    staleTime: 5 * 60_000,
  });
  const archive = useArchiveDecisionTree();
  const restore = useRestoreDecisionTree();

  // Readable country name for a code (falls back to the raw code).
  const countryName = useMemo(() => {
    const byCode = new Map((countriesQ.data ?? []).map((c) => [c.code, c]));
    return (code: string): string => {
      const c = byCode.get(code);
      if (!c) return code;
      return isAr ? c.name_ar : c.name_en;
    };
  }, [countriesQ.data, isAr]);

  // Filter option sources — distinct values actually present in the catalog.
  const { locationOptions, soilOptions } = useMemo(() => {
    const locs = new Set<string>();
    const soils = new Set<string>();
    for (const tree of data ?? []) {
      tree.country_codes.forEach((c) => locs.add(c));
      tree.soil_textures.forEach((s) => soils.add(s));
    }
    return {
      locationOptions: [...locs].sort(),
      soilOptions: [...soils].sort(),
    };
  }, [data]);

  // Client-side because the catalog endpoint takes no filter params. The
  // toolbar is agnostic — it emits a FilterValues object and the page decides
  // where the narrowing happens.
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const wanted = (key: string): readonly string[] => filters[key] ?? [];
    return (data ?? []).filter((tree) => {
      if (q) {
        const hay = `${tree.code} ${tree.name_en} ${tree.name_ar ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      const locs = wanted("location");
      if (locs.length && !locs.some((c) => tree.country_codes.includes(c))) return false;
      const soils = wanted("soil");
      if (soils.length && !soils.some((s) => tree.soil_textures.includes(s))) return false;
      const scopes = wanted("scope");
      if (scopes.length && !scopes.includes(tree.scope)) return false;
      return true;
    });
  }, [data, search, filters]);

  const isFiltered =
    search.trim() !== "" || Object.values(filters).some((v) => (v?.length ?? 0) > 0);

  const onConfirmArchive = (): void => {
    if (!archiveTarget) return;
    archive.mutate({ code: archiveTarget.code }, { onSettled: () => setArchiveTarget(null) });
  };

  return (
    <Page>
      <PageHeader
        title={t("list.title")}
        subtitle={t("list.subtitle")}
        actions={
          canManage ? <LinkButton to="/decision-trees/new">{t("list.newButton")}</LinkButton> : null
        }
      />

      {!canManage ? (
        <p className="text-xs text-ap-muted">
          {t("list.missingCapability", { capability: "decision_tree.manage" })}
        </p>
      ) : null}

      <Toolbar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: t("list.search"),
          label: t("list.searchAria"),
        }}
        chips={
          <ToolbarChips
            value={status}
            onChange={(next) => setStatus((next as DecisionTreeListStatus | null) ?? "active")}
            options={[
              { value: "active", label: t("list.status.active") },
              { value: "archived", label: t("list.status.archived") },
              { value: "all", label: t("list.status.all") },
            ]}
          />
        }
        axes={[
          {
            key: "location",
            label: t("list.filters.location"),
            options: locationOptions.map((c) => ({ value: c, label: countryName(c) })),
          },
          {
            key: "soil",
            label: t("list.filters.soil"),
            options: soilOptions.map((s) => ({
              value: s,
              label: t(`targeting.soilValues.${s}`),
            })),
          },
          {
            key: "scope",
            label: t("list.filters.scope"),
            single: true,
            options: (["block", "cell"] as const).map((s) => ({
              value: s,
              label: t(`targeting.scopeValues.${s}`),
            })),
          },
        ]}
        values={filters}
        onValuesChange={setFilters}
        resultCount={data ? { shown: filtered.length, total: data.length } : undefined}
      />

      <DataTable<DecisionTree>
        columns={[
          {
            key: "code",
            header: t("list.table.code"),
            className: "font-mono text-xs",
            cell: (tree) => tree.code,
          },
          {
            key: "name",
            header: t("list.table.name"),
            cell: (tree) => (
              <span className="flex items-center gap-1.5">
                {isAr && tree.name_ar ? tree.name_ar : tree.name_en}
                {tree.archived ? <Pill kind="neutral">{t("list.row.archivedBadge")}</Pill> : null}
              </span>
            ),
          },
          {
            key: "crop",
            header: t("list.table.crop"),
            className: "text-xs text-ap-muted",
            cell: (tree) => (
              <ChipSet values={tree.crop_paths} empty={t("list.table.anyCrop")} mono />
            ),
          },
          {
            key: "soil",
            header: t("list.table.soil"),
            className: "text-xs text-ap-muted",
            cell: (tree) => (
              <ChipSet
                values={tree.soil_textures.map((s) => t(`targeting.soilValues.${s}`))}
                empty={t("list.table.anySoil")}
              />
            ),
          },
          {
            key: "locations",
            header: t("list.table.locations"),
            className: "text-xs text-ap-muted",
            cell: (tree) => (
              <ChipSet
                values={tree.country_codes.map(countryName)}
                empty={t("list.table.anyLocation")}
              />
            ),
          },
          {
            key: "scope",
            header: t("list.table.scope"),
            className: "text-xs",
            cell: (tree) => t(`targeting.scopeValues.${tree.scope}`),
          },
          {
            key: "version",
            header: t("list.table.version"),
            align: "end",
            cell: (tree) =>
              tree.current_version != null ? (
                <Pill kind="ok">{t("list.row.v", { n: tree.current_version })}</Pill>
              ) : (
                <Pill kind="neutral">{t("list.row.draft")}</Pill>
              ),
          },
          {
            key: "actions",
            header: t("list.table.actions"),
            align: "end",
            cell: (tree) =>
              canManage && tree.tenant_id != null ? (
                <RowActions>
                  {tree.archived ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={restore.isPending}
                      onClick={() => restore.mutate({ code: tree.code })}
                    >
                      {restore.isPending ? t("list.row.restoring") : t("list.row.restore")}
                    </Button>
                  ) : (
                    <Button size="sm" variant="ghost" onClick={() => setArchiveTarget(tree)}>
                      {t("list.row.archive")}
                    </Button>
                  )}
                </RowActions>
              ) : null,
          },
        ]}
        rowKey={(tree) => tree.id}
        state={mapAsyncState(queryState(trees), () => filtered)}
        filtered={isFiltered}
        rowHref={(tree) => `/decision-trees/${tree.code}`}
        caption={t("list.title")}
        errorMessage={t("list.loadFailed")}
        empty={
          <EmptyState
            message={t("list.empty")}
            action={
              canManage ? (
                <LinkButton to="/decision-trees/new">{t("list.newButton")}</LinkButton>
              ) : null
            }
          />
        }
        noResults={
          <EmptyState
            message={t("list.noResults")}
            action={
              <Button
                variant="secondary"
                onClick={() => {
                  setSearch("");
                  setFilters({});
                  setStatus("active");
                }}
              >
                {t("list.clearFilters")}
              </Button>
            }
          />
        }
      />

      {archiveTarget ? (
        <Modal
          open
          onClose={() => setArchiveTarget(null)}
          labelledBy="dt-archive-title"
          className="max-w-md"
        >
          <h2 id="dt-archive-title" className="text-base font-semibold text-ap-ink">
            {t("list.archiveConfirm.title")}
          </h2>
          <p className="mt-2 text-sm text-ap-ink">
            {t("list.archiveConfirm.body", {
              name: isAr && archiveTarget.name_ar ? archiveTarget.name_ar : archiveTarget.name_en,
            })}
          </p>
          {archive.isError ? (
            <p className="mt-2 text-xs text-ap-crit">{t("list.archiveConfirm.failed")}</p>
          ) : null}
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setArchiveTarget(null)}
              className="rounded-md px-3 py-1.5 text-sm text-ap-muted"
            >
              {t("list.archiveConfirm.cancel")}
            </button>
            <button
              type="button"
              onClick={onConfirmArchive}
              disabled={archive.isPending}
              className="rounded-md bg-ap-crit px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-crit/90 disabled:opacity-60"
            >
              {t("list.archiveConfirm.confirm")}
            </button>
          </div>
        </Modal>
      ) : null}
    </Page>
  );
}

function ChipSet({
  values,
  empty,
  mono,
}: {
  values: string[];
  empty: string;
  mono?: boolean;
}): ReactNode {
  if (values.length === 0) {
    return <span>{empty}</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {values.map((v) => (
        <span
          key={v}
          className={`rounded bg-ap-primary/10 px-1.5 py-0.5 text-[11px] text-ap-primary ${
            mono ? "font-mono" : ""
          }`}
        >
          {v}
        </span>
      ))}
    </div>
  );
}
