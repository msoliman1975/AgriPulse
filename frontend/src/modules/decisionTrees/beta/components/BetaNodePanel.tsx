/**
 * The node editor, one form per kind.
 *
 * Every edit writes the whole node back through `setBetaNode`, so the canvas
 * redraws from the same YAML the save will send. That is the contract the
 * current editor uses for structural edits, and it is why the switch bands on
 * the canvas are never a render behind the form.
 *
 * Two rules the form enforces rather than reports:
 *   * a switch's default is always written, never omitted (section 4.3);
 *   * a register node's code comes from the catalogue, never a text box.
 */

import { useTranslation } from "react-i18next";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Field } from "@/components/Field";
import { Pill } from "@/components/Pill";
import type { Finding } from "@/api/decisionTreesBeta";

import { FINDING_SEVERITIES, type FindingSeverity } from "../lib/betaConstants";
import {
  BETA_NODE_KINDS,
  SWITCH_OPS,
  betaNodeKind,
  caseOp,
  caseOperand,
  withCaseOp,
  type BetaNode,
  type BetaNodeKind,
  type CaseOperand,
  type SwitchCase,
  type SwitchOp,
} from "../lib/betaTree";
import { FindingPicker, SourcePill } from "./FindingPicker";
import { ValueRefField } from "./ValueRefField";
import { defaultBetaValueRef, scalarText } from "../lib/betaValueRef";

const SELECT_CLASS = "w-full rounded-lg border border-ap-line px-2.5 py-1.5 text-sm text-ap-ink";

interface BetaNodePanelProps {
  nodeId: string;
  node: BetaNode;
  /** Every node id in the tree, for the "go to" pickers. */
  nodeIds: readonly string[];
  findings: readonly Finding[];
  /** The tree's declared `registers` list. */
  declaredCodes: readonly string[];
  /** Variable names any `set` node writes, for a `vars` reference. */
  knownVarNames: readonly string[];
  readOnly?: boolean;
  onChange: (node: BetaNode) => void;
  onChangeKind: (kind: BetaNodeKind) => void;
  onDeclareCode: (code: string) => void;
  onDelete?: () => void;
}

export function BetaNodePanel({
  nodeId,
  node,
  nodeIds,
  findings,
  declaredCodes,
  knownVarNames,
  readOnly = false,
  onChange,
  onChangeKind,
  onDeclareCode,
  onDelete,
}: BetaNodePanelProps): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const kind = betaNodeKind(node);

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          {t("node.title")}
          <span dir="ltr" className="font-mono text-xs text-ap-muted">
            {nodeId}
          </span>
          <Pill kind="neutral">{t(`canvas.kind.${kind}`)}</Pill>
        </span>
      }
      actions={
        onDelete && !readOnly ? (
          <Button variant="danger" size="sm" onClick={onDelete}>
            {t("canvas.delete")}
          </Button>
        ) : null
      }
      bodyClassName="flex flex-col gap-4"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("node.labelEn")}>
          {(props) => (
            <input
              {...props}
              disabled={readOnly}
              value={node.label_en ?? ""}
              onChange={(e) => onChange({ ...node, label_en: e.target.value })}
              className={SELECT_CLASS}
            />
          )}
        </Field>
        <Field label={t("node.labelAr")}>
          {(props) => (
            <input
              {...props}
              dir="rtl"
              disabled={readOnly}
              value={node.label_ar ?? ""}
              onChange={(e) => onChange({ ...node, label_ar: e.target.value })}
              className={SELECT_CLASS}
            />
          )}
        </Field>
      </div>

      <Field label={t("node.changeKind")} help={t("node.changeKindHelp")}>
        {(props) => (
          <select
            {...props}
            disabled={readOnly}
            value={kind}
            onChange={(e) => onChangeKind(e.target.value as BetaNodeKind)}
            className={SELECT_CLASS}
          >
            {BETA_NODE_KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`canvas.kind.${k}`)}
              </option>
            ))}
          </select>
        )}
      </Field>

      {kind === "condition" ? (
        <ConditionFields node={node} nodeIds={nodeIds} readOnly={readOnly} onChange={onChange} />
      ) : null}

      {kind === "register" ? (
        <RegisterFields
          node={node}
          nodeIds={nodeIds}
          findings={findings}
          declaredCodes={declaredCodes}
          readOnly={readOnly}
          onChange={onChange}
          onDeclareCode={onDeclareCode}
        />
      ) : null}

      {kind === "set" ? (
        <SetFields
          node={node}
          nodeIds={nodeIds}
          knownVarNames={knownVarNames}
          readOnly={readOnly}
          onChange={onChange}
        />
      ) : null}

      {kind === "switch" ? (
        <SwitchFields
          node={node}
          nodeIds={nodeIds}
          knownVarNames={knownVarNames}
          readOnly={readOnly}
          onChange={onChange}
        />
      ) : null}

      {kind === "stop" ? <p className="text-sm text-ap-muted">{t("node.stop.help")}</p> : null}
    </Card>
  );
}

