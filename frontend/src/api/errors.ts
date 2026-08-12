// Typed RFC 7807 problem+json envelope. Backend errors are normalised
// into this shape by app/core/errors.py; the axios interceptor surfaces
// them as ApiError instances callers can pattern-match against.
export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail?: string;
  instance?: string;
  // Backend extensions (correlation_id, validation errors, etc.) flow
  // through unchanged.
  [extensionKey: string]: unknown;
}

export class ApiError extends Error {
  public readonly status: number;
  public readonly problem: ProblemDetails;
  public readonly correlationId?: string;

  constructor(problem: ProblemDetails, correlationId?: string) {
    super(problem.detail ?? problem.title);
    this.name = "ApiError";
    this.status = problem.status;
    this.problem = problem;
    this.correlationId = correlationId;
  }

  /** Convenience for narrowing in switch statements. */
  is(...statuses: number[]): boolean {
    return statuses.includes(this.status);
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

/** One entry of FastAPI's 422 `errors` extension. */
interface ProblemFieldError {
  loc?: unknown[];
  msg?: string;
}

/**
 * Per-field messages from a 422, as "field: what's wrong" lines.
 *
 * A request-validation problem's `detail` is always the same sentence —
 * "One or more request fields failed validation." — while the part that
 * says *which* field and *why* sits in the `errors` extension. Rendering
 * only `detail` leaves the author guessing at which input to fix.
 *
 * Returns [] for any problem without a usable `errors` array, so callers
 * can fall back to `detail` unchanged.
 */
export function problemFieldErrors(problem: ProblemDetails | undefined): string[] {
  const raw = problem?.errors;
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    const { loc, msg } = (entry ?? {}) as ProblemFieldError;
    if (typeof msg !== "string" || msg.trim() === "") return [];
    // `loc` is ["body", "code"] — the leading source segment is noise to
    // an author, who only ever sees one form.
    const field = Array.isArray(loc)
      ? loc.filter((p) => typeof p === "string" && p !== "body" && p !== "query").join(".")
      : "";
    return [field ? `${field}: ${msg}` : msg];
  });
}
