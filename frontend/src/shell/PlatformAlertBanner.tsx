import clsx from "clsx";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { useCapability } from "@/rbac/useCapability";
import { usePlatformAlertSummary } from "@/queries/platformAlerts";

/**
 * App-wide red bar for platform admins when something is broken.
 *
 * Mounted in <AppShell>, not in <PlatformLayout>, and that is the whole
 * point. A banner that only renders under /platform/* is only seen by
 * someone who already went looking at the platform portal — which is
 * exactly the trip an operator does not make on a day when they have no
 * reason to suspect anything. The failure this exists to stop was four days
 * of silence, so it has to reach the operator wherever they happen to be.
 *
 * Not dismissible. The way to clear it is to fix or resolve the alert; a
 * dismiss control would turn "the platform is broken" into a thing you
 * click past on the way to something else.
 */
export function PlatformAlertBanner(): ReactNode {
  const { t } = useTranslation("admin");
  const isPlatformAdmin = useCapability("platform.manage_tenants");
  // The hook is held unconditionally and gated by `enabled` — calling it
  // conditionally would break the rules of hooks, and firing the request
  // for a tenant user would only earn a 403.
  const { data } = usePlatformAlertSummary(isPlatformAdmin);

  if (!isPlatformAdmin || !data) return null;

  const { critical, warning } = data;
  if (critical + warning === 0) return null;

  // Red when anything is critical, amber when only warnings stand. The
  // distinction is worth keeping: an operator who learns that the bar is
  // sometimes amber stops reading red as routine.
  const isCritical = critical > 0;

  return (
    <div
      role="alert"
      className={clsx(
        "flex w-full items-center justify-center gap-3 px-4 py-1.5 text-sm font-medium text-white",
        isCritical ? "bg-ap-crit" : "bg-ap-warn",
      )}
    >
      <span>
        {isCritical
          ? t("platformAlerts.banner.critical", { count: critical })
          : t("platformAlerts.banner.warning", { count: warning })}
      </span>
      {isCritical && warning > 0 ? (
        <span className="opacity-80">
          {t("platformAlerts.banner.alsoWarnings", { count: warning })}
        </span>
      ) : null}
      <Link
        to="/platform/alerts"
        className="rounded bg-white/20 px-2 py-0.5 underline-offset-2 hover:bg-white/30 hover:underline"
      >
        {t("platformAlerts.banner.review")}
      </Link>
    </div>
  );
}
