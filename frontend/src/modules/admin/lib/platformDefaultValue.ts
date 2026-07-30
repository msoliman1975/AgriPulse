import type { ValueConstraint, ValueSchema } from "@/api/platformDefaults";

/**
 * Value formatting + parsing for the Platform Defaults editor.
 *
 * Kept out of the page component so the rules can be unit-tested directly —
 * they mirror `app/shared/settings/validation.py`, and a drift between the
 * two shows up as a 400 the user can't act on.
 */

/** Locale-aware timestamp; falls back to the raw string if unparseable. */
export function formatTimestamp(iso: string, locale: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(d);
}

/** Compact "0–100" / "one of: a, b" label rendered beside the schema pill. */
export function constraintHint(c: ValueConstraint | null): string | null {
  if (!c) return null;
  if (c.choices) return `one of: ${c.choices.join(", ")}`;
  const { minimum, maximum } = c;
  if (minimum !== undefined && maximum !== undefined) return `${minimum}–${maximum}`;
  if (minimum !== undefined) return `≥ ${minimum}`;
  if (maximum !== undefined) return `≤ ${maximum}`;
  return null;
}

/**
 * `null` renders as the literal `null` so it stays distinct from `""`.
 *
 * The old editor rendered both as an empty string, so touching a nullable
 * row (e.g. the former `email.smtp_host`, whose null meant "use the env
 * config") silently rewrote it to an empty string with no way back.
 */
export function formatValue(value: unknown): string {
  if (value === undefined) return "";
  if (value === null) return "null";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function parseAndValidate(
  raw: string,
  schema: ValueSchema,
  constraint: ValueConstraint | null,
): unknown {
  const trimmed = raw.trim();

  if (trimmed === "null" && (schema === "string" || constraint?.nullable)) {
    return null;
  }

  let parsed: unknown;
  if (schema === "string") {
    parsed = trimmed;
  } else if (schema === "number") {
    const n = Number(trimmed);
    if (trimmed === "" || !Number.isFinite(n)) {
      throw new Error(`Expected a number; got ${trimmed || "(empty)"}.`);
    }
    parsed = n;
  } else if (schema === "boolean") {
    if (trimmed === "true") parsed = true;
    else if (trimmed === "false") parsed = false;
    else throw new Error("Expected `true` or `false`.");
  } else {
    // object / array — JSON-parse, then assert.
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      throw new Error("Expected valid JSON.");
    }
    if (schema === "array" && !Array.isArray(parsed)) {
      throw new Error("Expected a JSON array.");
    }
    if (
      schema === "object" &&
      (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
    ) {
      throw new Error("Expected a JSON object.");
    }
  }

  assertConstraint(parsed, constraint);
  return parsed;
}

function assertConstraint(value: unknown, c: ValueConstraint | null): void {
  if (!c) return;
  if (c.choices && !c.choices.includes(String(value))) {
    throw new Error(`Must be one of: ${c.choices.join(", ")}.`);
  }
  if (typeof value !== "number") return;
  if (c.integer_only && !Number.isInteger(value)) {
    throw new Error("Must be a whole number.");
  }
  if (c.minimum !== undefined && value < c.minimum) {
    throw new Error(`Must be ≥ ${c.minimum}.`);
  }
  if (c.maximum !== undefined && value > c.maximum) {
    throw new Error(`Must be ≤ ${c.maximum}.`);
  }
}
