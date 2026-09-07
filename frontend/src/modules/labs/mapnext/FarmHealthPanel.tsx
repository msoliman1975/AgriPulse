// Farm-level health definition — what "healthy" means on this farm.
//
// A RESOLUTION TIER, not a template. There is no Apply and no preview, and
// there must not be: a block's definition is resolved at read time as
//
//     platform default  <-  crop catalog  <-  this farm override
//
// shallow merge, deepest tier winning per key. Nothing is copied into
// blocks, so there is nothing to reconcile. An Apply would write a resolved
// answer into blocks and start it drifting from the tiers it came from —
// the exact failure the health work exists to end.
//
// EVERY control has an explicit Override toggle, and that is the whole
// design of this panel rather than a decoration. A field left inherited is
// OMITTED from the request; a field switched on is sent and pins that value
// for ever after. If the controls just held values, saving would pin all
// seven whatever the operator touched, and the farm would silently stop
// tracking the knowledge base. The three fields that take null as a real
// value — a null `snoozed_as` means "count a snoozed alert by its own
// severity" — are why "not sent" and "sent as null" cannot be collapsed.
//
// Nothing here shows the RESOLVED value, because this panel edits the
// override and nothing else. What a block actually ended up with is shown
// beside its health class in the block dock, with the tier that decided it.
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { isApiError } from "@/api/errors";
import {
  getHealthTemplate,
  putHealthTemplate,
  type HealthDefinitionBody,
} from "@/api/farmConfig";

const inputCls =
  "w-24 rounded-lg border border-ap-line bg-ap-panel px-2.5 py-1.5 text-sm text-ap-ink focus:border-ap-primary focus:outline-none disabled:opacity-50";
const selectCls =
  "rounded-lg border border-ap-line bg-ap-panel px-2.5 py-1.5 text-sm text-ap-ink focus:border-ap-primary focus:outline-none disabled:opacity-50";
const primaryBtn =
  "h-9 rounded-lg bg-ap-primary px-4 text-sm font-semibold text-white hover:bg-ap-primary/90 disabled:opacity-50";
const ghostBtn =
  "h-9 rounded-lg border border-ap-line bg-ap-panel px-3 text-sm font-semibold text-ap-ink hover:bg-ap-primary-soft disabled:opacity-50";

// The closed sets, mirrored from `app.shared.health_definition`. Every one
// of these is also enforced server-side by `parse_definition`; the point of
// repeating them here is that a control can only OFFER a legal value, so an
// illegal one is not something the operator can reach and then be told off
// for. Bounds that are numbers (0 < share <= 1) stay server-side only —
// duplicating a range in two languages is how the two drift.
const CLASSES = ["healthy", "watch", "critical"] as const;
const COVERAGE = ["unknown", "healthy"] as const;
const STATUSES = ["open", "acknowledged", "snoozed"] as const;
const SEVERITIES = ["critical", "warning", "info"] as const;

/** The seven keys a farm may set, each with whether it is overridden. */
interface Draft {
  stale_after_hours: { on: boolean; value: number };
  no_tree_coverage: { on: boolean; value: string };
  counted_statuses: { on: boolean; value: string[] };
  snoozed_as: { on: boolean; value: string };
  severity_map: { on: boolean; value: Record<string, string> };
  cell_critical_share: { on: boolean; value: number };
  recommendation_floor: { on: boolean; value: number };
}

// The value a control starts at when it is switched on. These are the
// platform defaults, so switching a control on and saving immediately is a
// no-op in effect — the operator has to move something for anything to
// change. `snoozed_as` starts at the sentinel for null.
const NULL_SNOOZE = "__own__";

function emptyDraft(): Draft {
  return {
    stale_after_hours: { on: false, value: 48 },
    no_tree_coverage: { on: false, value: "unknown" },
    counted_statuses: { on: false, value: ["open", "acknowledged", "snoozed"] },
    snoozed_as: { on: false, value: "watch" },
    severity_map: {
      on: false,
      value: { critical: "critical", warning: "watch", info: "healthy" },
    },
    cell_critical_share: { on: false, value: 0.25 },
    recommendation_floor: { on: false, value: 0.8 },
  };
}

/** Server body -> draft. A key PRESENT in the body is overridden, whatever
 *  its value — including null, which is a real choice for three of them. */
