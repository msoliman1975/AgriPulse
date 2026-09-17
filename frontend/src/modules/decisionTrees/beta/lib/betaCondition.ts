/**
 * The condition tree a beta `condition` node carries, as the designer edits it.
 *
 * Until now the beta designer could point a condition node at its two
 * branches but not say what it tested: `condition.tree` was only editable by
 * hand, and the beta screens have no YAML box. So a condition could be read on
 * the canvas and never authored.
 *
 * The dialect is the shared evaluator's, `app/shared/conditions/evaluator.py`,
 * and this module keeps to it exactly:
 *
 *   {all_of: [...]}                       every child must match
 *   {any_of: [...]}                       one child must match
 *   {not: <child>}                        invert
 *   {op: lt|le|gt|ge|eq|ne, left, right}  compare against one value
 *   {op: "between", left, low, high}      a closed range, both ends included
 *   {op: "in", left, values: [...]}       membership
 *
 * `lib/conditionEdit.ts` parses the same dialect for the existing editor, and
 * is deliberately not reused: its value-ref vocabulary has ten sources and
 * beta needs twelve. A beta tree can test a variable a `set` node wrote and a
 * finding a `register` node recorded, and neither exists in the old engine. A
 * shared parser would read both of those as "unsupported" and drop the author
 * into a read-only JSON blob on the two sources the folding engine adds.
 *
 * Every function here is pure and works on the raw object, so there is no
 * second AST to keep in step with the wire shape.
 */

import { asBetaValueRef, scalarText, type BetaValueRef } from "./betaValueRef";

/** Comparison operators, in the order the picker offers them. The same list
 *  the evaluator implements and `SWITCH_CASE_OPS` accepts on the server. */
export const CONDITION_OPS = ["lt", "le", "gt", "ge", "eq", "ne", "between", "in"] as const;
export type ConditionOp = (typeof CONDITION_OPS)[number];

export type GroupMode = "all_of" | "any_of";

/** How deep the editor lets an author nest. The panel is one ~360px column
 *  and each level costs indentation; past this the "add group" button is not
 *  offered. A deeper tree written by hand still renders. */
export const MAX_CONDITION_DEPTH = 3;

export type CondShape = "empty" | "group" | "not" | "term" | "unknown";

export type CondNode = Record<string, unknown>;

/** Which of the five shapes this node is, by the key it carries — the way
 *  the evaluator discriminates it. */
export function condShape(node: unknown): CondShape {
  if (node === null || node === undefined) return "empty";
  if (typeof node !== "object" || Array.isArray(node)) return "unknown";
  const n = node as CondNode;
  if (Array.isArray(n.all_of) || Array.isArray(n.any_of)) return "group";
  if ("not" in n) return "not";
  if (typeof n.op === "string" && (CONDITION_OPS as readonly string[]).includes(n.op)) {
    return "term";
  }
  return "unknown";
}

export function groupMode(node: CondNode): GroupMode {
  return Array.isArray(node.any_of) ? "any_of" : "all_of";
}

export function groupChildren(node: CondNode): unknown[] {
  const children = Array.isArray(node.any_of) ? node.any_of : node.all_of;
  return Array.isArray(children) ? children : [];
}

export function termOp(node: CondNode): ConditionOp {
  return (node.op as ConditionOp) ?? "lt";
}

/** A comparison's left side is always a value-ref. A malformed one reads
 *  back as the default index reading rather than as nothing, so the author
 *  sees a field they can correct. */
export function termLeft(node: CondNode): BetaValueRef {
  return asBetaValueRef(node.left);
}

// ---- Building --------------------------------------------------------

export function defaultTerm(): CondNode {
  return {
    op: "lt",
    left: { source: "indices", index_code: "ndvi", key: "baseline_deviation" },
    right: 0,
  };
}

export function defaultGroup(mode: GroupMode = "all_of"): CondNode {
  return { [mode]: [defaultTerm()] };
}

/**
 * Rewrite a term onto another operator, carrying the operand where it still
 * means the same thing.
 *
 * `between` needs two bounds and `in` needs a list, so neither inherits a
 * single value; going back the other way takes the low bound, which is the
 * number the author last typed on the left of the range.
 */
