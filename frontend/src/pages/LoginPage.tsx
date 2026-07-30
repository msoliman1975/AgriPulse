import type { ReactNode } from "react";
import { useEffect, useRef } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "react-oidc-context";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";

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

  // One-shot guard so a chatty parent re-render (or React 18 StrictMode
  // double-mount) can't fire `signinRedirect` more than once. Without
  // this, every fresh `auth` object reference re-ran the effect — the
  // browser flickered between `/login` and Keycloak as multiple
  // redirects raced.
  const triggered = useRef(false);

  useEffect(() => {
    if (auth.isAuthenticated || auth.activeNavigator || auth.isLoading) {
      return;
    }
    if (triggered.current) {
      return;
    }
    triggered.current = true;
    void auth.signinRedirect({ state: { from } });
    // Depend on the primitives we actually read, not the whole `auth`
    // object — `auth` is a fresh reference on every parent render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.isAuthenticated, auth.activeNavigator, auth.isLoading, from]);

  if (auth.isAuthenticated) {
    return <Navigate to={from} replace />;
  }

  const onClick = (): void => {
    void auth.signinRedirect({ state: { from } });
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-ap-bg px-4">
      <Card className="w-full max-w-md">
        <h2 className="text-2xl font-semibold text-ap-ink">{t("login.heading")}</h2>
        <p className="mt-2 text-sm text-ap-muted">{t("login.subheading")}</p>
        <p className="mt-4 text-sm text-ap-muted" aria-live="polite">
          {auth.activeNavigator ? t("login.redirecting") : null}
        </p>
        <Button className="mt-6 w-full" onClick={onClick}>
          {t("login.signInButton")}
        </Button>
      </Card>
    </div>
  );
}