// ---- Node pickers -----------------------------------------------------

function NodeSelect({
  label,
  help,
  value,
  nodeIds,
  readOnly,
  onChange,
}: {
  label: string;
  help?: string;
  value: string;
  nodeIds: readonly string[];
  readOnly: boolean;
  onChange: (id: string) => void;
}): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  return (
    <Field label={label} help={help}>
      {(props) => (
        <select
          {...props}
          dir="ltr"
          disabled={readOnly}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={SELECT_CLASS}
        >
          <option value="">{t("node.unset")}</option>
          {nodeIds.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
      )}
    </Field>
  );
}

// ---- Per-kind forms ---------------------------------------------------

function ConditionFields({
  node,
  nodeIds,
  readOnly,
  onChange,
}: {
  node: BetaNode;
  nodeIds: readonly string[];
  readOnly: boolean;
  onChange: (n: BetaNode) => void;
}): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <NodeSelect
        label={t("node.onMatch")}
        value={node.on_match ?? ""}
        nodeIds={nodeIds}
        readOnly={readOnly}
        onChange={(id) => onChange({ ...node, on_match: id || undefined })}
      />
      <NodeSelect
        label={t("node.onMiss")}
        value={node.on_miss ?? ""}
        nodeIds={nodeIds}
        readOnly={readOnly}
        onChange={(id) => onChange({ ...node, on_miss: id || undefined })}
      />
    </div>
  );
}

function RegisterFields({
  node,
  nodeIds,
  findings,
  declaredCodes,
  readOnly,
  onChange,
  onDeclareCode,
}: {
  node: BetaNode;
  nodeIds: readonly string[];
  findings: readonly Finding[];
  declaredCodes: readonly string[];
  readOnly: boolean;
  onChange: (n: BetaNode) => void;
  onDeclareCode: (code: string) => void;
}): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const code = node.register?.code ?? "";
  const severity = node.register?.severity ?? "warning";
  const picked = findings.find((f) => f.code === code && !f.shadowed) ?? null;
  const notDeclared = code !== "" && !declaredCodes.includes(code);

  return (
    <div className="flex flex-col gap-3">
      <div>
        <p className="mb-1 text-sm font-medium text-ap-ink">{t("node.register.code")}</p>
        {picked ? (
          <p className="mb-2 flex flex-wrap items-center gap-2 text-sm">
            <span dir="ltr" className="font-mono text-xs font-semibold">
              {picked.code}
            </span>
            {/* Which table the code came from — the fold reads platform first,
                so this is what decides whose clause the card quotes. */}
            <SourcePill source={picked.source} />
          </p>
        ) : null}
        <FindingPicker
          findings={findings}
          value={code}
          disabled={readOnly}
          onChange={(next) =>
            onChange({
              ...node,
              register: { code: next, severity },
            })
          }
        />
        {notDeclared ? (
          <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-ap-warn">
            {t("node.register.notDeclared")}
            {!readOnly ? (
              <Button variant="secondary" size="sm" onClick={() => onDeclareCode(code)}>
                {t("node.register.declare")}
              </Button>
            ) : null}
          </p>
        ) : null}
      </div>

      <Field label={t("node.register.severity")} help={t("node.register.severityHelp")}>
        {(props) => (
          <select
            {...props}
            disabled={readOnly}
            value={severity}
            onChange={(e) =>
              onChange({
                ...node,
                register: { code, severity: e.target.value as FindingSeverity },
              })
            }
            className={SELECT_CLASS}
          >
            {FINDING_SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {t(`severity.${s}`)}
              </option>
            ))}
          </select>
        )}
      </Field>

      <NodeSelect
        label={t("node.next")}
        value={node.next ?? ""}
        nodeIds={nodeIds}
        readOnly={readOnly}
        onChange={(id) => onChange({ ...node, next: id || undefined })}
      />
    </div>
  );
}

