/**
 * A compact editor for one value-ref.
 *
 * A switch switches on one, and a `set` node may copy one into a variable.
 * The full condition builder (`components/ConditionBuilder.tsx`) edits these
 * inside a predicate tree, but it is 1,300 lines and its editor is private to
 * it, so this is the one-operand version: pick a source, fill the two or three
 * fields that source has.
 *
 * The vocabulary and the read-back helpers live in `lib/betaValueRef.ts`.
 */

import { useTranslation } from "react-i18next";

import { Field } from "@/components/Field";

import {
  BETA_VALUE_SOURCES,
  asBetaValueRef,
  defaultBetaValueRef,
  scalarText,
  valueRefFields,
  type BetaValueRef,
  type BetaValueSource,
} from "../lib/betaValueRef";

const CONTROL_CLASS = "w-full rounded-lg border border-ap-line px-2.5 py-1.5 text-sm text-ap-ink";

interface ValueRefFieldProps {
  value: unknown;
  onChange: (next: BetaValueRef) => void;
  label: string;
  /** Names a `set` node wrote earlier, offered when the source is `vars`. */
  knownVarNames?: readonly string[];
  disabled?: boolean;
}

export function ValueRefField({
  value,
  onChange,
  label,
  knownVarNames = [],
  disabled,
}: ValueRefFieldProps): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const ref = asBetaValueRef(value);

  const patch = (next: Record<string, unknown>): void =>
    onChange({ ...ref, ...next, source: ref.source });

  return (
    <div className="flex flex-col gap-2">
      <Field label={label}>
        {(props) => (
          <select
            {...props}
            disabled={disabled}
            value={ref.source}
            onChange={(e) => onChange(defaultBetaValueRef(e.target.value as BetaValueSource))}
            className={CONTROL_CLASS}
          >
            {BETA_VALUE_SOURCES.map((s) => (
              <option key={s} value={s}>
                {t(`valueRef.sources.${s}`)}
              </option>
            ))}
          </select>
        )}
      </Field>
      <div className="grid grid-cols-2 gap-2">
        {valueRefFields(ref).map((field) => (
          <Field key={field.key} label={t(`valueRef.${field.labelKey}`)}>
            {(props) =>
              field.options ? (
                <select
                  {...props}
                  disabled={disabled}
                  value={scalarText(ref[field.key])}
                  onChange={(e) => patch({ [field.key]: e.target.value })}
                  className={CONTROL_CLASS}
                >
                  {field.options.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  {...props}
                  dir="ltr"
                  disabled={disabled}
                  value={scalarText(ref[field.key])}
                  onChange={(e) => patch({ [field.key]: e.target.value })}
                  list={
                    field.key === "name" && knownVarNames.length > 0 ? "beta-var-names" : undefined
                  }
                  className={CONTROL_CLASS}
                />
              )
            }
          </Field>
        ))}
      </div>
      {knownVarNames.length > 0 ? (
        <datalist id="beta-var-names">
          {knownVarNames.map((n) => (
            <option key={n} value={n} />
          ))}
        </datalist>
      ) : null}
    </div>
  );
}
