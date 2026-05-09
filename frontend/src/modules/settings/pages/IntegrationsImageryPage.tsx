import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import type { ResolvedSetting } from "@/api/integrations";
import { listFarms } from "@/api/farms";
import { Skeleton } from "@/components/Skeleton";
import { SourcePill } from "@/modules/settings/components/SourcePill";
import {
  useApplyImageryToBlocks,
  useFarmImagery,
  usePutFarmImagery,
  usePutTenantIntegration,
  useTenantIntegration,
} from "@/queries/integrations";

export function IntegrationsImageryPage(): ReactNode {
  const { t } = useTranslation("integrations");
  const tenantQ = useTenantIntegration("imagery");
  const putTenant = usePutTenantIntegration("imagery");

  const [selectedFarmId, setSelectedFarmId] = useState<string | null>(null);
  const farmsQ = useQuery({
    queryKey: ["farms", "list-tenant"],
    queryFn: () => listFarms(),
    staleTime: 60_000,
  });

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-xl font-semibold text-ap-ink">{t("imagery.title")}</h1>
        <p className="mt-1 text-sm text-ap-muted">{t("imagery.subtitle")}</p>
      </header>

      <section className="rounded-xl border border-ap-line bg-ap-panel p-4">
        <h2 className="text-sm font-semibold text-ap-ink">
          {t("section.tenant")}
        </h2>
        {tenantQ.isLoading ? (
          <Skeleton className="mt-3 h-24 w-full" />
        ) : tenantQ.isError ? (
          <p className="mt-3 text-sm text-ap-crit">{t("loadFailed")}</p>
        ) : (
          <SettingsList
            settings={tenantQ.data?.settings ?? []}
            onSave={(key, value) => putTenant.mutate({ key, value })}
            isPending={putTenant.isPending}
          />
        )}
      </section>

      <section className="rounded-xl border border-ap-line bg-ap-panel p-4">
        <h2 className="text-sm font-semibold text-ap-ink">{t("section.farm")}</h2>
        <p className="mt-1 text-xs text-ap-muted">{t("section.farmHint")}</p>

        <label className="mt-3 flex items-center gap-2 text-sm">
          <span className="text-ap-muted">{t("farm.pickFarmLabel")}</span>
          <select
            className="rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
            value={selectedFarmId ?? ""}
            onChange={(e) => setSelectedFarmId(e.target.value || null)}
          >
            <option value="">{t("farm.pickFarm")}</option>
            {(farmsQ.data?.items ?? []).map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
        </label>

        {selectedFarmId ? <FarmImageryForm farmId={selectedFarmId} /> : null}
      </section>
    </div>
  );
}

function SettingsList({
  settings,
  onSave,
  isPending,
}: {
  settings: ResolvedSetting[];
  onSave: (key: string, value: unknown) => void;
  isPending: boolean;
}): ReactNode {
  return (
    <div className="mt-3 divide-y divide-ap-line">
      {settings.map((s) => (
        <SettingRow key={s.key} setting={s} onSave={onSave} isPending={isPending} />
      ))}
    </div>
  );
}

