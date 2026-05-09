import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ResolvedSetting } from "@/api/integrations";
import type { Category } from "@/api/platformTenantIntegrations";
import { Skeleton } from "@/components/Skeleton";
import { SourcePill } from "@/modules/settings/components/SourcePill";
import {
  useClearPlatformTenantIntegration,
  usePlatformTenantIntegration,
  usePutPlatformTenantIntegration,
} from "@/queries/platformTenantIntegrations";

interface Props {
  tenantId: string;
}

const CATEGORIES: Category[] = ["weather", "imagery", "email", "webhook"];

/**
 * /platform/tenants/:id Integrations tab. Per-category sections, each
 * showing the resolved tenant-tier values with inline edit. Writes
 * land in `tenant_settings_overrides` so TenantOwner can later edit
 * them in Agri.Pulse — Platform's values just seed the defaults.
 */
export function TenantIntegrationsPanel({ tenantId }: Props): ReactNode {
  const { t } = useTranslation("admin");
  return (
    <div className="flex flex-col gap-4">
      <header>
        <h2 className="text-sm font-semibold text-ap-ink">
          {t("integrations.title")}
        </h2>
        <p className="mt-1 text-xs text-ap-muted">
          {t("integrations.subtitle")}
        </p>
      </header>
      {CATEGORIES.map((category) => (
        <CategorySection
          key={category}
          tenantId={tenantId}
          category={category}
        />
      ))}
    </div>
  );
}

function CategorySection({
  tenantId,
  category,
}: {
  tenantId: string;
  category: Category;
}): ReactNode {
  const { t } = useTranslation("admin");
  const q = usePlatformTenantIntegration(tenantId, category);
  const put = usePutPlatformTenantIntegration(tenantId, category);
  const clear = useClearPlatformTenantIntegration(tenantId, category);

  return (
    <section className="rounded-xl border border-ap-line bg-ap-panel p-4">
      <h3 className="text-sm font-semibold capitalize text-ap-ink">
        {t(`integrations.category.${category}`)}
      </h3>
      {q.isLoading ? (
        <Skeleton className="mt-3 h-16 w-full" />
      ) : q.isError ? (
        <p className="mt-3 text-sm text-ap-crit">{t("integrations.loadFailed")}</p>
      ) : (
        <div className="mt-3 divide-y divide-ap-line">
          {(q.data?.settings ?? []).map((s) => (
            <SettingRow
              key={s.key}
              setting={s}
              onSave={(key, value) => put.mutate({ key, value })}
              onClear={(key) => clear.mutate(key)}
              busy={put.isPending || clear.isPending}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function SettingRow({
  setting,
  onSave,
  onClear,
  busy,
}: {
  setting: ResolvedSetting;
  onSave: (key: string, value: unknown) => void;
  onClear: (key: string) => void;
  busy: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const [draft, setDraft] = useState(formatValue(setting.value));
  useEffect(() => setDraft(formatValue(setting.value)), [setting.value]);
  const dirty = draft !== formatValue(setting.value);
  const isTenantSet = setting.source === "tenant";
  return (
    <div className="flex flex-wrap items-center gap-2 py-2">
      <code className="font-mono text-xs text-ap-muted">{setting.key}</code>
      <SourcePill source={setting.source} />
      <input
        className="flex-1 rounded-md border border-ap-line bg-white px-2 py-1 text-sm font-mono"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <button
        type="button"
        disabled={!dirty || busy}
        onClick={() => onSave(setting.key, parseValue(draft))}
        className="rounded-md bg-ap-primary px-2 py-1 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
      >
        {t("integrations.save")}
      </button>
      {isTenantSet ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => onClear(setting.key)}
          className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
        >
          {t("integrations.clear")}
        </button>
      ) : null}
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
