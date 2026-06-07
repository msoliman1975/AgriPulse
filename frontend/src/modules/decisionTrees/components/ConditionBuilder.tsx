// Visual condition builder for the NodeDetailsPanel (PR-D5).
//
// Coverage: single comparison OR all_of / any_of group of comparisons.
// Anything more complex (nested groups, NOT, between, in) falls into a
// read-only fallback that points the author at the YAML editor — see
// `conditionEdit.ts` for the parser's gating logic.
//
// Edits apply eagerly to the parent's draft YAML (via `onChange`) so
// the structural validator + canvas re-layout reflect the change
// immediately. Same model PR-D4 uses for add/delete node.

import { useTranslation } from "react-i18next";
import { type ReactNode } from "react";

import {
  COMPARISON_OPS,
  GRID_FIELDS,
  INDICES_KEYS,
  SIGNAL_KEYS,
  WEATHER_SCOPES,
  defaultComparisonTerm,
  defaultValueRef,
  serializeCondition,
  type ComparisonOp,
  type ComparisonTerm,
  type EditableCondition,
  type GroupMode,
  type RightOperand,
  type ValueRef,
  type ValueRefSource,
} from "../lib/conditionEdit";

interface ConditionBuilderProps {
  value: EditableCondition;
  /** Fires with the new condition AST ready to be written back to
   *  YAML (`condition.tree`). Caller serializes + persists. */
  onChange: (nextTree: unknown) => void;
  readOnly?: boolean;
}

export function ConditionBuilder({
  value,
  onChange,
  readOnly = false,
}: ConditionBuilderProps): ReactNode {
  const { t } = useTranslation("decisionTrees");

  if (value.kind === "unsupported") {
    return (
      <div className="rounded-md border border-ap-warn/40 bg-ap-warn/5 p-2 text-xs">
        <p className="font-medium text-ap-warn">{t("editor.condition.unsupportedHeading")}</p>
        <p className="mt-1 text-ap-ink">{value.reason}</p>
        <pre className="mt-2 max-h-48 overflow-auto rounded bg-ap-bg/60 p-2 text-[11px] leading-relaxed text-ap-ink">
          {JSON.stringify(value.raw, null, 2)}
        </pre>
      </div>
    );
  }

  const setTerms = (terms: ComparisonTerm[], mode: GroupMode = "all"): void => {
    if (terms.length === 0) {
      onChange(undefined);
      return;
    }
    if (terms.length === 1) {
      onChange(serializeCondition({ kind: "single", term: terms[0] }));
      return;
    }
    onChange(serializeCondition({ kind: "group", mode, terms }));
  };

  const terms: ComparisonTerm[] =
    value.kind === "group"
      ? value.terms
      : value.kind === "single"
        ? [value.term]
        : [];

  const groupMode: GroupMode = value.kind === "group" ? value.mode : "all";

  const onTermChange = (idx: number, next: ComparisonTerm): void => {
    const copy = [...terms];
    copy[idx] = next;
    setTerms(copy, groupMode);
  };
  const onRemoveTerm = (idx: number): void => {
    const copy = terms.filter((_, i) => i !== idx);
    setTerms(copy, groupMode);
  };
  const onAddTerm = (): void => {
    setTerms([...terms, defaultComparisonTerm()], groupMode);
  };
  const onModeChange = (mode: GroupMode): void => {
    setTerms(terms, mode);
  };

  return (
    <div className="flex flex-col gap-2 text-xs">
      {terms.length > 1 ? (
        <div className="flex items-center gap-2">
          <span className="text-ap-muted">{t("editor.condition.match")}</span>
          <select
            disabled={readOnly}
            value={groupMode}
            onChange={(e) => onModeChange(e.target.value as GroupMode)}
            className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          >
            <option value="all">{t("editor.condition.modeAll")}</option>
            <option value="any">{t("editor.condition.modeAny")}</option>
          </select>
        </div>
      ) : null}

      {terms.length === 0 ? (
        <p className="text-ap-muted">{t("editor.condition.empty")}</p>
      ) : (
        terms.map((term, idx) => (
          <ComparisonRow
            key={idx}
            term={term}
            readOnly={readOnly}
            onChange={(next) => onTermChange(idx, next)}
            onRemove={terms.length > 1 ? () => onRemoveTerm(idx) : undefined}
          />
        ))
      )}

      {!readOnly ? (
        <button
          type="button"
          onClick={onAddTerm}
          className="self-start rounded-md border border-dashed border-ap-line bg-ap-bg/40 px-2 py-1 text-xs text-ap-ink hover:bg-ap-bg/60"
        >
          {t("editor.condition.addTerm")}
        </button>
      ) : null}
    </div>
  );
}

