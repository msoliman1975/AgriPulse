import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import type { DecisionTree, DecisionTreeListStatus } from "@/api/decisionTrees";
import { listCountries } from "@/api/countries";
import { Modal } from "@/components/Modal";
import { Page } from "@/components/Page";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useCapability } from "@/rbac/useCapability";
import {
  useArchiveDecisionTree,
  useDecisionTrees,
  useRestoreDecisionTree,
} from "@/queries/decisionTrees";

const NO_FILTER = "";

export function DecisionTreeListPage(): ReactNode {
  const { t, i18n } = useTranslation("decisionTrees");
  const isAr = i18n.language === "ar";
  const canManage = useCapability("decision_tree.manage");

  const [status, setStatus] = useState<DecisionTreeListStatus>("active");
  const [search, setSearch] = useState("");
  const [location, setLocation] = useState(NO_FILTER);
  const [soil, setSoil] = useState(NO_FILTER);
  const [scope, setScope] = useState(NO_FILTER);
  const [archiveTarget, setArchiveTarget] = useState<DecisionTree | null>(null);

  const { data, isLoading, isError } = useDecisionTrees(status);
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

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (data ?? []).filter((tree) => {
      if (q) {
        const hay = `${tree.code} ${tree.name_en} ${tree.name_ar ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (location && !tree.country_codes.includes(location)) return false;
      if (soil && !tree.soil_textures.includes(soil)) return false;
      if (scope && tree.scope !== scope) return false;
      return true;
    });
  }, [data, search, location, soil, scope]);

  const onConfirmArchive = (): void => {
    if (!archiveTarget) return;
    archive.mutate({ code: archiveTarget.code }, { onSettled: () => setArchiveTarget(null) });
  };

  return (
    <Page>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ap-ink">{t("list.title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("list.subtitle")}</p>
        </div>
        {canManage ? (
          <Link
            to="/decision-trees/new"
            className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90"
          >
            {t("list.newButton")}
          </Link>
        ) : null}
      </header>

      {!canManage ? (
        <p className="text-xs text-ap-muted">
          {t("list.missingCapability", { capability: "decision_tree.manage" })}
        </p>
      ) : null}

      {/* Toolbar: search + per-axis filters + status. */}
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-1 flex-col gap-1" style={{ minWidth: "16rem" }}>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t("list.search")}
            aria-label={t("list.searchAria")}
            className="w-full rounded-md border border-ap-line bg-white px-3 py-1.5 text-sm shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
          />
        </label>
        <FilterSelect
          label={t("list.filters.location")}
          value={location}
          onChange={setLocation}
          allLabel={t("list.filters.all")}
          options={locationOptions.map((c) => ({ value: c, label: countryName(c) }))}
        />
        <FilterSelect
          label={t("list.filters.soil")}
          value={soil}
          onChange={setSoil}
          allLabel={t("list.filters.all")}
          options={soilOptions.map((s) => ({ value: s, label: t(`targeting.soilValues.${s}`) }))}
        />
        <FilterSelect
          label={t("list.filters.scope")}
          value={scope}
          onChange={setScope}
          allLabel={t("list.filters.all")}
          options={(["block", "cell"] as const).map((s) => ({
            value: s,
            label: t(`targeting.scopeValues.${s}`),
          }))}
        />
        <FilterSelect
          label={t("list.filters.status")}
          value={status}
          onChange={(v) => setStatus(v as DecisionTreeListStatus)}
          options={[
            { value: "active", label: t("list.status.active") },
            { value: "archived", label: t("list.status.archived") },
            { value: "all", label: t("list.status.all") },
          ]}
        />
      </div>

      <div className="rounded-xl border border-ap-line bg-ap-panel">
        {isLoading ? (
          <div className="flex flex-col gap-2 p-4">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : isError ? (
          <p className="p-4 text-sm text-ap-crit">{t("list.loadFailed")}</p>
        ) : !data || data.length === 0 ? (
          <p className="p-12 text-center text-sm text-ap-muted">{t("list.empty")}</p>
        ) : filtered.length === 0 ? (
          <p className="p-12 text-center text-sm text-ap-muted">{t("list.noResults")}</p>
        ) : (
          <table className="min-w-full text-sm">
            <thead className="bg-ap-bg/40 text-xs uppercase text-ap-muted">
              <tr>
                <th className="px-4 py-2 text-start">{t("list.table.code")}</th>
                <th className="px-4 py-2 text-start">{t("list.table.name")}</th>
                <th className="px-4 py-2 text-start">{t("list.table.crop")}</th>
                <th className="px-4 py-2 text-start">{t("list.table.soil")}</th>
                <th className="px-4 py-2 text-start">{t("list.table.locations")}</th>
                <th className="px-4 py-2 text-start">{t("list.table.scope")}</th>
                <th className="px-4 py-2 text-end">{t("list.table.version")}</th>
                <th className="px-4 py-2 text-end">{t("list.table.actions")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ap-line">
              {filtered.map((tree) => (
                <tr key={tree.id}>
                  <td className="px-4 py-2">
                    <Link
                      to={`/decision-trees/${tree.code}`}
                      className="font-mono text-xs text-ap-primary hover:underline"
                    >
                      {tree.code}
                    </Link>
                  </td>
                  <td className="px-4 py-2 text-ap-ink">
                    <span className="flex items-center gap-1.5">
                      {isAr && tree.name_ar ? tree.name_ar : tree.name_en}
                      {tree.archived ? (
                        <Pill kind="neutral">{t("list.row.archivedBadge")}</Pill>
                      ) : null}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-ap-muted">
                    <ChipSet values={tree.crop_paths} empty={t("list.table.anyCrop")} mono />
                  </td>
                  <td className="px-4 py-2 text-xs text-ap-muted">
                    <ChipSet
                      values={tree.soil_textures.map((s) => t(`targeting.soilValues.${s}`))}
                      empty={t("list.table.anySoil")}
                    />
                  </td>
                  <td className="px-4 py-2 text-xs text-ap-muted">
                    <ChipSet
                      values={tree.country_codes.map(countryName)}
                      empty={t("list.table.anyLocation")}
                    />
                  </td>
                  <td className="px-4 py-2 text-xs text-ap-ink">
                    {t(`targeting.scopeValues.${tree.scope}`)}
                  </td>
                  <td className="px-4 py-2 text-end">
                    {tree.current_version != null ? (
                      <Pill kind="ok">{t("list.row.v", { n: tree.current_version })}</Pill>
                    ) : (
                      <Pill kind="neutral">{t("list.row.draft")}</Pill>
                    )}
                  </td>
                  <td className="px-4 py-2 text-end">
                    <div className="flex items-center justify-end gap-3">
                      <Link
                        to={`/decision-trees/${tree.code}`}
                        className="text-xs font-medium text-ap-primary hover:underline"
                      >
                        {t("list.row.open")}
                      </Link>
                      {canManage && tree.tenant_id != null ? (
                        tree.archived ? (
                          <button
                            type="button"
                            onClick={() => restore.mutate({ code: tree.code })}
                            disabled={restore.isPending}
                            className="text-xs font-medium text-ap-primary hover:underline disabled:opacity-50"
                          >
                            {restore.isPending ? t("list.row.restoring") : t("list.row.restore")}
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setArchiveTarget(tree)}
                            className="text-xs font-medium text-ap-crit hover:underline"
                          >
                            {t("list.row.archive")}
                          </button>
                        )
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

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

function FilterSelect({
  label,
  value,
  onChange,
  options,
  allLabel,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  options: Array<{ value: string; label: string }>;
  allLabel?: string;
}): ReactNode {
  return (
    <label className="flex flex-col gap-1 text-xs">
      <span className="font-medium text-ap-muted">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-md border border-ap-line bg-white px-2 py-1.5 text-sm shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
      >
        {allLabel !== undefined ? <option value={NO_FILTER}>{allLabel}</option> : null}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
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
