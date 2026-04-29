import type { ReactNode } from "react";
import { useEffect } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "react-oidc-context";
import { useTranslation } from "react-i18next";

interface Props {
  children: ReactNode;
}

/**
 * Guards a route behind a valid OIDC session. Three states:
 *
 *  - Loading: render an a11y-friendly status message.
 *  - Authenticated: render children.
 *  - Unauthenticated: bounce to /login with `from` set so the post-login
 *    redirect returns the user to the originally-requested page.
 */
export function ProtectedRoute({ children }: Props): ReactNode {
  const auth = useAuth();
  const location = useLocation();
  const { t } = useTranslation("common");

  useEffect(() => {
    // Re-fire silent renew if we land on a protected page while the token
    // is expiring soon — react-oidc-context handles this automatically,
    // but this hook keeps the intent visible.
  }, [auth.user]);

  if (auth.isLoading) {
    return (
      <p role="status" className="p-6 text-slate-600">
        {t("actions.loading")}
      </p>
    );
  }

  if (!auth.isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}
