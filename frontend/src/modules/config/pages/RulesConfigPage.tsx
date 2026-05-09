import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  AlertSeverity,
  DefaultRule,
  RuleOverride,
  RuleOverrideUpsertPayload,
  TenantRule,
  TenantRuleCreatePayload,
  TenantRuleUpdatePayload,
} from "@/api/alerts";
import { Pill } from "@/components/Pill";
import { SegmentedControl } from "@/components/SegmentedControl";
import { Skeleton } from "@/components/Skeleton";
import { useCapability } from "@/rbac/useCapability";
import {
  useCreateTenantRule,
  useDefaultRules,
  useDeleteTenantRule,
  useRuleOverrides,
  useTenantRules,
  useUpdateTenantRule,
  useUpsertRuleOverride,
} from "@/queries/alerts";

const SEVERITIES: ReadonlyArray<AlertSeverity> = ["info", "warning", "critical"];

const SEV_KIND: Record<AlertSeverity, "info" | "warn" | "crit"> = {
  info: "info",
  warning: "warn",
  critical: "crit",
};

interface MergedRule {
  rule: DefaultRule;
  override: RuleOverride | null;
  effectiveSeverity: AlertSeverity;
  isDisabled: boolean;
  hasOverride: boolean;
}

export function RulesConfigPage(): ReactNode {
  const { t, i18n } = useTranslation("rules");
  const canManage = useCapability("alert_rule.manage");
  const [tab, setTab] = useState<"platform" | "tenant">("platform");

  const defaults = useDefaultRules();
  const overrides = useRuleOverrides();

  const merged = useMemo<MergedRule[]>(() => {
    if (!defaults.data) return [];
    const overrideByCode = new Map<string, RuleOverride>();
    for (const o of overrides.data ?? []) overrideByCode.set(o.rule_code, o);
    return defaults.data.map((rule) => {
      const override = overrideByCode.get(rule.code) ?? null;
      const effectiveSeverity = (override?.modified_severity ?? rule.severity) as AlertSeverity;
      return {
        rule,
        override,
        effectiveSeverity,
        isDisabled: Boolean(override?.is_disabled),
        hasOverride:
          override != null &&
          (override.is_disabled ||
            override.modified_severity != null ||
            override.modified_conditions != null ||
            override.modified_actions != null),
      };
    });
  }, [defaults.data, overrides.data]);

  const isLoading = defaults.isLoading || overrides.isLoading;
  const isError = defaults.isError || overrides.isError;
  const isAr = i18n.language === "ar";

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ap-ink">{t("page.title")}</h1>
          <p className="mt-1 text-sm text-ap-muted">{t("page.subtitle")}</p>
        </div>
        <SegmentedControl
          ariaLabel="Rule source"
          items={[
            { value: "platform", label: t("tabs.platform") },
            { value: "tenant", label: t("tabs.tenant") },
          ]}
          value={tab}
          onChange={(v) => setTab(v)}
        />
      </header>

      {tab === "platform" ? (
        <div className="rounded-xl border border-ap-line bg-ap-panel">
          {isLoading ? (
            <div className="flex flex-col gap-2 p-4">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : isError ? (
            <p className="p-4 text-sm text-ap-crit">{t("page.loadFailed")}</p>
          ) : merged.length === 0 ? (
            <p className="p-12 text-center text-sm text-ap-muted">{t("page.empty")}</p>
          ) : (
            <ul className="divide-y divide-ap-line">
              {merged.map((m) => (
                <RuleRow
                  key={m.rule.code}
                  merged={m}
                  isAr={isAr}
                  canManage={canManage}
                />
              ))}
            </ul>
          )}
        </div>
      ) : (
        <TenantRulesSection canManage={canManage} isAr={isAr} />
      )}
    </div>
  );
}

