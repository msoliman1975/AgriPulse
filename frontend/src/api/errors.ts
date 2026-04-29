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