function toDraft(body: HealthDefinitionBody | null): Draft {
  const d = emptyDraft();
  if (!body) return d;
  const has = (k: keyof HealthDefinitionBody) => Object.hasOwn(body, k);

  if (has("stale_after_hours") && body.stale_after_hours != null) {
    d.stale_after_hours = { on: true, value: body.stale_after_hours };
  }
  if (has("no_tree_coverage") && body.no_tree_coverage != null) {
    d.no_tree_coverage = { on: true, value: body.no_tree_coverage };
  }
  if (has("counted_statuses") && body.counted_statuses != null) {
    d.counted_statuses = { on: true, value: body.counted_statuses };
  }
  if (has("snoozed_as")) {
    // null is a value here, not an absence: "count it by its own severity".
    d.snoozed_as = { on: true, value: body.snoozed_as ?? NULL_SNOOZE };
  }
  if (has("severity_map") && body.severity_map != null) {
    d.severity_map = { on: true, value: { ...d.severity_map.value, ...body.severity_map } };
  }
  if (has("cell_critical_share") && body.cell_critical_share != null) {
    d.cell_critical_share = { on: true, value: body.cell_critical_share };
  }
  if (has("recommendation_floor") && body.recommendation_floor != null) {
    d.recommendation_floor = { on: true, value: body.recommendation_floor };
  }
  return d;
}

/** Draft -> server body. Only the switched-on keys, and null when the whole
 *  thing is off — which CLEARS the override rather than storing `{}`. */
function toBody(d: Draft): HealthDefinitionBody | null {
  const body: HealthDefinitionBody = {};
  if (d.stale_after_hours.on) body.stale_after_hours = d.stale_after_hours.value;
  if (d.no_tree_coverage.on) body.no_tree_coverage = d.no_tree_coverage.value;
  if (d.counted_statuses.on) body.counted_statuses = d.counted_statuses.value;
  if (d.snoozed_as.on) {
    body.snoozed_as = d.snoozed_as.value === NULL_SNOOZE ? null : d.snoozed_as.value;
  }
  if (d.severity_map.on) body.severity_map = d.severity_map.value;
  if (d.cell_critical_share.on) body.cell_critical_share = d.cell_critical_share.value;
  if (d.recommendation_floor.on) body.recommendation_floor = d.recommendation_floor.value;
  return Object.keys(body).length > 0 ? body : null;
}

interface Props {
  farmId: string;
}

