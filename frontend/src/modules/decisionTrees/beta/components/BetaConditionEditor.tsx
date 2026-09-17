/**
 * The editor for a condition node's test.
 *
 * A condition node is the only kind whose body the beta designer could not
 * edit: the canvas drew the test and the panel offered the two branches, and
 * the test itself was reachable only by hand-editing the definition. This is
 * that missing editor, and it offers every operator the engine implements —
 * including `between`, which is the one an author reaches for as soon as a
 * reading has both a floor and a ceiling.
 *
 * Groups nest, so `all_of` and `any_of` are authorable here rather than only
 * readable. The dialect and the pure helpers are `lib/betaCondition.ts`.
 */

import { useTranslation } from "react-i18next";

import { Button } from "@/components/Button";
import { Field } from "@/components/Field";

import {
  CONDITION_OPS,
  MAX_CONDITION_DEPTH,
  appendChild,
  condShape,
  defaultGroup,
  defaultTerm,
  groupChildren,
  groupMode,
  isRefOperand,
  nodeAt,
  operandListText,
  operandText,
  parseOperand,
  parseOperandList,
  replaceAt,
  termLeft,
  termOp,
  withGroupMode,
  withOp,
  type CondNode,
  type CondPath,
  type ConditionOp,
  type GroupMode,
} from "../lib/betaCondition";
import { ValueRefField } from "./ValueRefField";

const CONTROL_CLASS = "w-full rounded-lg border border-ap-line px-2.5 py-1.5 text-sm text-ap-ink";

interface BetaConditionEditorProps {
  /** The raw `condition.tree`. */
  value: unknown;
  /** The whole tree after the edit, ready to write back to `condition.tree`.
   *  `undefined` means the author removed the last test. */
  onChange: (next: unknown) => void;
  knownVarNames?: readonly string[];
  readOnly?: boolean;
}

export function BetaConditionEditor({
  value,
  onChange,
  knownVarNames = [],
  readOnly = false,
}: BetaConditionEditorProps): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const shape = condShape(value);

  const edit = (path: CondPath, next: CondNode | null): void => {
    onChange(replaceAt(value, path, next));
  };

  if (shape === "empty") {
    return (
      <div className="flex flex-col gap-2">
        <p className="text-sm text-ap-muted">{t("condition.empty")}</p>
        {!readOnly ? (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={() => onChange(defaultTerm())}>
              {t("condition.addTest")}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => onChange(defaultGroup())}>
              {t("condition.addGroup")}
            </Button>
          </div>
        ) : null}
      </div>
    );
  }

  if (shape === "unknown") {
    // Not a shape this editor writes. Showing it rather than replacing it:
    // the author's own YAML is not something a screen should quietly drop.
    return (
      <div className="flex flex-col gap-2">
        <p className="text-sm text-ap-warn">{t("condition.unsupported")}</p>
        <pre
          dir="ltr"
          className="max-h-40 overflow-auto rounded-lg bg-ap-bg p-2 text-[11px] text-ap-ink"
        >
          {JSON.stringify(value, null, 2)}
        </pre>
      </div>
    );
  }

  return (
    <CondNodeEditor
      node={value as CondNode}
      path={[]}
      depth={0}
      knownVarNames={knownVarNames}
      readOnly={readOnly}
      onEdit={edit}
      onAddChild={(path, child) => onChange(appendChild(value, path, child))}
      root={value}
    />
  );
}

interface NodeEditorProps {
  node: CondNode;
  path: CondPath;
  depth: number;
  knownVarNames: readonly string[];
  readOnly: boolean;
  onEdit: (path: CondPath, next: CondNode | null) => void;
  onAddChild: (path: CondPath, child: CondNode) => void;
  root: unknown;
}

function CondNodeEditor(props: NodeEditorProps): JSX.Element {
  const shape = condShape(props.node);
  if (shape === "group") return <GroupEditor {...props} />;
  if (shape === "not") return <NotEditor {...props} />;
  if (shape === "term") return <TermEditor {...props} />;
  return <UnsupportedChild node={props.node} />;
}

function UnsupportedChild({ node }: { node: CondNode }): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  return (
    <p className="text-sm text-ap-warn">
      {t("condition.unsupported")} <span dir="ltr">{JSON.stringify(node)}</span>
    </p>
  );
}

