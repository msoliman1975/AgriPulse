// Tenant-side UI for customizing a tree's declared parameters (PR-D3
// consumer of PR-C's REST surface).
//
// For each parameter declared on the tree's *current published
// version*, surfaces: the declared default, the tenant's current
// override (if any), and an inline input bound to the parameter's
// type. Save → PUT, Clear → DELETE.
//
// Unlike `ParametersPanel`, which edits the tree's YAML (author side),
// this panel writes per-(tenant, tree, param) rows in the
// `tree_parameter_overrides` table. The two surfaces co-exist on the
// viewer page: an author sees both (and can author + override), a
// tenant viewing a platform tree sees only this panel.

import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Skeleton } from "@/components/Skeleton";
import {
  useDeleteTreeParameterOverride,
  useTreeParameterOverrides,
  useUpsertTreeParameterOverride,
} from "@/queries/parameterOverrides";

import type { ParameterDeclaration } from "../lib/parametersEdit";

interface ParameterOverridesPanelProps {
  code: string;
  canManage: boolean;
}

export function ParameterOverridesPanel({
  code,
  canManage,
}: ParameterOverridesPanelProps): JSX.Element {
  const { t } = useTranslation("decisionTrees");
  const q = useTreeParameterOverrides(code);
  const upsert = useUpsertTreeParameterOverride(code);
  const remove = useDeleteTreeParameterOverride(code);

  if (q.isLoading) {
    return (
      <aside className="flex flex-col gap-3 rounded-xl border border-ap-line bg-ap-panel p-4">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="h-24 w-full" />
      </aside>
    );
  }
  if (q.isError || !q.data) {
    return (
      <aside className="rounded-xl border border-ap-line bg-ap-panel p-4 text-sm text-ap-crit">
        {t("overrides.loadFailed")}
      </aside>
    );
  }

  const { declarations, overrides } = q.data;
  const names = Object.keys(declarations);

  return (
    <aside className="flex flex-col gap-3 rounded-xl border border-ap-line bg-ap-panel p-4">
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-ap-ink">{t("overrides.heading")}</h2>
        {!canManage ? (
          <span className="text-xs text-ap-muted">{t("overrides.readOnlyHint")}</span>
        ) : null}
      </header>

      {names.length === 0 ? (
        <p className="rounded-md border border-dashed border-ap-line p-4 text-center text-xs text-ap-muted">
          {t("overrides.empty")}
        </p>
      ) : null}

      <div className="flex flex-col divide-y divide-ap-line">
        {names.sort().map((name) => (
          <OverrideRow
            key={name}
            name={name}
            // ParameterOverridesResponse declares `type` as plain
            // string; narrow at the boundary so the row's `<input>`
            // dispatch can rely on the union.
            decl={normalizeDecl(declarations[name])}
            current={name in overrides ? overrides[name] : undefined}
            canEdit={canManage}
            saving={upsert.isPending}
            clearing={remove.isPending}
            onSave={(value) => upsert.mutate({ paramName: name, value })}
            onClear={() => remove.mutate({ paramName: name })}
          />
        ))}
      </div>

      {upsert.isError ? (
        <p className="rounded-md border border-ap-crit/40 bg-ap-crit/10 p-2 text-xs text-ap-crit">
          {t("overrides.saveFailed")}
        </p>
      ) : null}
    </aside>
  );
}

// Coerce the API shape to the local ParameterDeclaration union. The
// REST schema's `type` is plain string; we trust the backend to have
// already validated it.
function normalizeDecl(raw: {
  type: string;
  default: unknown;
  description?: string | null;
  min?: number | null;
  max?: number | null;
  values?: unknown[] | null;
}): ParameterDeclaration {
  const type = (["number", "integer", "boolean", "string", "enum"].includes(raw.type)
    ? raw.type
    : "string") as ParameterDeclaration["type"];
  return {
    type,
    default: raw.default,
    description: raw.description ?? null,
    min: raw.min ?? null,
    max: raw.max ?? null,
    values: raw.values ?? null,
  };
}