function SetFields({
  node,
  nodeIds,
  knownVarNames,
  readOnly,
  onChange,
}: {
  node: BetaNode;
  nodeIds: readonly string[];
  knownVarNames: readonly string[];
  readOnly: boolean;
  onChange: (n: BetaNode) => void;
}): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const entries = Object.entries(node.set ?? {});

  const writeEntries = (next: Array<[string, unknown]>): void =>
    onChange({ ...node, set: Object.fromEntries(next) });

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm font-medium text-ap-ink">{t("node.set.title")}</p>
      {entries.length === 0 ? <p className="text-sm text-ap-muted">{t("node.set.empty")}</p> : null}
      {entries.map(([name, value], index) => {
        const isReading = value !== null && typeof value === "object";
        return (
          <div key={index} className="flex flex-col gap-2 rounded-lg border border-ap-line p-3">
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label={t("node.set.name")}>
                {(props) => (
                  <input
                    {...props}
                    dir="ltr"
                    disabled={readOnly}
                    value={name}
                    onChange={(e) => {
                      const next = [...entries];
                      next[index] = [e.target.value, value];
                      writeEntries(next);
                    }}
                    className={SELECT_CLASS}
                  />
                )}
              </Field>
              <Field label={t("node.set.valueKind")}>
                {(props) => (
                  <select
                    {...props}
                    disabled={readOnly}
                    value={isReading ? "reading" : "literal"}
                    onChange={(e) => {
                      const next = [...entries];
                      next[index] = [
                        name,
                        e.target.value === "reading" ? defaultBetaValueRef("indices") : "",
                      ];
                      writeEntries(next);
                    }}
                    className={SELECT_CLASS}
                  >
                    <option value="literal">{t("node.set.literal")}</option>
                    <option value="reading">{t("node.set.reading")}</option>
                  </select>
                )}
              </Field>
            </div>
            {isReading ? (
              <ValueRefField
                label={t("valueRef.source")}
                value={value}
                knownVarNames={knownVarNames}
                disabled={readOnly}
                onChange={(ref) => {
                  const next = [...entries];
                  next[index] = [name, ref];
                  writeEntries(next);
                }}
              />
            ) : (
              <Field label={t("node.set.literal")}>
                {(props) => (
                  <input
                    {...props}
                    disabled={readOnly}
                    value={scalarText(value)}
                    onChange={(e) => {
                      const next = [...entries];
                      next[index] = [name, e.target.value];
                      writeEntries(next);
                    }}
                    className={SELECT_CLASS}
                  />
                )}
              </Field>
            )}
            {!readOnly ? (
              <Button
                variant="secondary"
                size="sm"
                className="self-start"
                onClick={() => writeEntries(entries.filter((_, i) => i !== index))}
              >
                {t("node.set.remove", { name: name || "—" })}
              </Button>
            ) : null}
          </div>
        );
      })}
      {!readOnly ? (
        <Button
          variant="secondary"
          size="sm"
          className="self-start"
          onClick={() => writeEntries([...entries, [`var_${entries.length + 1}`, ""]])}
        >
          {t("node.set.add")}
        </Button>
      ) : null}
      <NodeSelect
        label={t("node.next")}
        value={node.next ?? ""}
        nodeIds={nodeIds}
        readOnly={readOnly}
        onChange={(id) => onChange({ ...node, next: id || undefined })}
      />
    </div>
  );
}