function GroupEditor({
  node,
  path,
  depth,
  knownVarNames,
  readOnly,
  onEdit,
  onAddChild,
  root,
}: NodeEditorProps): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const mode = groupMode(node);
  const children = groupChildren(node);

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-ap-line p-2">
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={t("condition.groupMode")}
          disabled={readOnly}
          value={mode}
          onChange={(e) => onEdit(path, withGroupMode(node, e.target.value as GroupMode))}
          className="rounded-lg border border-ap-line px-2 py-1 text-sm text-ap-ink"
        >
          <option value="all_of">{t("condition.allOf")}</option>
          <option value="any_of">{t("condition.anyOf")}</option>
        </select>
        {!readOnly ? (
          <Button variant="ghost" size="sm" onClick={() => onEdit(path, null)}>
            {t("condition.remove")}
          </Button>
        ) : null}
      </div>

      {children.map((child, index) => (
        <CondNodeEditor
          key={index}
          node={(child ?? {}) as CondNode}
          path={[...path, index]}
          depth={depth + 1}
          knownVarNames={knownVarNames}
          readOnly={readOnly}
          onEdit={onEdit}
          onAddChild={onAddChild}
          root={root}
        />
      ))}

      {!readOnly ? (
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={() => onAddChild(path, defaultTerm())}>
            {t("condition.addTest")}
          </Button>
          {depth + 1 < MAX_CONDITION_DEPTH ? (
            <Button variant="secondary" size="sm" onClick={() => onAddChild(path, defaultGroup())}>
              {t("condition.addGroup")}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function NotEditor(props: NodeEditorProps): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const child = nodeAt(props.root, [...props.path, 0]);
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-ap-line p-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-ap-ink">{t("condition.not")}</span>
        {!props.readOnly ? (
          <Button variant="ghost" size="sm" onClick={() => props.onEdit(props.path, null)}>
            {t("condition.remove")}
          </Button>
        ) : null}
      </div>
      {child ? (
        <CondNodeEditor {...props} node={child} path={[...props.path, 0]} depth={props.depth + 1} />
      ) : (
        <p className="text-sm text-ap-warn">{t("condition.unsupported")}</p>
      )}
    </div>
  );
}

function TermEditor({ node, path, knownVarNames, readOnly, onEdit }: NodeEditorProps): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const op = termOp(node);

  const write = (patch: Partial<CondNode>): void => onEdit(path, { ...node, ...patch });

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-ap-line p-2">
      <ValueRefField
        label={t("condition.left")}
        value={termLeft(node)}
        knownVarNames={knownVarNames}
        disabled={readOnly}
        onChange={(ref) => write({ left: ref })}
      />

      <Field label={t("condition.op")}>
        {(fieldProps) => (
          <select
            {...fieldProps}
            disabled={readOnly}
            value={op}
            onChange={(e) => onEdit(path, withOp(node, e.target.value as ConditionOp))}
            className={CONTROL_CLASS}
          >
            {CONDITION_OPS.map((each) => (
              <option key={each} value={each}>
                {t(`op.${each}`)}
              </option>
            ))}
          </select>
        )}
      </Field>

      {op === "between" ? (
        <div className="grid gap-2 sm:grid-cols-2">
          <OperandField
            label={t("condition.low")}
            value={node.low}
            knownVarNames={knownVarNames}
            readOnly={readOnly}
            onChange={(next) => write({ low: next })}
          />
          <OperandField
            label={t("condition.high")}
            value={node.high}
            knownVarNames={knownVarNames}
            readOnly={readOnly}
            onChange={(next) => write({ high: next })}
          />
        </div>
      ) : null}

      {op === "in" ? (
        <Field label={t("condition.values")} help={t("condition.valuesHelp")}>
          {(fieldProps) => (
            <input
              {...fieldProps}
              dir="ltr"
              disabled={readOnly}
              value={operandListText(node.values)}
              onChange={(e) => write({ values: parseOperandList(e.target.value) })}
              className={CONTROL_CLASS}
            />
          )}
        </Field>
      ) : null}

      {op !== "between" && op !== "in" ? (
        <OperandField
          label={t("condition.right")}
          value={node.right}
          knownVarNames={knownVarNames}
          readOnly={readOnly}
          onChange={(next) => write({ right: next })}
        />
      ) : null}

      {!readOnly ? (
        <div>
          <Button variant="ghost" size="sm" onClick={() => onEdit(path, null)}>
            {t("condition.remove")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * One side of a comparison: a value the author types, or a reference to
 * something the walk can read.
 *
 * A reference on the right is how one tree serves several tenants: the
 * threshold is a `params` name rather than a number in the body, and the
 * tenant's own parameters block fills it in.
 */
function OperandField({
  label,
  value,
  knownVarNames,
  readOnly,
  onChange,
}: {
  label: string;
  value: unknown;
  knownVarNames: readonly string[];
  readOnly: boolean;
  onChange: (next: unknown) => void;
}): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const isRef = isRefOperand(value);

  return (
    <div className="flex flex-col gap-2">
      <Field label={label}>
        {(fieldProps) =>
          isRef ? (
            <select
              {...fieldProps}
              disabled
              value="ref"
              className={CONTROL_CLASS}
              aria-hidden="true"
            >
              <option value="ref">{t("condition.operandRef")}</option>
            </select>
          ) : (
            <input
              {...fieldProps}
              dir="ltr"
              disabled={readOnly}
              value={operandText(value)}
              onChange={(e) => onChange(parseOperand(e.target.value))}
              className={CONTROL_CLASS}
            />
          )
        }
      </Field>

      {isRef ? (
        <ValueRefField
          label={t("condition.operandRef")}
          value={value}
          knownVarNames={knownVarNames}
          disabled={readOnly}
          onChange={(ref) => onChange(ref)}
        />
      ) : null}

      {!readOnly ? (
        <div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onChange(isRef ? 0 : { source: "params", name: "" })}
          >
            {isRef ? t("condition.useValue") : t("condition.useRef")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
