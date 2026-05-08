import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import type {
  AlertSeverity,
  DefaultRule,
  RuleOverride,
  RuleOverrideUpsertPayload,
} from "@/api/alerts";
import { Pill } from "@/components/Pill";
import { Skeleton } from "@/components/Skeleton";
import { useActiveFarmId } from "@/hooks/useActiveFarm";
import { useCapability } from "@/rbac/useCapability";
import {
  useDefaultRules,
  useRuleOverrides,
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
  const farmId = useActiveFarmId();
  const { t, i18n } = useTranslation("rules");
  const canManage = useCapability("alert_rule.manage");

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

  if (!farmId) {
    return <Navigate to="/" replace />;
  }

  const isLoading = defaults.isLoading || overrides.isLoading;
  const isError = defaults.isError || overrides.isError;
  const isAr = i18n.language === "ar";

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4">
      <header>
        <h1 className="text-2xl font-semibold text-ap-ink">{t("page.title")}</h1>
        <p className="mt-1 text-sm text-ap-muted">{t("page.subtitle")}</p>
      </header>

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
