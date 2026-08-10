import { useEffect, useState, type ReactNode } from "react";

import { currentSession } from "@/auth/session";
import type { Lang } from "@/i18n/strings";
import { ensureDeviceRegistered } from "@/push/register";
import { SignInScreen } from "@/screens/SignInScreen";
import { VisitsScreen } from "@/screens/VisitsScreen";

// Which farm the scout is working. A Scout's token carries exactly one farm
// scope today, so this comes from configuration; when a scout can hold several,
// it becomes a picker rather than a constant.
const FARM_ID = import.meta.env.VITE_FARM_ID ?? "";

export function App(): ReactNode {
  const [signedIn, setSignedIn] = useState(() => currentSession() !== null);
  // Arabic is the default, not a fallback.
  const lang: Lang = (import.meta.env.VITE_LANG as Lang) ?? "ar";

  // Re-register on every launch of a signed-in app, not just at sign-in:
  // FCM rotates tokens on reinstall and restore, and a stale token is a
  // phone that has silently stopped buzzing.
  useEffect(() => {
    if (signedIn) void ensureDeviceRegistered();
  }, [signedIn]);

  return (
    <div className="app" dir={lang === "ar" ? "rtl" : "ltr"} lang={lang}>
      {signedIn ? (
        <VisitsScreen lang={lang} farmId={FARM_ID} />
      ) : (
        <SignInScreen lang={lang} onSignedIn={() => setSignedIn(true)} />
      )}
    </div>
  );
}
