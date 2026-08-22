import { Component, type ErrorInfo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";

import { Button } from "./Button";

/**
 * The last line of defence for a render that throws.
 *
 * Until this existed there was no error boundary anywhere in the app. React
 * unmounts the whole tree when a render throws and nothing catches it, so a
 * single bad page took the header, the nav and the platform alert bar with
 * it and left the browser showing a blank white document. That is the worst
 * possible failure to debug from a user's description, because "nothing is
 * there" looks identical to a permissions problem, a bad URL, a failed
 * deploy and an empty list.
 *
 * `/platform/alerts` shipped that way: it handed <DataTable> a response
 * envelope instead of the rows, `.map()` threw, and the page rendered
 * nothing at all.
 *
 * Two rules this follows:
 *
 *  - The error is shown, not hidden. A boundary that renders an empty div
 *    is the same blank page with more code.
 *  - It resets on navigation. React keeps a boundary latched after it
 *    catches, so without the `key` on the route boundary, clicking away
 *    from a broken page would leave the error panel up on every page after
 *    it.
 */

interface Props {
  children: ReactNode;
  /** Rendered instead of the default panel. Receives the thrown value. */
  fallback?: (error: unknown, reset: () => void) => ReactNode;
  /** Called when a render throws. Used for logging. */
  onError?: (error: unknown, info: ErrorInfo) => void;
}

interface State {
  error: unknown;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    // The console is where a developer looks first, and React's own
    // "the above error occurred" message does not include the component
    // stack once a boundary handles it.
    console.error("Unhandled render error", error, info.componentStack);
    this.props.onError?.(error, info);
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    if (this.state.error === null) return this.props.children;
    if (this.props.fallback) return this.props.fallback(this.state.error, this.reset);
    return <ErrorPanel error={this.state.error} reset={this.reset} />;
  }
}

function messageOf(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string" && error) return error;
  return "";
}

function ErrorPanel({ error, reset }: { error: unknown; reset: () => void }): ReactNode {
  const { t } = useTranslation("common");
  const detail = messageOf(error);
  return (
    <div className="mx-auto max-w-lg p-6">
      <div role="alert" className="rounded-md bg-ap-panel p-6 shadow-card">
        <h2 className="text-base font-semibold text-ap-ink">{t("errorBoundary.title")}</h2>
        <p className="mt-2 text-sm text-ap-muted">{t("errorBoundary.body")}</p>
        {detail ? (
          // The raw message, on purpose. An operator reporting "it is
          // blank" costs a debugging session; one reporting "it says
          // data.map is not a function" costs a search.
          <pre className="mt-3 overflow-x-auto rounded bg-ap-bg p-3 text-xs text-ap-muted">
            {detail}
          </pre>
        ) : null}
        <div className="mt-4 flex gap-2">
          <Button variant="secondary" onClick={reset}>
            {t("errorBoundary.retry")}
          </Button>
          <Button variant="secondary" onClick={() => window.location.reload()}>
            {t("errorBoundary.reload")}
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * Boundary for the routed page area. Keyed on the pathname so navigating
 * to another page clears a latched error without a full reload.
 */
export function RouteErrorBoundary({ children }: { children: ReactNode }): ReactNode {
  const { pathname } = useLocation();
  return <ErrorBoundary key={pathname}>{children}</ErrorBoundary>;
}

/**
 * Boundary for everything above the routes - header, nav, providers.
 *
 * Its fallback cannot use the shell (the shell is what failed) and cannot
 * use `reset` either: re-rendering the same broken tree in place would
 * throw again immediately. It offers the way home instead.
 */
export function AppErrorBoundary({ children }: { children: ReactNode }): ReactNode {
  return (
    <ErrorBoundary fallback={(error) => <ShellFallback error={error} />}>{children}</ErrorBoundary>
  );
}

function ShellFallback({ error }: { error: unknown }): ReactNode {
  const detail = messageOf(error);
  // No `useTranslation` here. i18n initialisation is one of the things that
  // can fail above the routes, and a fallback that needs the thing that
  // broke is not a fallback.
  return (
    <div className="mx-auto max-w-lg p-6">
      <div role="alert" className="rounded-md bg-ap-panel p-6 shadow-card">
        <h2 className="text-base font-semibold text-ap-ink">AgriPulse could not start</h2>
        <p className="mt-2 text-sm text-ap-muted">
          Something failed before the page could load. Reloading usually clears it.
        </p>
        {detail ? (
          <pre className="mt-3 overflow-x-auto rounded bg-ap-bg p-3 text-xs text-ap-muted">
            {detail}
          </pre>
        ) : null}
        <div className="mt-4">
          <Button variant="secondary" onClick={() => window.location.reload()}>
            Reload
          </Button>
        </div>
      </div>
    </div>
  );
}
