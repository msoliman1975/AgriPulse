import type { ReactNode } from "react";
import { useEffect } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "react-oidc-context";
import { useTranslation } from "react-i18next";

interface RedirectState {
  from?: { pathname?: string };
}

export function LoginPage(): ReactNode {
  const auth = useAuth();
  const location = useLocation();
  const { t } = useTranslation("auth");

  // The OIDC redirect target after a successful sign-in. Defaults to /
  // when the user navigated to /login directly.
  const from = (location.state as RedirectState | null)?.from?.pathname ?? "/";

  // Auto-trigger the redirect for SPA-style flows so the user does not
  // see a button when already mid-flow. We still render a button for
  // the no-JS / blocked-redirect fallback path.
  useEffect(() => {
    if (!auth.isAuthenticated && !auth.activeNavigator && !auth.isLoading) {
      void auth.signinRedirect({ state: { from } });
    }
  }, [auth, from]);

  if (auth.isAuthenticated) {
    return <Navigate to={from} replace />;
  }

  const onClick = (): void => {
    void auth.signinRedirect({ state: { from } });
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-sand-50 px-4">
      <div className="card w-full max-w-md">
        <h1 className="text-2xl font-semibold text-brand-800">{t("login.heading")}</h1>
        <p className="mt-2 text-sm text-slate-600">{t("login.subheading")}</p>
        <p className="mt-4 text-sm text-slate-500" aria-live="polite">
          {auth.activeNavigator ? t("login.redirecting") : null}
        </p>
        <button type="button" onClick={onClick} className="btn-primary mt-6 w-full">
          {t("login.signInButton")}
        </button>
      </div>
    </div>
  );
}
