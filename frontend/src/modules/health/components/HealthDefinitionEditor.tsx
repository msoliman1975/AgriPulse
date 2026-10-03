// One editor for the block health definition, used by two tiers:
//
//   * the platform default (/platform/health-definition): every key always
//     has a value, so there are no switches;
//   * a crop path (the catalogue's Health tab): each key is either set here
//     or inherited, and an inherited key shows its value and the level it
//     came from.
//
// The mode follows from `inherited`: pass it and the editor shows switches.
//
// The editor holds no default values of its own. A switch turned on starts
// from the inherited value, so turning it on and saving changes nothing until
// someone moves a control. The bounds the server checks (share in (0, 1],
// hours >= 1) are mirrored only as input limits; the server is the gate.
//
// Field labels come from `farmConsole:farmHealth.*`, which the farm panel
// already uses, so the three screens name each setting the same way.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type {
  HealthBody,
  HealthDefinitionValues,
  HealthKey,
  InheritedValue,
} from "@/api/healthDefinitions";

const CLASSES = ["healthy", "watch", "critical"] as const;
const COVERAGE = ["unknown", "healthy"] as const;
const STATUSES = ["open", "acknowledged", "snoozed"] as const;
const SEVERITIES = ["critical", "warning", "info"] as const;
const ROLLUPS = ["worst", "share", "most_common"] as const;
const NULL_SNOOZE = "__own__";

const inputCls =
  "w-24 rounded-md border border-ap-line bg-ap-panel px-2.5 py-1.5 text-sm text-ap-ink focus:border-ap-primary focus:outline-none disabled:opacity-50";
const selectCls =
  "rounded-md border border-ap-line bg-ap-panel px-2.5 py-1.5 text-sm text-ap-ink focus:border-ap-primary focus:outline-none disabled:opacity-50";

interface Props {
  keys: readonly HealthKey[];
  /** Full mode: every key. Override mode: only the keys set at this level. */
  values: HealthBody;
  onChange: (next: HealthBody) => void;
  disabled: boolean;
  /** Present: override mode. What each key reads without this level. */
  inherited?: Partial<Record<HealthKey, InheritedValue>>;
}