function RuleRow({
  merged,
  isAr,
  canManage,
}: {
  merged: MergedRule;
  isAr: boolean;
  canManage: boolean;
}): ReactNode {
  const { t } = useTranslation("rules");
  const upsert = useUpsertRuleOverride();
  const [expanded, setExpanded] = useState(false);
  // Edit-buffer pre-populated with whatever the override currently is so
  // an immediate "Save" with no UI change is a no-op (button disabled).
  const [bufferDisabled, setBufferDisabled] = useState(merged.isDisabled);
  const [bufferSeverity, setBufferSeverity] = useState<AlertSeverity | "default">(
    merged.override?.modified_severity ?? "default",
  );

  const dirty =
    bufferDisabled !== merged.isDisabled ||
    (bufferSeverity === "default"
      ? merged.override?.modified_severity != null
      : bufferSeverity !== merged.override?.modified_severity);

  const name = (isAr ? merged.rule.name_ar : merged.rule.name_en) ?? merged.rule.name_en;
  const description =
    (isAr ? merged.rule.description_ar : merged.rule.description_en) ??
    merged.rule.description_en;

  const save = (): void => {
    const payload: RuleOverrideUpsertPayload = {
      is_disabled: bufferDisabled,
      modified_severity: bufferSeverity === "default" ? null : bufferSeverity,
      // Preserve any conditions/actions overrides the API set previously —
      // we don't surface them in the UI yet, but blowing them away on Save
      // would be surprising. Defer "edit conditions JSON" to a follow-up.
      modified_conditions: merged.override?.modified_conditions ?? null,
      modified_actions: merged.override?.modified_actions ?? null,
    };
    upsert.mutate({ ruleCode: merged.rule.code, payload });
  };

  const reset = (): void => {
    setBufferDisabled(false);
    setBufferSeverity("default");
    upsert.mutate({
      ruleCode: merged.rule.code,
      payload: {
        is_disabled: false,
        modified_severity: null,
        modified_conditions: null,
        modified_actions: null,
      },
    });
  };

  const cropTag =
    merged.rule.applies_to_crop_categories.length === 0
      ? t("table.appliesAll")
      : t("table.appliesSome", {
          categories: merged.rule.applies_to_crop_categories.join(", "),
        });

  return (
    <li className="flex flex-col gap-2 p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div
          aria-hidden="true"
          className={`mt-1 h-10 w-1 flex-none rounded-full ${
            merged.effectiveSeverity === "critical"
              ? "bg-ap-crit"
              : merged.effectiveSeverity === "warning"
                ? "bg-ap-warn"
                : "bg-ap-accent"
          }`}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-ap-ink">{name}</span>
            <span className="font-mono text-[11px] text-ap-muted">{merged.rule.code}</span>
            <Pill kind={SEV_KIND[merged.effectiveSeverity]}>
              {t(`severity.${merged.effectiveSeverity}`)}
            </Pill>
            <Pill kind={merged.rule.status === "active" ? "ok" : "neutral"}>
              {t(`status.${merged.rule.status}`)}
            </Pill>
            {merged.isDisabled ? (
              <Pill kind="crit">{t("row.disabled")}</Pill>
            ) : merged.hasOverride ? (
              <Pill kind="info">{t("row.overridden")}</Pill>
            ) : (
              <Pill kind="neutral">{t("row.default")}</Pill>
            )}
          </div>
          <div className="mt-1 text-[11px] text-ap-muted">{cropTag}</div>
          {description ? (
            <p className="mt-1 text-sm text-ap-muted">{description}</p>
          ) : null}
          <button
            type="button"
            onClick={() => setExpanded((s) => !s)}
            className="mt-2 text-[11px] font-medium text-ap-primary hover:underline"
          >
            {expanded ? t("row.collapse") : t("row.expand")}
          </button>
          {expanded ? (
            <div className="mt-2 grid gap-2 rounded-md border border-ap-line bg-ap-bg/40 p-3 text-[11px]">
              <div>
                <div className="mb-1 font-semibold text-ap-ink">
                  {t("row.conditionsHeader")}
                </div>
                <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[10px] text-ap-ink">
                  {JSON.stringify(merged.rule.conditions, null, 2)}
                </pre>
              </div>
              <div>
                <div className="mb-1 font-semibold text-ap-ink">
                  {t("row.actionsHeader")}
                </div>
                <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-[10px] text-ap-ink">
                  {JSON.stringify(merged.rule.actions, null, 2)}
                </pre>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {canManage ? (
        <div className="flex flex-wrap items-center gap-3 border-t border-ap-line pt-3 text-sm">
          <label className="inline-flex items-center gap-2">
            <input
              type="checkbox"
              checked={bufferDisabled}
              onChange={(e) => setBufferDisabled(e.target.checked)}
            />
            <span>{bufferDisabled ? t("row.disable") : t("row.enable")}</span>
          </label>
          <label className="inline-flex items-center gap-2">
            <span className="text-xs font-medium text-ap-muted">
              {t("row.severityOverride")}
            </span>
            <select
              value={bufferSeverity}
              onChange={(e) =>
                setBufferSeverity(e.target.value as AlertSeverity | "default")
              }
              className="rounded-md border border-ap-line bg-white px-2 py-1 text-sm shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
            >
              <option value="default">
                {t("row.severityNone", { severity: t(`severity.${merged.rule.severity}`) })}
              </option>
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {t(`severity.${s}`)}
                </option>
              ))}
            </select>
          </label>
          <div className="ms-auto flex gap-2">
            {merged.hasOverride ? (
              <button
                type="button"
                onClick={reset}
                disabled={upsert.isPending}
                className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40 disabled:opacity-60"
              >
                {upsert.isPending ? t("row.resetting") : t("row.reset")}
              </button>
            ) : null}
            <button
              type="button"
              onClick={save}
              disabled={!dirty || upsert.isPending}
              className="rounded-md bg-ap-primary px-3 py-1 text-xs font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
            >
              {upsert.isPending ? t("row.saving") : t("row.save")}
            </button>
          </div>
        </div>
      ) : (
        <p className="border-t border-ap-line pt-3 text-xs text-ap-muted">
          {t("row.missingCapability", { capability: "alert_rule.manage" })}
        </p>
      )}
      {upsert.isError ? (
        <p className="text-xs text-ap-crit">
          {(upsert.error as Error)?.message ?? t("row.saveFailed")}
        </p>
      ) : null}
    </li>
  );
}


