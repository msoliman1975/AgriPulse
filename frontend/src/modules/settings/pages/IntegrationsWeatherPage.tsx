import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ResolvedSetting } from "@/api/integrations";
import { Skeleton } from "@/components/Skeleton";
import { listFarms } from "@/api/farms";
import { useQuery } from "@tanstack/react-query";
import { SourcePill } from "@/modules/settings/components/SourcePill";
import {
  useFarmWeather,
  usePutFarmWeather,
  usePutTenantIntegration,
  useTenantIntegration,
} from "@/queries/integrations";

/**
 * /settings/integrations/weather — tenant defaults form on top, then a
 * Farm picker that shows the resolved chain for one Farm and lets the
 * user override at the Farm tier.
 */
export function IntegrationsWeatherPage(): ReactNode {
  const { t } = useTranslation("integrations");
  const tenantQ = useTenantIntegration("weather");
  const putTenant = usePutTenantIntegration("weather");

  const [selectedFarmId, setSelectedFarmId] = useState<string | null>(null);
  const farmsQ = useQuery({
    queryKey: ["farms", "list-tenant"],
    queryFn: () => listFarms(),
    staleTime: 60_000,
  });

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-xl font-semibold text-ap-ink">{t("weather.title")}</h1>
        <p className="mt-1 text-sm text-ap-muted">{t("weather.subtitle")}</p>
      </header>

      {/* Tenant tier */}
      <section className="rounded-xl border border-ap-line bg-ap-panel p-4">
        <h2 className="text-sm font-semibold text-ap-ink">
          {t("section.tenant")}
        </h2>
        {tenantQ.isLoading ? (
          <Skeleton className="mt-3 h-24 w-full" />
        ) : tenantQ.isError ? (
          <p className="mt-3 text-sm text-ap-crit">{t("loadFailed")}</p>
        ) : (
          <SettingTable
            settings={tenantQ.data?.settings ?? []}
            onSave={(key, value) =>
              putTenant.mutate({ key, value })
            }
            isPending={putTenant.isPending}
          />
        )}
      </section>

      {/* Farm tier */}
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

        {selectedFarmId ? (
          <FarmWeatherForm farmId={selectedFarmId} />
        ) : null}
      </section>
    </div>
  );
}

function SettingTable({
  settings,
  onSave,
  isPending,
}: {
  settings: ResolvedSetting[];
  onSave: (key: string, value: unknown) => void;
  isPending: boolean;
}): ReactNode {
  const { t } = useTranslation("integrations");
  return (
    <div className="mt-3 divide-y divide-ap-line">
      {settings.map((s) => (
        <SettingRow key={s.key} setting={s} onSave={onSave} isPending={isPending} />
      ))}
      {settings.length === 0 ? (
        <p className="py-2 text-sm text-ap-muted">{t("noSettings")}</p>
      ) : null}
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
  useEffect(() => {
    setDraft(formatValue(setting.value));
  }, [setting.value]);
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
  // Try as number first.
  const asNum = Number(trimmed);
  if (!Number.isNaN(asNum) && /^-?\d+(\.\d+)?$/.test(trimmed)) return asNum;
  // Try as JSON (true/false/array/object).
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return trimmed;
  }
}

function FarmWeatherForm({ farmId }: { farmId: string }): ReactNode {
  const { t } = useTranslation("integrations");
  const farmQ = useFarmWeather(farmId);
  const putFarm = usePutFarmWeather();
  const [provider, setProvider] = useState<string>("");
  const [cadence, setCadence] = useState<string>("");

  useEffect(() => {
    const settings = farmQ.data?.settings ?? [];
    const provSetting = settings.find(
      (s) => s.key === "weather.default_provider_code",
    );
    const cadSetting = settings.find(
      (s) => s.key === "weather.default_cadence_hours",
    );
    setProvider(
      provSetting && provSetting.source === "farm" ? String(provSetting.value) : "",
    );
    setCadence(
      cadSetting && cadSetting.source === "farm" ? String(cadSetting.value) : "",
    );
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
              provider_code: provider.trim() || null,
              cadence_hours: cadence.trim() ? Number(cadence) : null,
            },
          });
        }}
        className="flex flex-wrap items-end gap-2"
      >
        <label className="flex flex-col text-xs">
          {t("farm.providerLabel")}
          <input
            className="mt-1 rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
            value={provider}
            placeholder={t("farm.inheritPlaceholder")}
            onChange={(e) => setProvider(e.target.value)}
          />
        </label>
        <label className="flex flex-col text-xs">
          {t("farm.cadenceLabel")}
          <input
            type="number"
            min={1}
            max={168}
            className="mt-1 w-24 rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
            value={cadence}
            placeholder={t("farm.inheritPlaceholder")}
            onChange={(e) => setCadence(e.target.value)}
          />
        </label>
        <button
          type="submit"
          disabled={putFarm.isPending}
          className="rounded-md bg-ap-primary px-3 py-1 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {t("save")}
        </button>
        <button
          type="button"
          onClick={() => {
            putFarm.mutate({
              farmId,
              payload: { provider_code: null, cadence_hours: null },
            });
          }}
          disabled={putFarm.isPending}
          className="rounded-md border border-ap-line bg-ap-panel px-3 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
        >
          {t("farm.resetButton")}
        </button>
      </form>
    </div>
  );
}
