import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { PageHeader } from "@/components/PageHeader";

/** The app's custom scheme, registered in mobile-investor's AndroidManifest. */
const APP_SCHEME = "cloud.agripulse.investor";
const APP_PACKAGE = "cloud.agripulse.investor";

/**
 * /investor-app/callback — public, outside the sign-in guard.
 *
 * The AgriPulse Investor app signs in through Keycloak in the system browser,
 * with PKCE. Keycloak returns here, because the web client already allows
 * this host, and this page hands `code` and `state` to the app. The code is
 * useless without the verifier, which stays in the app.
 *
 * Chrome on Android opens an `intent://` link more reliably than a bare
 * custom scheme; the button covers a browser that blocks the automatic hop.
 */
export function InvestorAppCallbackPage(): JSX.Element {
  const { t } = useTranslation("investors");
  const query = window.location.search;
  const appLink = `${APP_SCHEME}://callback${query}`;
  const intentLink = useMemo(
    () => `intent://callback${query}#Intent;scheme=${APP_SCHEME};package=${APP_PACKAGE};end`,
    [query],
  );
  const isAndroid = /Android/i.test(navigator.userAgent);

  useEffect(() => {
    window.location.replace(isAndroid ? intentLink : appLink);
  }, [appLink, intentLink, isAndroid]);

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4 p-6 text-center">
      <PageHeader title={t("appCallback.title")} subtitle={t("appCallback.body")} />
      <a
        href={isAndroid ? intentLink : appLink}
        className="rounded-md bg-ap-primary px-4 py-2 text-sm font-medium text-white"
      >
        {t("appCallback.open")}
      </a>
    </main>
  );
}
