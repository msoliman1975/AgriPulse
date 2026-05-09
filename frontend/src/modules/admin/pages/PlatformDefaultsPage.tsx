import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { PlatformDefault, ValueSchema } from "@/api/platformDefaults";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useCapability } from "@/rbac/useCapability";
import {
  usePlatformDefaults,
  useUpdatePlatformDefault,
} from "@/queries/platformDefaults";

/**
 * /admin/defaults — PlatformAdmin can edit `public.platform_defaults`.
 * Rows grouped by category. Each row has an inline editor that
 * validates against the row's value_schema before submit so the user
 * sees the error in their browser instead of a 400 round-trip.
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
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <header>
        <h1 className="text-2xl font-semibold text-ap-ink">
          {t("defaults.title")}
        </h1>
        <p className="mt-1 text-sm text-ap-muted">{t("defaults.subtitle")}</p>
        {!canManage ? (
          <p className="mt-2 text-xs text-ap-warn">
            {t("defaults.readonlyHint")}
          </p>
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
          <section
            key={category}
            className="rounded-xl border border-ap-line bg-ap-panel"
          >
            <h2 className="border-b border-ap-line px-4 py-2 text-sm font-semibold capitalize text-ap-ink">
              {category}
            </h2>
            <div className="divide-y divide-ap-line">
              {rows.map((row) => (
                <DefaultRow key={row.key} row={row} canManage={canManage} />
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

function DefaultRow({
  row,
  canManage,
}: {
  row: PlatformDefault;
  canManage: boolean;
}): ReactNode {
  const { t } = useTranslation("admin");
  const update = useUpdatePlatformDefault();
  const [draft, setDraft] = useState(formatValue(row.value));
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setDraft(formatValue(row.value));
  }, [row.value]);

  const dirty = draft !== formatValue(row.value);

  const onSave = (): void => {
    setErr(null);
    let parsed: unknown;
    try {
      parsed = parseAndValidate(draft, row.value_schema);
    } catch (e) {
      setErr((e as Error).message);
      return;
    }
    update.mutate(
      { key: row.key, value: parsed },
      {
        onError: (e) => setErr((e as Error).message),
      },
    );
  };

  return (
    <div className="flex flex-col gap-1 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <code className="font-mono text-xs text-ap-primary">{row.key}</code>
        <Pill kind="neutral">{row.value_schema}</Pill>
        {row.description ? (
          <span className="text-xs text-ap-muted">{row.description}</span>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <input
          className="flex-1 rounded-md border border-ap-line bg-white px-2 py-1 text-sm font-mono"
          value={draft}
          disabled={!canManage}
          onChange={(e) => setDraft(e.target.value)}
        />
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
      </div>
      {err ? <p className="text-xs text-ap-crit">{err}</p> : null}
      <p className="text-[11px] text-ap-muted">
        {t("defaults.lastUpdated", { when: row.updated_at })}
      </p>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function parseAndValidate(raw: string, schema: ValueSchema): unknown {
  const trimmed = raw.trim();
  if (schema === "string") {
    return trimmed;
  }
  if (schema === "number") {
    const n = Number(trimmed);
    if (!Number.isFinite(n)) {
      throw new Error(`Expected a number; got ${trimmed || "(empty)"}.`);
    }
    return n;
  }
  if (schema === "boolean") {
    if (trimmed === "true") return true;
    if (trimmed === "false") return false;
    throw new Error("Expected `true` or `false`.");
  }
  // object / array — JSON-parse, then assert.
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    throw new Error("Expected valid JSON.");
  }
  if (schema === "array" && !Array.isArray(parsed)) {
    throw new Error("Expected a JSON array.");
  }
  if (schema === "object" && (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))) {
    throw new Error("Expected a JSON object.");
  }
  return parsed;
}
