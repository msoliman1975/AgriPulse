import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { SignalDefinition } from "@/api/signals";

const inputCls =
  "w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary";

function Field({ label, children }: { label: string; children: ReactNode }): ReactNode {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ap-muted">{label}</span>
      {children}
    </label>
  );
}

export interface ValueInputProps {
  defn: SignalDefinition;
  valueText: string;
  setValueText: (v: string) => void;
  valueBool: boolean;
  setValueBool: (v: boolean) => void;
  lat: string;
  setLat: (v: string) => void;
  lon: string;
  setLon: (v: string) => void;
  /** When true, drops the html `required` attribute so a template member can be left blank. */
  optional?: boolean;
}

export function ValueInput({
  defn,
  valueText,
  setValueText,
  valueBool,
  setValueBool,
  lat,
  setLat,
  lon,
  setLon,
  optional = false,
}: ValueInputProps): ReactNode {
  const { t } = useTranslation("signals");
  const req = !optional;
  if (defn.value_kind === "numeric") {
    return (
      <Field
        label={defn.unit ? t("log.form.valueWithUnit", { unit: defn.unit }) : t("log.form.value")}
      >
        <input
          required={req}
          inputMode="decimal"
          value={valueText}
          onChange={(e) => setValueText(e.target.value)}
          className={inputCls}
        />
      </Field>
    );
  }
  if (defn.value_kind === "categorical") {
    return (
      <Field label={t("log.form.value")}>
        <select
          required={req}
          value={valueText}
          onChange={(e) => setValueText(e.target.value)}
          className={inputCls}
        >
          <option value="" disabled>
            {t("log.form.pickOne")}
          </option>
          {(defn.categorical_values ?? []).map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </Field>
    );
  }
  if (defn.value_kind === "event") {
    return (
      <Field label={t("log.form.description")}>
        <input
          required={req}
          maxLength={500}
          value={valueText}
          onChange={(e) => setValueText(e.target.value)}
          className={inputCls}
        />
      </Field>
    );
  }
  if (defn.value_kind === "boolean") {
    return (
      <Field label={t("log.form.value")}>
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={valueBool}
            onChange={(e) => setValueBool(e.target.checked)}
          />
          <span>{valueBool ? "true" : "false"}</span>
        </label>
      </Field>
    );
  }
  // geopoint
  return (
    <div className="grid grid-cols-2 gap-3">
      <Field label={t("log.form.lat")}>
        <input
          required={req}
          inputMode="decimal"
          value={lat}
          onChange={(e) => setLat(e.target.value)}
          className={inputCls}
        />
      </Field>
      <Field label={t("log.form.lon")}>
        <input
          required={req}
          inputMode="decimal"
          value={lon}
          onChange={(e) => setLon(e.target.value)}
          className={inputCls}
        />
      </Field>
    </div>
  );
}