// ---- Row ----------------------------------------------------------

function OverrideRow({
  name,
  decl,
  current,
  canEdit,
  saving,
  clearing,
  onSave,
  onClear,
}: {
  name: string;
  decl: ParameterDeclaration;
  current: unknown;
  canEdit: boolean;
  saving: boolean;
  clearing: boolean;
  onSave: (value: unknown) => void;
  onClear: () => void;
}): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const [draft, setDraft] = useState<unknown>(current ?? decl.default);
  // Track whether the input has diverged from the persisted state so
  // the Save button only enables when there's actually a change.
  const isDirty = JSON.stringify(draft) !== JSON.stringify(current ?? decl.default);
  const hasOverride = current !== undefined;

  return (
    <div className="flex flex-col gap-2 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="break-all font-mono text-sm text-ap-ink">{name}</span>
        <span className="font-mono text-[10px] text-ap-muted">{decl.type}</span>
      </div>
      {decl.description ? (
        <p className="text-xs text-ap-muted">{decl.description}</p>
      ) : null}
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <span className="block text-ap-muted">{t("overrides.fields.default")}</span>
          <span className="block font-mono text-ap-ink">
            {JSON.stringify(decl.default)}
          </span>
        </div>
        <div>
          <span className="block text-ap-muted">{t("overrides.fields.current")}</span>
          <span className="block font-mono text-ap-ink">
            {hasOverride ? JSON.stringify(current) : t("overrides.fields.usingDefault")}
          </span>
        </div>
      </div>
      {canEdit ? (
        <div className="flex items-end gap-2">
          <label className="flex flex-1 flex-col gap-1 text-xs">
            <span className="text-ap-muted">{t("overrides.fields.newValue")}</span>
            <OverrideInput decl={decl} value={draft} onChange={setDraft} />
          </label>
          <button
            type="button"
            disabled={!isDirty || saving}
            onClick={() => onSave(draft)}
            className="rounded-md bg-ap-primary px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
          >
            {saving ? t("overrides.saving") : t("overrides.save")}
          </button>
          {hasOverride ? (
            <button
              type="button"
              disabled={clearing}
              onClick={onClear}
              className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs disabled:opacity-50"
            >
              {clearing ? t("overrides.clearing") : t("overrides.clear")}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// Reuses the same dispatch logic as the author's DefaultInput, but
// independent so the two can evolve separately (override values may
// gain stricter UI like sliders later).
function OverrideInput({
  decl,
  value,
  onChange,
}: {
  decl: ParameterDeclaration;
  value: unknown;
  onChange: (next: unknown) => void;
}): JSX.Element {
  switch (decl.type) {
    case "boolean":
      return (
        <select
          value={String(value)}
          onChange={(e) => onChange(e.target.value === "true")}
          className="rounded-md border border-ap-line bg-ap-bg/40 px-2 py-1 text-sm text-ap-ink"
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      );
    case "number":
    case "integer":
      return (
        <input
          type="number"
          value={typeof value === "number" ? value : Number(value) || 0}
          min={decl.min ?? undefined}
          max={decl.max ?? undefined}
          step={decl.type === "integer" ? 1 : "any"}
          onChange={(e) => {
            const v = Number(e.target.value);
            if (!Number.isNaN(v)) onChange(decl.type === "integer" ? Math.round(v) : v);
          }}
          className="rounded-md border border-ap-line bg-ap-bg/40 px-2 py-1 text-sm text-ap-ink"
        />
      );
    case "enum":
      return (
        <select
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
          className="rounded-md border border-ap-line bg-ap-bg/40 px-2 py-1 text-sm text-ap-ink"
        >
          {(decl.values ?? []).map((v) => (
            <option key={String(v)} value={String(v)}>
              {String(v)}
            </option>
          ))}
        </select>
      );
    case "string":
    default:
      return (
        <input
          type="text"
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          className="rounded-md border border-ap-line bg-ap-bg/40 px-2 py-1 text-sm text-ap-ink"
        />
      );
  }
}
