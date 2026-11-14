// Heat units (decision D17): how a crop counts growing degree days, and from
// when. Set on the crop and inherited by its varieties and strains, deepest
// non-null wins, like the stage calendar. The base and upper temperatures stay
// on the crop's Details form; this fieldset is the method and the start. The
// draft helpers live in `lib/heatUnits.ts`.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { GDD_METHODS, GDD_START_KINDS, type GddMethod, type GddStartKind } from "@/api/crops";
import { Field, FIELD_CONTROL_CLASS } from "@/components/Field";
import { resolveHeatUnits } from "@/modules/admin/lib/cropTaxonomy";
import { heatUnitStartError, type HeatUnitDraft } from "@/modules/admin/lib/heatUnits";

export function HeatUnitFields({
  draft,
  onChange,
  disabled,
  inherits,
  stageCodes,
  parent,
}: {
  draft: HeatUnitDraft;
  onChange: (next: HeatUnitDraft) => void;
  disabled: boolean;
  /** True on a variety or strain: an empty select inherits from the parent. */
  inherits: boolean;
  /** Stage codes offered for a `stage` start (the node's resolved calendar). */
  stageCodes: readonly string[];
  /** What the level above resolves to, shown so "Inherit" says what it means. */
  parent?: ReturnType<typeof resolveHeatUnits>;
}): ReactNode {
  const { t } = useTranslation("admin");
  const unsetLabel = inherits ? t("heatUnits.inherit") : t("heatUnits.unset");
  const error = heatUnitStartError(draft);
  const parentStart = parent?.start.value;
  const inherited = parent
    ? t("heatUnits.inheritedSummary", {
        method: parent.method.value
          ? t(`heatUnits.methodOption.${parent.method.value}`)
          : t("heatUnits.unset"),
        start: parentStart
          ? `${t(`heatUnits.startKindOption.${parentStart.kind}`)}${
              parentStart.value ? ` ${parentStart.value}` : ""
            }`
          : t("heatUnits.unset"),
      })
    : null;

  return (
    <fieldset className="rounded-md border border-ap-line p-3">
      <legend className="px-1 text-xs font-medium text-ap-ink">{t("heatUnits.heading")}</legend>
      <p className="mb-2 text-[11px] text-ap-muted">{t("heatUnits.intro")}</p>
      {inherited ? <p className="mb-2 text-[11px] text-ap-ink">{inherited}</p> : null}
      <div className="grid gap-3 sm:grid-cols-3">
        <Field
          label={t("heatUnits.method")}
          help={draft.method ? t(`heatUnits.methodHint.${draft.method}`) : undefined}
        >
          {(props) => (
            <select
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={draft.method}
              disabled={disabled}
              onChange={(e) => onChange({ ...draft, method: e.target.value as GddMethod | "" })}
            >
              <option value="">{unsetLabel}</option>
              {GDD_METHODS.map((m) => (
                <option key={m} value={m}>
                  {t(`heatUnits.methodOption.${m}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t("heatUnits.startKind")}>
          {(props) => (
            <select
              {...props}
              className={FIELD_CONTROL_CLASS}
              value={draft.startKind}
              disabled={disabled}
              onChange={(e) =>
                onChange({
                  ...draft,
                  startKind: e.target.value as GddStartKind | "",
                  startValue: "",
                })
              }
            >
              <option value="">{unsetLabel}</option>
              {GDD_START_KINDS.map((k) => (
                <option key={k} value={k}>
                  {t(`heatUnits.startKindOption.${k}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        {draft.startKind === "date" ? (
          <Field label={t("heatUnits.startDate")} help={t("heatUnits.startDateHint")}>
            {(props) => (
              <input
                {...props}
                dir="ltr"
                className={FIELD_CONTROL_CLASS}
                value={draft.startValue}
                placeholder="03-01"
                disabled={disabled}
                onChange={(e) => onChange({ ...draft, startValue: e.target.value })}
              />
            )}
          </Field>
        ) : null}
        {draft.startKind === "stage" ? (
          <Field label={t("heatUnits.startStage")} help={t("heatUnits.startStageHint")}>
            {(props) => (
              <select
                {...props}
                className={FIELD_CONTROL_CLASS}
                value={draft.startValue}
                disabled={disabled}
                onChange={(e) => onChange({ ...draft, startValue: e.target.value })}
              >
                <option value="">—</option>
                {/* Keep a saved code selectable even if the calendar dropped it. */}
                {[
                  ...stageCodes,
                  ...(draft.startValue && !stageCodes.includes(draft.startValue)
                    ? [draft.startValue]
                    : []),
                ].map((code) => (
                  <option key={code} value={code}>
                    {code}
                  </option>
                ))}
              </select>
            )}
          </Field>
        ) : null}
      </div>
      {draft.startKind === "planting" ? (
        <p className="mt-1 text-[11px] text-ap-muted">{t("heatUnits.plantingHint")}</p>
      ) : null}
      {error ? (
        <p role="alert" className="mt-1 text-[11px] text-ap-crit">
          {t(error)}
        </p>
      ) : null}
    </fieldset>
  );
}