export function FarmHealthPanel({ farmId }: Props): ReactNode {
  const { t } = useTranslation(["farmConsole", "common"]);
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [locked, setLocked] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getHealthTemplate(farmId)
      .then((tpl) => {
        if (cancelled) return;
        setDraft(toDraft(tpl.definition));
        setLocked(tpl.locked);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(
            isApiError(err) ? (err.problem.detail ?? err.message) : t("farmHealth.loadFailed"),
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [farmId, t]);

  function patch(next: Partial<Draft>): void {
    setDraft((d) => ({ ...d, ...next }));
    setNote(null);
  }

  async function save(): Promise<void> {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const saved = await putHealthTemplate(farmId, toBody(draft));
      setDraft(toDraft(saved.definition));
      setNote(saved.definition ? t("farmHealth.saved") : t("farmHealth.cleared"));
    } catch (err: unknown) {
      setError(isApiError(err) ? (err.problem.detail ?? err.message) : t("farmHealth.saveFailed"));
    } finally {
      setBusy(false);
    }
  }

  const disabled = busy || locked || loading;
  const overrides = Object.values(draft).filter((f) => f.on).length;

  return (
    <section className="rounded-xl border border-ap-line bg-ap-bg/40 p-4">
      <h3 className="mb-1 text-sm font-bold text-ap-ink">{t("farmHealth.title")}</h3>
      <p className="mb-1 text-xs text-ap-muted">{t("farmHealth.intro")}</p>
      {/* Said once, plainly. A control left inherited keeps following the
          knowledge base; switching it on freezes that value on this farm. */}
      <p className="mb-3 text-xs text-ap-muted">{t("farmHealth.inheritNote")}</p>

      {locked ? <p className="mb-2 text-xs text-ap-warn">{t("farmHealth.locked")}</p> : null}
      {error ? <p className="mb-2 text-xs text-ap-crit">{error}</p> : null}
      {note ? <p className="mb-2 text-xs text-ap-good">{note}</p> : null}

      {loading ? (
        <p className="text-xs text-ap-muted">{t("farmHealth.loading")}</p>
      ) : (
        <div className="space-y-3">
          <Row
            label={t("farmHealth.staleAfterHours")}
            hint={t("farmHealth.staleAfterHoursHint")}
            on={draft.stale_after_hours.on}
            disabled={disabled}
            onToggle={(on) => patch({ stale_after_hours: { ...draft.stale_after_hours, on } })}
            inheritLabel={t("farmHealth.inherited")}
          >
            <input
              type="number"
              min={1}
              className={inputCls}
              disabled={disabled}
              value={draft.stale_after_hours.value}
              onChange={(e) =>
                patch({
                  stale_after_hours: {
                    on: true,
                    value: Math.max(1, Number(e.target.value) || 1),
                  },
                })
              }
            />
          </Row>

          <Row
            label={t("farmHealth.noTreeCoverage")}
            hint={t("farmHealth.noTreeCoverageHint")}
            on={draft.no_tree_coverage.on}
            disabled={disabled}
            onToggle={(on) => patch({ no_tree_coverage: { ...draft.no_tree_coverage, on } })}
            inheritLabel={t("farmHealth.inherited")}
          >
            <select
              className={selectCls}
              disabled={disabled}
              value={draft.no_tree_coverage.value}
              onChange={(e) => patch({ no_tree_coverage: { on: true, value: e.target.value } })}
            >
              {COVERAGE.map((c) => (
                <option key={c} value={c}>
                  {t(`health.${c}`)}
                </option>
              ))}
            </select>
          </Row>

          <Row
            label={t("farmHealth.countedStatuses")}
            hint={t("farmHealth.countedStatusesHint")}
            on={draft.counted_statuses.on}
            disabled={disabled}
            onToggle={(on) => patch({ counted_statuses: { ...draft.counted_statuses, on } })}
            inheritLabel={t("farmHealth.inherited")}
          >
            <div className="flex flex-wrap gap-3">
              {STATUSES.map((st) => (
                <label key={st} className="flex items-center gap-1.5 text-xs text-ap-ink">
                  <input
                    type="checkbox"
                    disabled={disabled}
                    checked={draft.counted_statuses.value.includes(st)}
                    onChange={(e) => {
                      const set = new Set(draft.counted_statuses.value);
                      if (e.target.checked) set.add(st);
                      else set.delete(st);
                      patch({
                        counted_statuses: { on: true, value: STATUSES.filter((s) => set.has(s)) },
                      });
                    }}
                  />
                  {t(`farmHealth.status.${st}`)}
                </label>
              ))}
            </div>
          </Row>

          <Row
            label={t("farmHealth.snoozedAs")}
            hint={t("farmHealth.snoozedAsHint")}
            on={draft.snoozed_as.on}
            disabled={disabled}
            onToggle={(on) => patch({ snoozed_as: { ...draft.snoozed_as, on } })}
            inheritLabel={t("farmHealth.inherited")}
          >
            <select
              className={selectCls}
              disabled={disabled}
              value={draft.snoozed_as.value}
              onChange={(e) => patch({ snoozed_as: { on: true, value: e.target.value } })}
            >
              {/* The sentinel is a real choice, not "no choice": it says a
                  snoozed alert counts by its own severity. It has to be
                  offered, or that setting would be unreachable. */}
              <option value={NULL_SNOOZE}>{t("farmHealth.snoozedOwnSeverity")}</option>
              {CLASSES.map((c) => (
                <option key={c} value={c}>
                  {t(`health.${c}`)}
                </option>
              ))}
            </select>
          </Row>

          <Row
            label={t("farmHealth.severityMap")}
            hint={t("farmHealth.severityMapHint")}
            on={draft.severity_map.on}
            disabled={disabled}
            onToggle={(on) => patch({ severity_map: { ...draft.severity_map, on } })}
            inheritLabel={t("farmHealth.inherited")}
          >
            <div className="flex flex-wrap gap-3">
              {SEVERITIES.map((sev) => (
                <label key={sev} className="flex items-center gap-1.5 text-xs text-ap-ink">
                  {t(`farmHealth.severity.${sev}`)}
                  <select
                    className={selectCls}
                    disabled={disabled}
                    value={draft.severity_map.value[sev]}
                    onChange={(e) =>
                      patch({
                        severity_map: {
                          on: true,
                          value: { ...draft.severity_map.value, [sev]: e.target.value },
                        },
                      })
                    }
                  >
                    {CLASSES.map((c) => (
                      <option key={c} value={c}>
                        {t(`health.${c}`)}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
          </Row>

          <Row
            label={t("farmHealth.cellCriticalShare")}
            hint={t("farmHealth.cellCriticalShareHint")}
            on={draft.cell_critical_share.on}
            disabled={disabled}
            onToggle={(on) => patch({ cell_critical_share: { ...draft.cell_critical_share, on } })}
            inheritLabel={t("farmHealth.inherited")}
          >
            <Share
              value={draft.cell_critical_share.value}
              disabled={disabled}
              min={1}
              onChange={(v) => patch({ cell_critical_share: { on: true, value: v } })}
            />
          </Row>

          <Row
            label={t("farmHealth.recommendationFloor")}
            hint={t("farmHealth.recommendationFloorHint")}
            on={draft.recommendation_floor.on}
            disabled={disabled}
            onToggle={(on) =>
              patch({ recommendation_floor: { ...draft.recommendation_floor, on } })
            }
            inheritLabel={t("farmHealth.inherited")}
          >
            <Share
              value={draft.recommendation_floor.value}
              disabled={disabled}
              min={0}
              onChange={(v) => patch({ recommendation_floor: { on: true, value: v } })}
            />
          </Row>

          <div className="flex items-center gap-2 border-t border-ap-line pt-3">
            <button type="button" className={primaryBtn} disabled={disabled} onClick={save}>
              {busy ? t("farmHealth.saving") : t("farmHealth.save")}
            </button>
            <button
              type="button"
              className={ghostBtn}
              disabled={disabled || overrides === 0}
              onClick={() => {
                setDraft(emptyDraft());
                setNote(null);
              }}
            >
              {t("farmHealth.clearAll")}
            </button>
            <span className="text-xs text-ap-muted">
              {overrides === 0
                ? t("farmHealth.noOverrides")
                : t("farmHealth.overrideCount", { count: overrides })}
            </span>
          </div>
        </div>
      )}
    </section>
  );
}

/** One setting: its name, why it exists, and an explicit inherit/override
 *  switch. The switch is not decoration — see the file header. */
function Row({
  label,
  hint,
  on,
  disabled,
  onToggle,
  inheritLabel,
  children,
}: {
  label: string;
  hint: string;
  on: boolean;
  disabled: boolean;
  onToggle: (on: boolean) => void;
  inheritLabel: string;
  children: ReactNode;
}): ReactNode {
  return (
    <div className="grid grid-cols-[1fr_auto] items-start gap-3 border-b border-ap-line/60 pb-3">
      <div>
        <label className="flex items-center gap-2 text-xs font-semibold text-ap-ink">
          <input
            type="checkbox"
            checked={on}
            disabled={disabled}
            onChange={(e) => onToggle(e.target.checked)}
          />
          {label}
        </label>
        <p className="mt-0.5 text-[11px] leading-tight text-ap-muted">{hint}</p>
      </div>
      <div className="flex items-center gap-2">
        {on ? children : <span className="text-xs text-ap-muted">{inheritLabel}</span>}
      </div>
    </div>
  );
}

/** A 0-to-1 share, edited as a percentage because that is how a grower says
 *  it. `min` differs: a critical-cell share of 0 would mean no cells, which
 *  the server refuses, while a recommendation floor of 0 means "any". */
function Share({
  value,
  disabled,
  min,
  onChange,
}: {
  value: number;
  disabled: boolean;
  min: number;
  onChange: (v: number) => void;
}): ReactNode {
  return (
    <span className="flex items-center gap-1">
      <input
        type="number"
        min={min}
        max={100}
        className={inputCls}
        disabled={disabled}
        value={Math.round(value * 100)}
        onChange={(e) => {
          const pct = Math.min(100, Math.max(min, Number(e.target.value) || 0));
          onChange(pct / 100);
        }}
      />
      <span className="text-xs text-ap-muted">%</span>
    </span>
  );
}
