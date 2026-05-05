import { useEffect } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "react-oidc-context";
import { useTranslation } from "react-i18next";

interface CallbackState {
  from?: string;
}

/**
 * Lives at /auth/callback OUTSIDE ProtectedRoute so react-oidc-context
 * can finish processing the `?code=...` exchange without ProtectedRoute
 * bouncing the user back to /login mid-flight (which Keycloak then
 * rebounded back to /auth/callback — a redirect loop).
 *
 * Three states:
 *   - isLoading: render a status message while the code → token exchange
 *     completes.
 *   - error: render the error so the user sees what's wrong instead of
 *     looping silently.
 *   - authenticated: navigate to the original `from` location (preserved
 *     by LoginPage on `auth.signinRedirect`).
 */
export function AuthCallback(): JSX.Element {
  const auth = useAuth();
  const navigate = useNavigate();
  const { t } = useTranslation("common");

  useEffect(() => {
    if (auth.isAuthenticated && !auth.isLoading) {
      const state = auth.user?.state as CallbackState | undefined;
      const from = state?.from ?? "/";
      navigate(from, { replace: true });
    }
  }, [auth.isAuthenticated, auth.isLoading, auth.user, navigate]);

  if (auth.error) {
    return (
      <p role="alert" className="p-6 text-sm text-red-700">
        {auth.error.message}
      </p>
    );
  }

  if (auth.isAuthenticated) {
    // Belt-and-suspenders — the useEffect should have navigated already.
    return <Navigate to="/" replace />;
  }

  return (
    <p role="status" className="p-6 text-slate-600">
      {t("actions.loading")}
    </p>
  );
}