function SwitchFields({
  node,
  nodeIds,
  knownVarNames,
  readOnly,
  onChange,
}: {
  node: BetaNode;
  nodeIds: readonly string[];
  knownVarNames: readonly string[];
  readOnly: boolean;
  onChange: (n: BetaNode) => void;
}): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const sw = node.switch ?? { on: undefined, cases: [], default: "" };
  const cases = sw.cases ?? [];

  /** Every write goes through here, so `default` is present on every save.
   *  A switch with no default is rejected at publish; the designer never
   *  stores one without the key. */
  const writeSwitch = (patch: Partial<NonNullable<BetaNode["switch"]>>): void =>
    onChange({
      ...node,
      switch: {
        on: sw.on,
        cases,
        default: sw.default ?? "",
        ...patch,
      },
    });

  const writeCases = (next: SwitchCase[]): void => writeSwitch({ cases: next });

  return (
    <div className="flex flex-col gap-3">
      <ValueRefField
        label={t("node.switch.on")}
        value={sw.on}
        knownVarNames={knownVarNames}
        disabled={readOnly}
        onChange={(ref) => writeSwitch({ on: ref })}
      />

      <p className="text-sm font-medium text-ap-ink">{t("node.switch.cases")}</p>
      {cases.length === 0 ? (
        <p className="text-sm text-ap-muted">{t("node.switch.noCases")}</p>
      ) : null}
      {cases.map((c, index) => (
        <div
          key={index}
          className="grid items-end gap-2 rounded-lg border border-ap-line p-3 sm:grid-cols-4"
        >
          <Field label={t("node.switch.op")}>
            {(props) => (
              <select
                {...props}
                disabled={readOnly}
                value={caseOp(c) ?? "ge"}
                onChange={(e) => {
                  const nextOp = e.target.value as SwitchOp;
                  const next = [...cases];
                  next[index] = withCaseOp(c, nextOp, defaultOperandFor(nextOp, caseOperand(c)));
                  writeCases(next);
                }}
                className={SELECT_CLASS}
              >
                {SWITCH_OPS.map((op) => (
                  <option key={op} value={op}>
                    {t(`op.${op}`)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          {caseOp(c) === "between" ? (
            <>
              <Field label={t("node.switch.low")}>
                {(props) => (
                  <input
                    {...props}
                    dir="ltr"
                    disabled={readOnly}
                    value={betweenPart(caseOperand(c), 0)}
                    onChange={(e) => {
                      const next = [...cases];
                      next[index] = withCaseOp(c, "between", [
                        parseCaseValue(e.target.value, "ge") as number | string,
                        betweenPart(caseOperand(c), 1),
                      ]);
                      writeCases(next);
                    }}
                    className={SELECT_CLASS}
                  />
                )}
              </Field>
              <Field label={t("node.switch.high")}>
                {(props) => (
                  <input
                    {...props}
                    dir="ltr"
                    disabled={readOnly}
                    value={betweenPart(caseOperand(c), 1)}
                    onChange={(e) => {
                      const next = [...cases];
                      next[index] = withCaseOp(c, "between", [
                        betweenPart(caseOperand(c), 0),
                        parseCaseValue(e.target.value, "ge") as number | string,
                      ]);
                      writeCases(next);
                    }}
                    className={SELECT_CLASS}
                  />
                )}
              </Field>
            </>
          ) : (
            <Field label={t("node.switch.value")}>
              {(props) => (
                <input
                  {...props}
                  dir="ltr"
                  disabled={readOnly}
                  value={caseValueText(caseOperand(c))}
                  onChange={(e) => {
                    const next = [...cases];
                    next[index] = withCaseOp(
                      c,
                      caseOp(c) ?? "ge",
                      parseCaseValue(e.target.value, caseOp(c) ?? "ge"),
                    );
                    writeCases(next);
                  }}
                  className={SELECT_CLASS}
                />
              )}
            </Field>
          )}
          <NodeSelect
            label={t("node.switch.go")}
            value={c.go}
            nodeIds={nodeIds}
            readOnly={readOnly}
            onChange={(id) => {
              const next = [...cases];
              next[index] = { ...c, go: id };
              writeCases(next);
            }}
          />
          {!readOnly ? (
            <div className="flex gap-1">
              <Button
                variant="secondary"
                size="sm"
                aria-label={t("node.switch.moveUp")}
                disabled={index === 0}
                onClick={() => writeCases(swap(cases, index, index - 1))}
              >
                ↑
              </Button>
              <Button
                variant="secondary"
                size="sm"
                aria-label={t("node.switch.moveDown")}
                disabled={index === cases.length - 1}
                onClick={() => writeCases(swap(cases, index, index + 1))}
              >
                ↓
              </Button>
              <Button
                variant="secondary"
                size="sm"
                aria-label={t("node.switch.removeCase", { position: index + 1 })}
                onClick={() => writeCases(cases.filter((_, i) => i !== index))}
              >
                ×
              </Button>
            </div>
          ) : null}
        </div>
      ))}
      {!readOnly ? (
        <Button
          variant="secondary"
          size="sm"
          className="self-start"
          onClick={() => writeCases([...cases, { ge: 0, go: "" }])}
        >
          {t("node.switch.addCase")}
        </Button>
      ) : null}

      <NodeSelect
        label={t("node.switch.default")}
        help={t("node.switch.defaultHelp")}
        value={sw.default ?? ""}
        nodeIds={nodeIds}
        readOnly={readOnly}
        onChange={(id) => writeSwitch({ default: id })}
      />
    </div>
  );
}

// ---- Helpers ----------------------------------------------------------

function swap<T>(list: readonly T[], a: number, b: number): T[] {
  const next = [...list];
  const tmp = next[a];
  next[a] = next[b];
  next[b] = tmp;
  return next;
}

/** One half of a `between` pair, as text for its input. */
function betweenPart(operand: CaseOperand | undefined, index: 0 | 1): number | string {
  if (!Array.isArray(operand)) return "";
  return operand[index] ?? "";
}

/** Carry the operand across an operator change where it still makes sense.
 *  `between` needs a pair and `in` needs a list, so neither inherits a
 *  single value. */
function defaultOperandFor(op: SwitchOp, previous: CaseOperand | undefined): CaseOperand {
  if (op === "between") return Array.isArray(previous) ? previous.slice(0, 2) : ["", ""];
  if (op === "in") return Array.isArray(previous) ? previous : [];
  return Array.isArray(previous) ? "" : (previous ?? "");
}

function caseValueText(value: CaseOperand | undefined): string {
  return Array.isArray(value) ? value.join(", ") : String(value ?? "");
}

/** Read the typed value back. `in` takes a list; everything else takes one
 *  value, kept as a number when it reads as one so the YAML carries `70`
 *  rather than `"70"` and the engine compares numerically. */
function parseCaseValue(text: string, op: SwitchOp): CaseOperand {
  if (op === "in") {
    return text
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => (isNumeric(part) ? Number(part) : part));
  }
  if (text.trim() === "") return "";
  if (isNumeric(text)) return Number(text);
  if (text === "true") return true;
  if (text === "false") return false;
  return text;
}

function isNumeric(text: string): boolean {
  return text.trim() !== "" && Number.isFinite(Number(text));
}
