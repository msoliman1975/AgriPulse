import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ResolvedSetting } from "@/api/integrations";
import { Skeleton } from "@/components/Skeleton";
import { SourcePill } from "@/modules/settings/components/SourcePill";
import {
  usePutTenantIntegration,
  useTenantIntegration,
} from "@/queries/integrations";

interface Props {
  category: "email" | "webhook";
  i18nTitleKey: string;
  i18nSubtitleKey: string;
}

/**
 * Email + webhook are tenant-tier-only per the proposal V1. One page
 * lists the resolved keys with editable values.
 */
export function IntegrationsTenantOnlyPage({
  category,
  i18nTitleKey,
  i18nSubtitleKey,
}: Props): ReactNode {
  const { t } = useTranslation("integrations");
  const tenantQ = useTenantIntegration(category);
  const putTenant = usePutTenantIntegration(category);

  return (
    <div className="flex flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold text-ap-ink">{t(i18nTitleKey)}</h1>
        <p className="mt-1 text-sm text-ap-muted">{t(i18nSubtitleKey)}</p>
      </header>

      <section className="rounded-xl border border-ap-line bg-ap-panel p-4">
        {tenantQ.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : tenantQ.isError ? (
          <p className="text-sm text-ap-crit">{t("loadFailed")}</p>
        ) : (tenantQ.data?.settings ?? []).length === 0 ? (
          <p className="text-sm text-ap-muted">{t("noSettings")}</p>
        ) : (
          <div className="divide-y divide-ap-line">
            {(tenantQ.data?.settings ?? []).map((s) => (
              <SettingRow
                key={s.key}
                setting={s}
                onSave={(key, value) => putTenant.mutate({ key, value })}
                isPending={putTenant.isPending}
              />
            ))}
          </div>
        )}
      </section>
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