export function HealthDefinitionEditor({
  keys,
  values,
  onChange,
  disabled,
  inherited,
}: Props): ReactNode {
  const { t } = useTranslation(["admin", "farmConsole", "integrations"]);
  const overrideMode = inherited !== undefined;

  const set = <K extends HealthKey>(key: K, value: HealthDefinitionValues[K]): void =>
    onChange({ ...values, [key]: value });

  const toggle = (key: HealthKey, on: boolean): void => {
    const next: HealthBody = { ...values };
    if (on) {
      // Start from what the key reads today. A deep copy, so editing the
      // severity map or the status list never edits the inherited object.
      const start = inherited?.[key]?.value;
      (next as Record<string, unknown>)[key] =
        start === undefined ? null : JSON.parse(JSON.stringify(start));
    } else {
      delete next[key];
    }
    onChange(next);
  };

  return (
    <div className="space-y-3">
      {keys.map((key) => {
        const on = !overrideMode || Object.hasOwn(values, key);
        const from = inherited?.[key];
        return (
          <div
            key={key}
            className="grid grid-cols-1 items-start gap-2 border-b border-ap-line/60 pb-3 sm:grid-cols-[minmax(0,1fr)_auto]"
          >
            <div>
              <label className="flex items-center gap-2 text-xs font-semibold text-ap-ink">
                {overrideMode ? (
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={disabled}
                    onChange={(e) => toggle(key, e.target.checked)}
                    aria-label={t("admin:healthDefinition.overrideLabel", {
                      name: t(LABEL[key]),
                    })}
                  />
                ) : null}
                {t(LABEL[key])}
              </label>
              <p className="mt-0.5 text-[11px] leading-tight text-ap-muted">{t(HINT[key])}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {on ? (
                <Control k={key} values={values} set={set} disabled={disabled} />
              ) : (
                <span className="text-xs text-ap-muted">
                  <span className="font-medium text-ap-ink">
                    {from ? describe(key, from.value, t) : "—"}
                  </span>{" "}
                  {from
                    ? t("admin:healthDefinition.inheritedFrom", {
                        source:
                          from.source === "platform"
                            ? t("admin:healthDefinition.platformSource")
                            : from.source,
                      })
                    : null}
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

const LABEL: Record<HealthKey, string> = {
  stale_after_hours: "farmConsole:farmHealth.staleAfterHours",
  no_tree_coverage: "farmConsole:farmHealth.noTreeCoverage",
  counted_statuses: "farmConsole:farmHealth.countedStatuses",
  snoozed_as: "farmConsole:farmHealth.snoozedAs",
  severity_map: "farmConsole:farmHealth.severityMap",
  cell_critical_share: "farmConsole:farmHealth.cellCriticalShare",
  recommendation_floor: "farmConsole:farmHealth.recommendationFloor",
  cell_rollup: "admin:healthDefinition.cellRollup",
};

const HINT: Record<HealthKey, string> = {
  stale_after_hours: "farmConsole:farmHealth.staleAfterHoursHint",
  no_tree_coverage: "farmConsole:farmHealth.noTreeCoverageHint",
  counted_statuses: "farmConsole:farmHealth.countedStatusesHint",
  snoozed_as: "farmConsole:farmHealth.snoozedAsHint",
  severity_map: "farmConsole:farmHealth.severityMapHint",
  cell_critical_share: "farmConsole:farmHealth.cellCriticalShareHint",
  recommendation_floor: "farmConsole:farmHealth.recommendationFloorHint",
  cell_rollup: "admin:healthDefinition.cellRollupHint",
};

type T = (key: string, options?: Record<string, unknown>) => string;

/** A stored scalar as text; anything else as nothing. */
function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

/** An inherited value in words, for the row that is not set here. */
function describe(key: HealthKey, value: unknown, t: T): string {
  switch (key) {
    case "stale_after_hours":
      return t("admin:healthDefinition.hours", { count: Number(value) });
    case "no_tree_coverage":
      return t(`farmConsole:health.${text(value)}`);
    case "counted_statuses":
      return (Array.isArray(value) ? value : [])
        .map((s) => t(`farmConsole:farmHealth.status.${text(s)}`))
        .join(", ");
    case "snoozed_as":
      return value === null
        ? t("farmConsole:farmHealth.snoozedOwnSeverity")
        : t(`farmConsole:health.${text(value)}`);
    case "severity_map": {
      const map = (value ?? {}) as Record<string, string>;
      return SEVERITIES.map(
        (s) =>
          `${t(`farmConsole:farmHealth.severity.${s}`)} → ${t(`farmConsole:health.${map[s]}`)}`,
      ).join(", ");
    }
    case "cell_critical_share":
      return value === null
        ? t("admin:healthDefinition.nullShare.cellCriticalShare")
        : `${Math.round(Number(value) * 100)}%`;
    case "recommendation_floor":
      return value === null
        ? t("admin:healthDefinition.nullShare.recommendationFloor")
        : `${Math.round(Number(value) * 100)}%`;
    case "cell_rollup":
      return t(`integrations:cellRollup.rule.${text(value)}`);
  }
}

function Control({
  k,
  values,
  set,
  disabled,
}: {
  k: HealthKey;
  values: HealthBody;
  set: <K extends HealthKey>(key: K, value: HealthDefinitionValues[K]) => void;
  disabled: boolean;
}): ReactNode {
  const { t } = useTranslation(["admin", "farmConsole", "integrations"]);

  switch (k) {
    case "stale_after_hours":
      return (
        <input
          type="number"
          min={1}
          dir="ltr"
          className={inputCls}
          disabled={disabled}
          aria-label={t(LABEL[k])}
          value={values.stale_after_hours ?? 1}
          onChange={(e) => set(k, Math.max(1, Math.round(Number(e.target.value) || 1)))}
        />
      );
    case "no_tree_coverage":
      return (
        <select
          className={selectCls}
          disabled={disabled}
          aria-label={t(LABEL[k])}
          value={values.no_tree_coverage ?? "unknown"}
          onChange={(e) => set(k, e.target.value as "unknown" | "healthy")}
        >
          {COVERAGE.map((c) => (
            <option key={c} value={c}>
              {t(`farmConsole:health.${c}`)}
            </option>
          ))}
        </select>
      );
    case "counted_statuses": {
      const current = values.counted_statuses ?? [];
      return (
        <div className="flex flex-wrap gap-3">
          {STATUSES.map((st) => (
            <label key={st} className="flex items-center gap-1.5 text-xs text-ap-ink">
              <input
                type="checkbox"
                disabled={disabled}
                checked={current.includes(st)}
                onChange={(e) => {
                  const chosen = new Set(current);
                  if (e.target.checked) chosen.add(st);
                  else chosen.delete(st);
                  set(
                    k,
                    STATUSES.filter((s) => chosen.has(s)),
                  );
                }}
              />
              {t(`farmConsole:farmHealth.status.${st}`)}
            </label>
          ))}
        </div>
      );
    }
    case "snoozed_as":
      return (
        <select
          className={selectCls}
          disabled={disabled}
          aria-label={t(LABEL[k])}
          value={values.snoozed_as ?? NULL_SNOOZE}
          onChange={(e) =>
            set(
              k,
              e.target.value === NULL_SNOOZE
                ? null
                : (e.target.value as HealthDefinitionValues["snoozed_as"]),
            )
          }
        >
          {/* A real choice, not "no choice": a snoozed alert counts by its
              own severity. It has to be offered or it is unreachable. */}
          <option value={NULL_SNOOZE}>{t("farmConsole:farmHealth.snoozedOwnSeverity")}</option>
          {CLASSES.map((c) => (
            <option key={c} value={c}>
              {t(`farmConsole:health.${c}`)}
            </option>
          ))}
        </select>
      );
    case "severity_map": {
      const map = values.severity_map ?? ({} as HealthDefinitionValues["severity_map"]);
      return (
        <div className="flex flex-wrap gap-3">
          {SEVERITIES.map((sev) => (
            <label key={sev} className="flex items-center gap-1.5 text-xs text-ap-ink">
              {t(`farmConsole:farmHealth.severity.${sev}`)}
              <select
                className={selectCls}
                disabled={disabled}
                value={map[sev]}
                onChange={(e) =>
                  set(k, { ...map, [sev]: e.target.value as (typeof CLASSES)[number] })
                }
              >
                {CLASSES.map((c) => (
                  <option key={c} value={c}>
                    {t(`farmConsole:health.${c}`)}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      );
    }
    case "cell_critical_share":
    case "recommendation_floor":
      return (
        <NullableShare
          label={t(LABEL[k])}
          nullLabel={t(
            k === "cell_critical_share"
              ? "admin:healthDefinition.nullShare.cellCriticalShare"
              : "admin:healthDefinition.nullShare.recommendationFloor",
          )}
          setLabel={t("admin:healthDefinition.setThreshold")}
          value={values[k] ?? null}
          min={k === "cell_critical_share" ? 1 : 0}
          disabled={disabled}
          onChange={(v) => set(k, v)}
        />
      );
    case "cell_rollup":
      return (
        <select
          className={selectCls}
          disabled={disabled}
          aria-label={t(LABEL[k])}
          value={values.cell_rollup ?? "worst"}
          onChange={(e) => set(k, e.target.value as (typeof ROLLUPS)[number])}
        >
          {ROLLUPS.map((r) => (
            <option key={r} value={r}>
              {t(`integrations:cellRollup.rule.${r}`)}
            </option>
          ))}
        </select>
      );
  }
}

/** A 0-to-1 share edited as a percent, where null is a real value with its
 *  own meaning. `min` differs: a critical-cell share of 0 would mean no
 *  cells, which the server refuses, while a floor of 0 means "any". */
function NullableShare({
  label,
  nullLabel,
  setLabel,
  value,
  min,
  disabled,
  onChange,
}: {
  label: string;
  nullLabel: string;
  setLabel: string;
  value: number | null;
  min: number;
  disabled: boolean;
  onChange: (v: number | null) => void;
}): ReactNode {
  const isSet = value !== null;
  return (
    <span className="flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-1.5 text-xs text-ap-ink">
        <input
          type="checkbox"
          checked={isSet}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked ? Math.max(min, 25) / 100 : null)}
        />
        {setLabel}
      </label>
      {isSet ? (
        <span className="flex items-center gap-1">
          <input
            type="number"
            min={min}
            max={100}
            dir="ltr"
            className={inputCls}
            disabled={disabled}
            aria-label={label}
            value={Math.round((value ?? 0) * 100)}
            onChange={(e) => {
              const pct = Math.min(100, Math.max(min, Number(e.target.value) || 0));
              onChange(pct / 100);
            }}
          />
          <span className="text-xs text-ap-muted">%</span>
        </span>
      ) : (
        <span className="text-xs text-ap-muted">{nullLabel}</span>
      )}
    </span>
  );
}