// ---- Comparison row ------------------------------------------------

interface ComparisonRowProps {
  term: ComparisonTerm;
  readOnly: boolean;
  onChange: (next: ComparisonTerm) => void;
  onRemove?: () => void;
}

function ComparisonRow({ term, readOnly, onChange, onRemove }: ComparisonRowProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  return (
    <div className="rounded-md border border-ap-line bg-ap-bg/40 p-2">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto_1fr_auto]">
        <ValueRefEditor
          label={t("editor.condition.left")}
          value={term.left}
          disallowParams
          readOnly={readOnly}
          onChange={(next) => onChange({ ...term, left: next })}
        />
        <OperatorPicker
          value={term.op}
          readOnly={readOnly}
          onChange={(next) => onChange({ ...term, op: next })}
        />
        <RightEditor
          value={term.right}
          readOnly={readOnly}
          onChange={(next) => onChange({ ...term, right: next })}
        />
        {onRemove && !readOnly ? (
          <button
            type="button"
            onClick={onRemove}
            aria-label={t("editor.condition.removeTerm")}
            className="self-end justify-self-end rounded-md border border-ap-line bg-white px-2 py-0.5 text-[11px] text-ap-crit hover:bg-ap-crit/10"
          >
            ✕
          </button>
        ) : null}
      </div>
    </div>
  );
}

// ---- Value-ref editor ----------------------------------------------

interface ValueRefEditorProps {
  label: string;
  value: ValueRef;
  readOnly: boolean;
  /** Params refs are only legal on the right operand — set true for
   *  `left`. */
  disallowParams?: boolean;
  onChange: (next: ValueRef) => void;
}

function ValueRefEditor({
  label,
  value,
  readOnly,
  disallowParams = false,
  onChange,
}: ValueRefEditorProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const sources: ValueRefSource[] = disallowParams
    ? ["indices", "block", "weather", "signals", "grid"]
    : ["indices", "block", "weather", "signals", "grid", "params"];

  const onSourceChange = (next: ValueRefSource): void => {
    if (next === value.source) return;
    onChange(defaultValueRef(next));
  };

  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] text-ap-muted">{label}</span>
      <select
        disabled={readOnly}
        value={value.source}
        onChange={(e) => onSourceChange(e.target.value as ValueRefSource)}
        className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
      >
        {sources.map((s) => (
          <option key={s} value={s}>
            {t(`editor.condition.source.${s}`)}
          </option>
        ))}
      </select>
      <SourceSpecificFields value={value} readOnly={readOnly} onChange={onChange} />
    </div>
  );
}

