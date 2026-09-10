// Turning a recorded walk into rows a person can read.
//
// A trace step holds the node's question, the refs it resolved, and whether
// it matched. What a reader needs from that is four things per row: what was
// asked, what was read, what it was tested against, and the answer. This
// module does that translation and nothing else, so it can be tested without
// a screen.

import type { WalkStep } from "@/api/farmHealth";

export interface StepRow {
  nodeId: string;
  /** The node's own question, in the reader's language when the trace has it. */
  question: string;
  /** What the tree read: `indices.cwsi.mean = 0.47`, joined for display. */
  read: string | null;
  /** What it was compared with: `> 0.30`. Null when the node has no test. */
  test: string | null;
  matched: boolean;
}

const OPERATOR_TEXT: Record<string, string> = {
  gt: ">",
  gte: "≥",
  ge: "≥",
  lt: "<",
  lte: "≤",
  le: "≤",
  eq: "=",
  ne: "≠",
  in: "in",
  not_in: "not in",
  between: "between",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A ref as text: `indices.cwsi.mean`, or a literal as itself. */
function sideText(side: unknown): string | null {
  if (side === null || side === undefined) return null;
  if (typeof side === "string" || typeof side === "number" || typeof side === "boolean") {
    return String(side);
  }
  if (!isRecord(side)) return null;
  const source = typeof side.source === "string" ? side.source : null;
  if (source === "indices" && typeof side.index_code === "string") {
    const key = typeof side.key === "string" ? side.key : "mean";
    return `indices.${side.index_code}.${key}`;
  }
  if (source === "params" && typeof side.name === "string") return side.name;
  if (source === "crop_attribute" && typeof side.code === "string") {
    return `crop_attribute.${side.code}`;
  }
  if (source === "block" && typeof side.field === "string") return `block.${side.field}`;
  if (source === "weather" && typeof side.field === "string") return `weather.${side.field}`;
  return source;
}

/**
 * The comparison, as one short phrase.
 *
 * Returns null rather than an empty operator when the shape is not one this
 * knows: a half-rendered test ("indices.cwsi.mean") reads as a fact, and a
 * missing one reads as a node with no test, which is the truth.
 */
export function testText(condition: unknown): string | null {
  if (!isRecord(condition)) return null;
  const tree = isRecord(condition.tree) ? condition.tree : condition;
  if (Array.isArray(tree.all_of) || Array.isArray(tree.any_of)) {
    const parts = (tree.all_of ?? tree.any_of) as unknown[];
    const joiner = Array.isArray(tree.all_of) ? " and " : " or ";
    const rendered = parts.map((part) => testText(part)).filter((x): x is string => x !== null);
    return rendered.length > 0 ? rendered.join(joiner) : null;
  }
  const op = typeof tree.op === "string" ? tree.op : null;
  if (op === null) return null;
  const right = sideText(tree.right) ?? (Array.isArray(tree.values) ? tree.values.join(", ") : null);
  const symbol = OPERATOR_TEXT[op] ?? op;
  return right === null ? symbol : `${symbol} ${right}`;
}

/**
 * One resolved value as text.
 *
 * A null is a fail-closed miss, not a zero, and the two lead to different
 * conclusions. Anything that is not a scalar is refused rather than
 * stringified, because "[object Object]" on a step row reads as a reading.
 */
function valueText(value: unknown): string {
  if (value === null || value === undefined) return "no reading";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map((item) => valueText(item)).join(", ");
  return "—";
}

/** What the node actually read, as `path = value`. */
export function readText(step: WalkStep): string | null {
  const values = step.values;
  if (!isRecord(values)) return null;
  const entries = Object.entries(values);
  if (entries.length === 0) return null;
  return entries.map(([path, value]) => `${path} = ${valueText(value)}`).join(", ");
}

/**
 * The walk as rows.
 *
 * `arabic` picks the node's own label. Reading `label_en` unconditionally is
 * how this app shipped English under Arabic names once already; the label
 * belongs to the tree author, not to the locale file, so it cannot be
 * translated here — only chosen.
 */
export function walkRows(steps: WalkStep[], arabic: boolean): StepRow[] {
  return (
    steps
      // The leaf carries no match, because it is the answer rather than a
      // check. Left in, it drew a final row headed by the leaf's own words
      // and marked "no" — the conclusion, listed as a test that failed. The
      // answer has its own line under the table.
      .filter((step) => typeof step.matched === "boolean")
      .map((step) => ({
        nodeId: step.node_id,
        question: (arabic ? (step.label_ar ?? step.label_en) : step.label_en) ?? step.node_id,
        read: readText(step),
        test: testText(step.condition),
        matched: step.matched === true,
      }))
  );
}

/**
 * How many opening steps two or more walks agree on.
 *
 * Exported for the day a verdict carries a route key and one area can hold
 * several walks. Section 5.6 of the specification describes what it feeds:
 * the shared steps once, then one block per route. Until the API can say
 * which route a cell took, an area shows the one walk it has.
 */
export function sharedPrefix(walks: StepRow[][]): number {
  if (walks.length < 2) return 0;
  const shortest = Math.min(...walks.map((walk) => walk.length));
  let shared = 0;
  for (let i = 0; i < shortest; i += 1) {
    const first = walks[0][i];
    const same = walks.every(
      (walk) => walk[i].nodeId === first.nodeId && walk[i].matched === first.matched,
    );
    if (!same) break;
    shared += 1;
  }
  return shared;
}
