import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { PlatformDefault } from "@/api/platformDefaults";
import {
  constraintHint,
  formatTimestamp,
  formatValue,
  parseAndValidate,
} from "@/modules/admin/lib/platformDefaultValue";
import { Page } from "@/components/Page";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useCapability } from "@/rbac/useCapability";
import { usePlatformDefaults, useUpdatePlatformDefault } from "@/queries/platformDefaults";

/**
 * /platform/defaults — PlatformAdmin can edit `public.platform_defaults`.
 * Rows grouped by category. Each row validates against the row's
 * value_schema *and* its server-supplied constraint before submit, so the
 * user sees the error in their browser instead of a 400 round-trip.
 */
export function PlatformDefaultsPage(): ReactNode {
  const { t } = useTranslation("admin");
  const canManage = useCapability("platform.manage_defaults");
  const { data, isLoading, isError } = usePlatformDefaults();

  const grouped = useMemo(() => {
    const map = new Map<string, PlatformDefault[]>();
    for (const d of data ?? []) {
      const list = map.get(d.category) ?? [];
      list.push(d);
      map.set(d.category, list);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [data]);

  return (
    <Page>
      <header>
        <h1 className="text-2xl font-semibold text-ap-ink">{t("defaults.title")}</h1>
        <p className="mt-1 text-sm text-ap-muted">{t("defaults.subtitle")}</p>
        {!canManage ? (
          <p className="mt-2 text-xs text-ap-warn">{t("defaults.readonlyHint")}</p>
        ) : null}
      </header>

      {isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : isError ? (
        <p className="text-sm text-ap-crit">{t("defaults.loadFailed")}</p>
      ) : grouped.length === 0 ? (
        <p className="text-sm text-ap-muted">{t("defaults.empty")}</p>
      ) : (
        grouped.map(([category, rows]) => (
          <section key={category} className="rounded-xl border border-ap-line bg-ap-panel">
            <h2 className="border-b border-ap-line px-4 py-2 text-sm font-semibold text-ap-ink">
              {t(`defaults.category.${category}`, { defaultValue: category })}
            </h2>
            <div className="divide-y divide-ap-line">
              {rows.map((row) => (
                <DefaultRow key={row.key} row={row} canManage={canManage} />
              ))}
            </div>
          </section>
        ))
      )}
    </Page>
  );
}

function DefaultRow({ row, canManage }: { row: PlatformDefault; canManage: boolean }): ReactNode {
  const { t, i18n } = useTranslation("admin");
  const update = useUpdatePlatformDefault();
  const [draft, setDraft] = useState(() => formatValue(row.value));
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setDraft(formatValue(row.value));
  }, [row.value]);

  // Clear the pending "Saved" timer if the row unmounts mid-flash.
  useEffect(() => {
    return () => {
      if (savedTimer.current) clearTimeout(savedTimer.current);
    };
  }, []);

  const dirty = draft !== formatValue(row.value);

  const onSave = (): void => {
    setErr(null);
    setSaved(false);
    let parsed: unknown;
    try {
      parsed = parseAndValidate(draft, row.value_schema, row.constraint);
    } catch (e) {
      setErr((e as Error).message);
      return;
    }
    update.mutate(
      { key: row.key, value: parsed },
      {
        onSuccess: () => {
          setSaved(true);
          if (savedTimer.current) clearTimeout(savedTimer.current);
          savedTimer.current = setTimeout(() => setSaved(false), 3000);
        },
        onError: (e) => setErr(e.message),
      },
    );
  };

  const hint = constraintHint(row.constraint);

  return (
    <div className="flex flex-col gap-1 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <code className="font-mono text-xs text-ap-primary">{row.key}</code>
        <Pill kind="neutral">{row.value_schema}</Pill>
        {hint ? <span className="font-mono text-[11px] text-ap-muted">{hint}</span> : null}
        {row.description ? <span className="text-xs text-ap-muted">{row.description}</span> : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {row.constraint?.choices ? (
          <select
            aria-label={row.key}
            className="flex-1 rounded-md border border-ap-line bg-white px-2 py-1 font-mono text-sm"
            value={draft}
            disabled={!canManage}
            onChange={(e) => setDraft(e.target.value)}
          >
            {row.constraint.choices.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        ) : (
          <input
            aria-label={row.key}
            className="flex-1 rounded-md border border-ap-line bg-white px-2 py-1 font-mono text-sm"
            value={draft}
            disabled={!canManage}
            onChange={(e) => setDraft(e.target.value)}
          />
        )}
        {canManage ? (
          <button
            type="button"
            disabled={!dirty || update.isPending}
            onClick={onSave}
            className="rounded-md bg-ap-primary px-2 py-1 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
          >
            {update.isPending ? t("defaults.saving") : t("defaults.save")}
          </button>
        ) : null}
        {saved ? (
          <span role="status" className="text-xs font-medium text-ap-ok">
            {t("defaults.saved")}
          </span>
        ) : null}
      </div>
      {err ? (
        <p role="alert" className="text-xs text-ap-crit">
          {err}
        </p>
      ) : null}
      <p className="text-[11px] text-ap-muted">
        {t("defaults.lastUpdated", { when: formatTimestamp(row.updated_at, i18n.language) })}
      </p>
    </div>
  );
}