function SettingRow({
  setting,
  onSave,
  isPending,
}: {
  setting: ResolvedSetting;
  onSave: (key: string, value: unknown) => void;
  isPending: boolean;
}): ReactNode {
  const { t } = useTranslation("integrations");
  const [draft, setDraft] = useState(() => formatValue(setting.value));
  useEffect(() => setDraft(formatValue(setting.value)), [setting.value]);
  const dirty = draft !== formatValue(setting.value);
  return (
    <div className="flex flex-wrap items-center gap-2 py-2">
      <code className="font-mono text-xs text-ap-muted">{setting.key}</code>
      <SourcePill source={setting.source} />
      <input
        className="flex-1 rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <button
        type="button"
        disabled={!dirty || isPending}
        onClick={() => onSave(setting.key, parseValue(draft))}
        className="rounded-md bg-ap-primary px-2 py-1 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
      >
        {t("save")}
      </button>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function parseValue(raw: string): unknown {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const asNum = Number(trimmed);
  if (!Number.isNaN(asNum) && /^-?\d+(\.\d+)?$/.test(trimmed)) return asNum;
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return trimmed;
  }
}

function FarmImageryForm({ farmId }: { farmId: string }): ReactNode {
  const { t } = useTranslation("integrations");
  const farmQ = useFarmImagery(farmId);
  const putFarm = usePutFarmImagery();
  const apply = useApplyImageryToBlocks();
  const [productCode, setProductCode] = useState("");
  const [cloudPct, setCloudPct] = useState("");

  useEffect(() => {
    const s = farmQ.data?.settings ?? [];
    const prod = s.find((x) => x.key === "imagery.default_product_code");
    const cloud = s.find((x) => x.key === "imagery.cloud_cover_threshold_pct");
    setProductCode(prod && prod.source === "farm" ? String(prod.value) : "");
    setCloudPct(cloud && cloud.source === "farm" ? String(cloud.value) : "");
  }, [farmQ.data]);

  if (farmQ.isLoading) return <Skeleton className="mt-3 h-24 w-full" />;
  if (farmQ.isError) {
    return <p className="mt-3 text-sm text-ap-crit">{t("loadFailed")}</p>;
  }

  return (
    <div className="mt-3 flex flex-col gap-3">
      <table className="text-sm">
        <thead className="text-xs uppercase text-ap-muted">
          <tr>
            <th className="text-start">{t("col.key")}</th>
            <th className="text-start">{t("col.resolved")}</th>
            <th className="text-start">{t("col.source")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ap-line">
          {(farmQ.data?.settings ?? []).map((s) => (
            <tr key={s.key}>
              <td className="py-2 pr-4 font-mono text-xs">{s.key}</td>
              <td className="py-2 pr-4 text-ap-ink">{formatValue(s.value)}</td>
              <td className="py-2"><SourcePill source={s.source} /></td>
            </tr>
          ))}
        </tbody>
      </table>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          putFarm.mutate({
            farmId,
            payload: {
              product_code: productCode.trim() || null,
              cloud_cover_threshold_pct: cloudPct.trim() ? Number(cloudPct) : null,
            },
          });
        }}
        className="flex flex-wrap items-end gap-2"
      >
        <label className="flex flex-col text-xs">
          {t("imagery.productLabel")}
          <input
            className="mt-1 rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
            value={productCode}
            placeholder={t("farm.inheritPlaceholder")}
            onChange={(e) => setProductCode(e.target.value)}
          />
        </label>
        <label className="flex flex-col text-xs">
          {t("imagery.cloudPctLabel")}
          <input
            type="number"
            min={0}
            max={100}
            className="mt-1 w-24 rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
            value={cloudPct}
            placeholder={t("farm.inheritPlaceholder")}
            onChange={(e) => setCloudPct(e.target.value)}
          />
        </label>
        <button
          type="submit"
          disabled={putFarm.isPending}
          className="rounded-md bg-ap-primary px-3 py-1 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {t("save")}
        </button>
      </form>

      <div className="flex flex-wrap items-center gap-2 border-t border-ap-line pt-3">
        <span className="text-xs text-ap-muted">
          {t("imagery.applyToBlocksHint")}
        </span>
        <button
          type="button"
          onClick={() => apply.mutate({ farmId, mode: "inherit" })}
          disabled={apply.isPending}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
        >
          {t("imagery.applyInherit")}
        </button>
        <button
          type="button"
          onClick={() => apply.mutate({ farmId, mode: "lock" })}
          disabled={apply.isPending}
          className="rounded-md bg-ap-warn/10 px-2 py-1 text-xs font-medium text-ap-warn hover:bg-ap-warn/20"
        >
          {t("imagery.applyLock")}
        </button>
        {apply.data ? (
          <span className="text-xs text-ap-muted">
            {t("imagery.applyResult", { n: apply.data.blocks_affected })}
          </span>
        ) : null}
      </div>
    </div>
  );
}
