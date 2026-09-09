import { track } from "./index";
import { routeTemplate } from "./routes";

/**
 * Automatic struggle capture: failed API calls and uncaught JavaScript.
 *
 * These two are the whole "where do users struggle?" question in the MVP. No
 * session replay, no rage-click SDK — just the errors the app already knows
 * about and, until now, threw away.
 */

/** UUID or "not a uuid". The server column is typed, so a junk value would
 *  cost the whole event; a missing one costs only the join. */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function currentRoute(): string {
  try {
    return routeTemplate(window.location.pathname);
  } catch {
    return "unknown";
  }
}

/**
 * Turn an RFC-7807 `type` URI into a short, low-cardinality code.
 *
 * The full URI is stable but long, and the last segment is what anyone
 * actually groups by. `about:blank` — what the interceptor synthesises for a
 * network failure with no body — becomes `network_error`, which is the more
 * honest name for that case anyway.
 */
export function errorCodeFrom(problemType: string | undefined, status: number): string {
  if (!problemType || problemType === "about:blank") {
    return status === 0 ? "network_error" : `http_${status}`;
  }
  const tail = problemType.split(/[/#]/).filter(Boolean).pop();
  return (tail ?? `http_${status}`).slice(0, 64);
}

/**
 * One failed HTTP call.
 *
 * `route` is the page the user was on, not the API path. "Which surface is
 * error-dense" is the product question; the API path is already in the server
 * logs, and the `correlation_id` joins the two for free — that header is the
 * single most valuable thing this event carries.
 */
/**
 * The failing endpoint, with every id replaced by a placeholder.
 *
 * Same rule as page routes: a template groups, a resolved path does not — and
 * a resolved path smuggles farm and block ids into a text column that the
 * props allow-list exists to keep clean. `/api/v1/farms/8f3a.../blocks/12`
 * becomes `/api/v1/farms/:id/blocks/:n`.
 *
 * Query strings are dropped whole. They carry filter values, which are user
 * input, and no grouping question needs them.
 */
export function apiRouteTemplate(url: string | undefined): string {
  if (!url) return "unknown";
  const path = url.split("?")[0].split("#")[0];
  return path
    .replace(/\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, "/:id")
    .replace(/\/\d+/g, "/:n")
    .slice(0, 128);
}

export function reportApiError(args: {
  status: number;
  method?: string;
  problemType?: string;
  correlationId?: string;
  url?: string;
}): void {
  const correlation =
    args.correlationId && UUID_RE.test(args.correlationId) ? args.correlationId : undefined;
  track("api_error", {
    route: currentRoute(),
    outcome: "error",
    status_code: args.status,
    error_code: errorCodeFrom(args.problemType, args.status),
    correlation_id: correlation,
    props: {
      method: (args.method ?? "").toUpperCase().slice(0, 8) || "UNKNOWN",
      problem_type: (args.problemType ?? "about:blank").slice(0, 128),
      api_route: apiRouteTemplate(args.url),
    },
  });
}

/**
 * One uncaught render error, window error, or unhandled rejection.
 *
 * The message is deliberately NOT sent. A thrown message interpolates whatever
 * the code put in it — a farm name, a block note, an email address — and this
 * store has an allow-list precisely so that cannot happen. `digest` is a
 * fingerprint of the first stack frame: enough to group repeats, useless as
 * data. Real stack traces are Phase B, through self-hosted GlitchTip.
 */
export function reportClientError(error: unknown, component?: string): void {
  track("client_error", {
    route: currentRoute(),
    outcome: "error",
    error_code: errorNameOf(error),
    props: {
      component: (component ?? "unknown").slice(0, 64),
      digest: digestOf(error),
    },
  });
}

function errorNameOf(error: unknown): string {
  if (error instanceof Error && error.name) return error.name.slice(0, 64);
  return "Error";
}

/** First stack frame, stripped of the host and query so two users on two
 *  deploys of the same bug fingerprint alike. Never the message. */
function digestOf(error: unknown): string {
  if (!(error instanceof Error) || !error.stack) return "no-stack";
  const frames = error.stack.split("\n").slice(1);
  const first = frames.find((f) => f.trim().length > 0);
  if (!first) return "no-stack";
  return first
    .trim()
    .replace(/https?:\/\/[^/]+/g, "")
    .replace(/\?[^\s)]*/g, "")
    .slice(0, 120);
}

let installed = false;

/** Idempotent. Registers the two listeners React boundaries cannot see:
 *  errors thrown outside render, and rejected promises nobody awaited. */
export function installGlobalErrorCapture(): void {
  if (installed) return;
  installed = true;
  window.addEventListener("error", (event) => {
    reportClientError(event.error ?? new Error("window.onerror"), "window");
  });
  window.addEventListener("unhandledrejection", (event) => {
    reportClientError(event.reason, "unhandledrejection");
  });
}