export function withOp(node: CondNode, op: ConditionOp): CondNode {
  const left = node.left ?? defaultTerm().left;
  if (op === "between") {
    const low = "low" in node ? node.low : (node.right ?? 0);
    const high = "high" in node ? node.high : (node.right ?? 0);
    return { op, left, low, high };
  }
  if (op === "in") {
    const values = Array.isArray(node.values)
      ? node.values
      : node.right === undefined
        ? []
        : [node.right];
    return { op, left, values };
  }
  const right = "right" in node ? node.right : "low" in node ? node.low : 0;
  return { op, left, right };
}

/** Swap a group between "every one of these" and "any one of these", keeping
 *  its children. */
export function withGroupMode(node: CondNode, mode: GroupMode): CondNode {
  return { [mode]: groupChildren(node) };
}

// ---- Editing by path -------------------------------------------------

/**
 * Where one node sits inside the tree: the child index at each level.
 *
 * `[]` is the root, `[0]` its first child, `[0, 1]` the second child of that
 * one. A `not` has exactly one child, at index 0.
 */
export type CondPath = number[];

/** Replace the node at `path`. Passing `null` removes it: a child drops out
 *  of its group, and removing the root empties the condition. */
export function replaceAt(tree: unknown, path: CondPath, next: CondNode | null): unknown {
  if (path.length === 0) return next ?? undefined;
  const node = tree as CondNode;
  const [index, ...rest] = path;
  const shape = condShape(node);

  if (shape === "not") {
    const child = replaceAt(node.not, rest, next);
    if (child === undefined) return undefined;
    return { not: child };
  }

  if (shape === "group") {
    const mode = groupMode(node);
    const children = [...groupChildren(node)];
    if (index < 0 || index >= children.length) return tree;
    const child = replaceAt(children[index], rest, next);
    if (child === undefined) children.splice(index, 1);
    else children[index] = child;
    // A group with nothing left in it is not a condition. `all_of: []`
    // matches every cell and `any_of: []` matches none, and neither is what
    // an author who removed the last test meant.
    if (children.length === 0) return undefined;
    return { [mode]: children };
  }

  return tree;
}

/** Append a child to the group at `path`. */
export function appendChild(tree: unknown, path: CondPath, child: CondNode): unknown {
  const target = nodeAt(tree, path);
  if (!target || condShape(target) !== "group") return tree;
  const mode = groupMode(target);
  return replaceAt(tree, path, { [mode]: [...groupChildren(target), child] });
}

/** The node at `path`, or null when the path does not lead anywhere. */
export function nodeAt(tree: unknown, path: CondPath): CondNode | null {
  let node: unknown = tree;
  for (const index of path) {
    const shape = condShape(node);
    if (shape === "not") {
      node = (node as CondNode).not;
      continue;
    }
    if (shape !== "group") return null;
    const children = groupChildren(node as CondNode);
    if (index < 0 || index >= children.length) return null;
    node = children[index];
  }
  if (node === null || node === undefined || typeof node !== "object") return null;
  return node as CondNode;
}

// ---- Operands --------------------------------------------------------

/** One side of a comparison: a literal the author typed, or another value-ref
 *  — a tree parameter, most often, so one tree can be re-thresholded per
 *  tenant without a second copy. */
export function isRefOperand(value: unknown): boolean {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/** Read a literal back as text for its input. A ref is not a literal, so it
 *  reads back as nothing rather than as "[object Object]" — which is what an
 *  input would otherwise save over the author's own structure. */
export function operandText(value: unknown): string {
  return scalarText(value);
}

/**
 * Read a typed literal back from an input.
 *
 * A number stays a number so the YAML carries `0.35` rather than `"0.35"`:
 * the evaluator compares a string against a number as no-match, without an
 * error, which is the kind of failure nobody sees.
 */
export function parseOperand(text: string): number | string | boolean {
  const trimmed = text.trim();
  if (trimmed === "") return "";
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  if (Number.isFinite(Number(trimmed))) return Number(trimmed);
  return text;
}

/** A comma-separated list for `in`, typed the same way. */
export function parseOperandList(text: string): (number | string | boolean)[] {
  return text
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part !== "")
    .map(parseOperand);
}

export function operandListText(values: unknown): string {
  if (!Array.isArray(values)) return "";
  return values.map((v) => operandText(v)).join(", ");
}
