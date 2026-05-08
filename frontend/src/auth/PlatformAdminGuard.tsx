import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useCapability } from "@/rbac/useCapability";

interface Props {
  children: ReactNode;
}

/**
 * Wraps platform-admin routes. Renders children when the JWT grants
 * `platform.manage_tenants`; otherwise renders an inline 403 panel.
 *
 * Why a 403 page instead of a redirect: hiding the route would leave a
 * support engineer wondering if the URL is wrong. An explicit message
 * tells them the URL is right but their account isn't authorized.
 */
export function PlatformAdminGuard({ children }: Props): ReactNode {
  const granted = useCapability("platform.manage_tenants");
  const { t } = useTranslation("admin");

  if (!granted) {
    return (
      <div role="alert" className="mx-auto max-w-lg rounded-md bg-ap-panel p-6 shadow-card">
        <h1 className="text-base font-semibold text-ap-ink">
          {t("guard.forbiddenTitle")}
        </h1>
        <p className="mt-2 text-sm text-ap-muted">{t("guard.forbiddenBody")}</p>
      </div>
    );
  }

  return <>{children}</>;
}