function SourceSpecificFields({
  value,
  readOnly,
  onChange,
}: {
  value: ValueRef;
  readOnly: boolean;
  onChange: (next: ValueRef) => void;
}): ReactNode {
  const { t } = useTranslation("decisionTrees");
  if (value.source === "indices") {
    return (
      <>
        <input
          type="text"
          disabled={readOnly}
          placeholder="ndvi"
          value={value.index_code}
          onChange={(e) => onChange({ ...value, index_code: e.target.value })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.indexCode")}
        />
        <select
          disabled={readOnly}
          value={value.key}
          onChange={(e) => onChange({ ...value, key: e.target.value as (typeof INDICES_KEYS)[number] })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        >
          {INDICES_KEYS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </>
    );
  }
  if (value.source === "block") {
    return (
      <select
        disabled={readOnly}
        value={value.field}
        onChange={(e) => onChange({ ...value, field: e.target.value as typeof value.field })}
        className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
      >
        <option value="crop_category">crop_category</option>
      </select>
    );
  }
  if (value.source === "weather") {
    return (
      <>
        <select
          disabled={readOnly}
          value={value.scope}
          onChange={(e) => onChange({ ...value, scope: e.target.value as (typeof WEATHER_SCOPES)[number] })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        >
          {WEATHER_SCOPES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <input
          type="text"
          disabled={readOnly}
          placeholder="precipitation_mm_total"
          value={value.field}
          onChange={(e) => onChange({ ...value, field: e.target.value })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.weatherField")}
        />
      </>
    );
  }
  if (value.source === "signals") {
    return (
      <>
        <input
          type="text"
          disabled={readOnly}
          placeholder="soil_moisture"
          value={value.code}
          onChange={(e) => onChange({ ...value, code: e.target.value })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.signalCode")}
        />
        <select
          disabled={readOnly}
          value={value.key}
          onChange={(e) => onChange({ ...value, key: e.target.value as (typeof SIGNAL_KEYS)[number] })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        >
          {SIGNAL_KEYS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </>
    );
  }
  if (value.source === "grid") {
    return (
      <>
        <input
          type="text"
          disabled={readOnly}
          placeholder="ndvi"
          value={value.index_code}
          onChange={(e) => onChange({ ...value, index_code: e.target.value })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.indexCode")}
        />
        <select
          disabled={readOnly}
          value={value.field}
          onChange={(e) =>
            onChange({ ...value, field: e.target.value as (typeof GRID_FIELDS)[number] })
          }
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
          aria-label={t("editor.condition.gridField")}
        >
          {GRID_FIELDS.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      </>
    );
  }
  // params
  return (
    <input
      type="text"
      disabled={readOnly}
      placeholder="threshold_name"
      value={value.name}
      onChange={(e) => onChange({ ...value, name: e.target.value })}
      className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
      aria-label={t("editor.condition.paramName")}
    />
  );
}

// ---- Operator picker -----------------------------------------------

interface OperatorPickerProps {
  value: ComparisonOp;
  readOnly: boolean;
  onChange: (next: ComparisonOp) => void;
}

function OperatorPicker({ value, readOnly, onChange }: OperatorPickerProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  return (
    <div className="flex flex-col gap-1 self-end">
      <span className="text-[11px] text-ap-muted">{t("editor.condition.operator")}</span>
      <select
        disabled={readOnly}
        value={value}
        onChange={(e) => onChange(e.target.value as ComparisonOp)}
        className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs font-mono"
      >
        {COMPARISON_OPS.map((op) => (
          <option key={op} value={op}>
            {opSymbol(op)} {op}
          </option>
        ))}
      </select>
    </div>
  );
}

function opSymbol(op: ComparisonOp): string {
  switch (op) {
    case "lt":
      return "<";
    case "le":
      return "≤";
    case "gt":
      return ">";
    case "ge":
      return "≥";
    case "eq":
      return "=";
    case "ne":
      return "≠";
  }
}

// ---- Right operand editor -----------------------------------------

interface RightEditorProps {
  value: RightOperand;
  readOnly: boolean;
  onChange: (next: RightOperand) => void;
}

function RightEditor({ value, readOnly, onChange }: RightEditorProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  // The user picks between "literal" (number/string/boolean) and "ref"
  // (typically a params ref). Number is the default and most common.
  const kindLabel = value.kind === "ref" ? "params ref" : value.kind;
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] text-ap-muted">
        {t("editor.condition.right")} <span className="text-ap-muted">({kindLabel})</span>
      </span>
      <select
        disabled={readOnly}
        value={value.kind}
        onChange={(e) => onChange(coerceRight(e.target.value as RightOperand["kind"], value))}
        className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
      >
        <option value="number">{t("editor.condition.rightNumber")}</option>
        <option value="string">{t("editor.condition.rightString")}</option>
        <option value="boolean">{t("editor.condition.rightBoolean")}</option>
        <option value="ref">{t("editor.condition.rightRef")}</option>
      </select>
      {value.kind === "number" ? (
        <input
          type="number"
          step="any"
          disabled={readOnly}
          value={value.value}
          onChange={(e) => {
            const n = Number(e.target.value);
            if (!Number.isNaN(n)) onChange({ kind: "number", value: n });
          }}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs font-mono"
        />
      ) : value.kind === "string" ? (
        <input
          type="text"
          disabled={readOnly}
          value={value.value}
          onChange={(e) => onChange({ kind: "string", value: e.target.value })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        />
      ) : value.kind === "boolean" ? (
        <select
          disabled={readOnly}
          value={String(value.value)}
          onChange={(e) => onChange({ kind: "boolean", value: e.target.value === "true" })}
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      ) : (
        <input
          type="text"
          disabled={readOnly}
          placeholder="threshold_param"
          value={value.ref.source === "params" ? value.ref.name : ""}
          onChange={(e) =>
            onChange({ kind: "ref", ref: { source: "params", name: e.target.value } })
          }
          className="rounded-md border border-ap-line bg-white px-2 py-1 text-xs"
        />
      )}
    </div>
  );
}

/** Switching the right-operand "kind" from one form to another resets
 *  to a sensible default value of the new kind. Numbers default to 0,
 *  strings to "", booleans to false, refs to an empty params ref. */
function coerceRight(kind: RightOperand["kind"], prev: RightOperand): RightOperand {
  if (kind === prev.kind) return prev;
  if (kind === "number") return { kind: "number", value: 0 };
  if (kind === "string") return { kind: "string", value: "" };
  if (kind === "boolean") return { kind: "boolean", value: false };
  return { kind: "ref", ref: { source: "params", name: "" } };
}