// =====================================================================
// Tenant rules: list + create + edit
// =====================================================================


function TenantRulesSection({
  canManage,
  isAr,
}: {
  canManage: boolean;
  isAr: boolean;
}): ReactNode {
  const { t } = useTranslation("rules");
  const tenantRules = useTenantRules();
  const deleteMut = useDeleteTenantRule();
  const [editing, setEditing] = useState<TenantRule | "new" | null>(null);

  if (tenantRules.isLoading) {
    return (
      <div className="rounded-xl border border-ap-line bg-ap-panel p-4">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="mt-2 h-16 w-full" />
      </div>
    );
  }
  if (tenantRules.isError) {
    return (
      <div className="rounded-xl border border-ap-line bg-ap-panel p-4 text-sm text-ap-crit">
        {t("page.loadFailed")}
      </div>
    );
  }

  const rules = tenantRules.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      {editing ? (
        <TenantRuleForm
          existing={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      ) : null}

      <div className="rounded-xl border border-ap-line bg-ap-panel">
        <header className="flex items-center justify-between border-b border-ap-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ap-ink">{t("tabs.tenant")}</h2>
          {canManage ? (
            <button
              type="button"
              onClick={() => setEditing("new")}
              className="rounded-md bg-ap-primary px-3 py-1 text-xs font-medium text-white hover:bg-ap-primary/90"
            >
              {t("tenant.newButton")}
            </button>
          ) : null}
        </header>
        {rules.length === 0 ? (
          <p className="p-12 text-center text-sm text-ap-muted">{t("tenant.empty")}</p>
        ) : (
          <ul className="divide-y divide-ap-line">
            {rules.map((rule) => (
              <TenantRuleRow
                key={rule.id}
                rule={rule}
                isAr={isAr}
                canManage={canManage}
                onEdit={() => setEditing(rule)}
                onDelete={() => deleteMut.mutate(rule.code)}
              />
            ))}
          </ul>
        )}
        {deleteMut.isError ? (
          <p className="border-t border-ap-line p-3 text-xs text-ap-crit">
            {(deleteMut.error as Error)?.message}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function TenantRuleRow({
  rule,
  isAr,
  canManage,
  onEdit,
  onDelete,
}: {
  rule: TenantRule;
  isAr: boolean;
  canManage: boolean;
  onEdit: () => void;
  onDelete: () => void;
}): ReactNode {
  const { t } = useTranslation("rules");
  const name = (isAr ? rule.name_ar : rule.name_en) ?? rule.name_en;
  const description = (isAr ? rule.description_ar : rule.description_en) ?? rule.description_en;
  const cropTag =
    rule.applies_to_crop_categories.length === 0
      ? t("table.appliesAll")
      : t("table.appliesSome", { categories: rule.applies_to_crop_categories.join(", ") });
  return (
    <li className="flex items-start gap-3 p-4">
      <div
        aria-hidden="true"
        className={`mt-1 h-10 w-1 flex-none rounded-full ${
          rule.severity === "critical"
            ? "bg-ap-crit"
            : rule.severity === "warning"
              ? "bg-ap-warn"
              : "bg-ap-accent"
        }`}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-ap-ink">{name}</span>
          <span className="font-mono text-[11px] text-ap-muted">{rule.code}</span>
          <Pill kind={SEV_KIND[rule.severity]}>{t(`severity.${rule.severity}`)}</Pill>
          <Pill kind={rule.status === "active" ? "ok" : "neutral"}>
            {t(`status.${rule.status}`)}
          </Pill>
          <Pill kind="info">{t("tenant.row.tenantBadge")}</Pill>
        </div>
        <div className="mt-1 text-[11px] text-ap-muted">{cropTag}</div>
        {description ? <p className="mt-1 text-sm text-ap-muted">{description}</p> : null}
      </div>
      {canManage ? (
        <div className="flex flex-none gap-1">
          <button
            type="button"
            onClick={onEdit}
            className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
          >
            {t("tenant.row.edit")}
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="rounded-md border border-ap-line bg-ap-panel px-2 py-1 text-xs font-medium text-ap-ink hover:bg-ap-line/40"
          >
            {t("tenant.row.delete")}
          </button>
        </div>
      ) : null}
    </li>
  );
}

function TenantRuleForm({
  existing,
  onClose,
}: {
  existing: TenantRule | null;
  onClose: () => void;
}): ReactNode {
  const { t } = useTranslation("rules");
  const create = useCreateTenantRule();
  const update = useUpdateTenantRule();

  const [code, setCode] = useState(existing?.code ?? "");
  const [nameEn, setNameEn] = useState(existing?.name_en ?? "");
  const [nameAr, setNameAr] = useState(existing?.name_ar ?? "");
  const [descEn, setDescEn] = useState(existing?.description_en ?? "");
  const [descAr, setDescAr] = useState(existing?.description_ar ?? "");
  const [severity, setSeverity] = useState<AlertSeverity>(existing?.severity ?? "warning");
  const [crops, setCrops] = useState(existing?.applies_to_crop_categories.join(", ") ?? "");
  const [conditionsText, setConditionsText] = useState(
    JSON.stringify(
      existing?.conditions ?? {
        type: "condition_tree",
        tree: {
          op: "lt",
          left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
          right: -1,
        },
      },
      null,
      2,
    ),
  );
  const [actionsText, setActionsText] = useState(
    JSON.stringify(
      existing?.actions ?? {
        diagnosis_en: "Diagnosis text.",
        diagnosis_ar: "التشخيص.",
        prescription_en: "Recommended action.",
        prescription_ar: "الإجراء الموصى به.",
      },
      null,
      2,
    ),
  );
  const [error, setError] = useState<string | null>(null);

  const submit = (event: React.FormEvent): void => {
    event.preventDefault();
    setError(null);
    let conditions: Record<string, unknown>;
    let actions: Record<string, unknown>;
    try {
      conditions = JSON.parse(conditionsText);
      actions = JSON.parse(actionsText);
    } catch {
      setError(t("form.invalidJson"));
      return;
    }
    const cropsList = crops
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean);
    if (existing) {
      const payload: TenantRuleUpdatePayload = {
        name_en: nameEn,
        name_ar: nameAr || null,
        description_en: descEn || null,
        description_ar: descAr || null,
        severity,
        applies_to_crop_categories: cropsList,
        conditions,
        actions,
      };
      update.mutate(
        { code: existing.code, payload },
        { onSuccess: onClose },
      );
    } else {
      const payload: TenantRuleCreatePayload = {
        code: code.trim(),
        name_en: nameEn,
        name_ar: nameAr || null,
        description_en: descEn || null,
        description_ar: descAr || null,
        severity,
        applies_to_crop_categories: cropsList,
        conditions,
        actions,
      };
      create.mutate(payload, { onSuccess: onClose });
    }
  };

  const pending = create.isPending || update.isPending;
  const submitErr =
    (create.error as Error)?.message || (update.error as Error)?.message || null;

  return (
    <form
      onSubmit={submit}
      className="rounded-xl border border-ap-primary/40 bg-ap-panel p-4 shadow-sm"
    >
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-ap-ink">
          {existing ? t("form.editTitle") : t("form.title")}
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="text-xs font-medium text-ap-muted hover:text-ap-ink"
        >
          {t("form.cancel")}
        </button>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <FormField label={t("form.code")} hint={t("form.codeHint")}>
          <input
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder={t("form.codePlaceholder")}
            pattern="^[a-z0-9][a-z0-9_-]*$"
            disabled={Boolean(existing)}
            className={inputCls}
          />
        </FormField>
        <FormField label={t("form.severity")}>
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value as AlertSeverity)}
            className={inputCls}
          >
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {t(`severity.${s}`)}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label={t("form.name_en")}>
          <input
            required
            value={nameEn}
            onChange={(e) => setNameEn(e.target.value)}
            className={inputCls}
          />
        </FormField>
        <FormField label={t("form.name_ar")}>
          <input
            value={nameAr ?? ""}
            onChange={(e) => setNameAr(e.target.value)}
            className={inputCls}
          />
        </FormField>
        <FormField label={t("form.description_en")} className="sm:col-span-2">
          <input
            value={descEn ?? ""}
            onChange={(e) => setDescEn(e.target.value)}
            className={inputCls}
          />
        </FormField>
        <FormField label={t("form.description_ar")} className="sm:col-span-2">
          <input
            value={descAr ?? ""}
            onChange={(e) => setDescAr(e.target.value)}
            className={inputCls}
          />
        </FormField>
        <FormField label={t("form.appliesToCrops")} className="sm:col-span-2">
          <input
            value={crops}
            onChange={(e) => setCrops(e.target.value)}
            placeholder="citrus, mango"
            className={inputCls}
          />
        </FormField>
        <FormField
          label={t("form.conditions")}
          hint={t("form.conditionsHint")}
          className="sm:col-span-2"
        >
          <textarea
            required
            value={conditionsText}
            onChange={(e) => setConditionsText(e.target.value)}
            rows={10}
            spellCheck={false}
            className="w-full rounded-md border border-ap-line bg-ap-bg/40 px-2 py-1 font-mono text-[11px] shadow-inner focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
          />
        </FormField>
        <FormField
          label={t("form.actions")}
          hint={t("form.actionsHint")}
          className="sm:col-span-2"
        >
          <textarea
            required
            value={actionsText}
            onChange={(e) => setActionsText(e.target.value)}
            rows={8}
            spellCheck={false}
            className="w-full rounded-md border border-ap-line bg-ap-bg/40 px-2 py-1 font-mono text-[11px] shadow-inner focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
          />
        </FormField>
      </div>
      <div className="mt-3 flex items-center justify-end gap-2">
        {error || submitErr ? (
          <span className="text-xs text-ap-crit">{error ?? submitErr}</span>
        ) : null}
        <button
          type="submit"
          disabled={pending}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {pending ? t("form.saving") : t("form.save")}
        </button>
      </div>
    </form>
  );
}

const inputCls =
  "w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm text-ap-ink shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary disabled:bg-ap-line/30";

function FormField({
  label,
  hint,
  className,
  children,
}: {
  label: string;
  hint?: string;
  className?: string;
  children: ReactNode;
}): ReactNode {
  return (
    <label className={`flex flex-col gap-1 ${className ?? ""}`}>
      <span className="text-xs font-medium text-ap-muted">{label}</span>
      {children}
      {hint ? <span className="text-[11px] text-ap-muted">{hint}</span> : null}
    </label>
  );
}
