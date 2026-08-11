import { useEffect, useState, type ReactNode } from "react";

import { fetchMyFarms, type FarmScope } from "@/api/me";
import { currentSession } from "@/auth/session";
import { t, type Lang } from "@/i18n/strings";
import { ensureDeviceRegistered } from "@/push/register";
import { SignInScreen } from "@/screens/SignInScreen";
import { VisitsScreen } from "@/screens/VisitsScreen";

/**
 * Build-time farm, kept only as a development override. It used to be the
 * only source, which meant one APK per farm — and it failed in the worst
 * possible direction: a scout on any other farm signed in successfully and
 * then saw "couldn't load visits", because the app was asking about a farm
 * their token does not cover.
 */
const FALLBACK_FARM_ID = import.meta.env.VITE_FARM_ID ?? "";

/** Remembered across launches so a two-farm scout is not asked every time. */
const PICKED_FARM_KEY = "agripulse.scout.farm";

export function App(): ReactNode {
  const [signedIn, setSignedIn] = useState(() => currentSession() !== null);
  // Arabic is the default, not a fallback.
  const lang: Lang = (import.meta.env.VITE_LANG as Lang) ?? "ar";

  const [farms, setFarms] = useState<FarmScope[] | null>(null);
  const [farmId, setFarmId] = useState<string>(
    () => localStorage.getItem(PICKED_FARM_KEY) ?? "",
  );

  // Re-register on every launch of a signed-in app, not just at sign-in:
  // FCM rotates tokens on reinstall and restore, and a stale token is a
  // phone that has silently stopped buzzing.
  // Registration is farm-gated, so it waits for the farm to resolve rather
  // than firing at sign-in and 403-ing against a farm the scout does not hold.
  useEffect(() => {
    if (signedIn && farmId) void ensureDeviceRegistered(farmId);
  }, [signedIn, farmId]);

  // Resolve the farm from the token rather than the build. Runs on every
  // launch, not just first sign-in, because a scout can be granted or lose a
  // farm between sessions and the app must follow.
  useEffect(() => {
    if (!signedIn) {
      setFarms(null);
      return;
    }
    let live = true;
    void fetchMyFarms().then((scopes) => {
      if (!live) return;
      setFarms(scopes);
      setFarmId((current) => {
        // Keep an explicit choice only while it is still granted; a farm the
        // scout no longer holds would 403 forever and read as a broken app.
        if (current && scopes.some((s) => s.farm_id === current)) return current;
        if (scopes.length === 1) return scopes[0].farm_id;
        return "";
      });
    });
    return () => {
      live = false;
    };
  }, [signedIn]);

  if (!signedIn) {
    return (
      <div className="app" dir={lang === "ar" ? "rtl" : "ltr"} lang={lang}>
        <SignInScreen lang={lang} onSignedIn={() => setSignedIn(true)} />
      </div>
    );
  }

  // `farms === null` is "still asking"; an empty array is a real answer.
  const resolved = farmId || (farms === null ? FALLBACK_FARM_ID : "");

  return (
    <div className="app" dir={lang === "ar" ? "rtl" : "ltr"} lang={lang}>
      {resolved ? (
        <VisitsScreen lang={lang} farmId={resolved} />
      ) : farms && farms.length === 0 ? (
        // A real state, not an error: enrolled, signed in, and not yet put on
        // a farm. Saying so beats a generic failure the scout cannot act on.
        <p className="empty">{t(lang, "farms.none")}</p>
      ) : farms && farms.length > 1 ? (
        <FarmPicker
          lang={lang}
          farms={farms}
          onPick={(id) => {
            localStorage.setItem(PICKED_FARM_KEY, id);
            setFarmId(id);
          }}
        />
      ) : (
        <p className="empty">{t(lang, "farms.loading")}</p>
      )}
    </div>
  );
}

/**
 * Shown only when a scout genuinely holds more than one farm. The farm id is
 * all the token carries, so the list shows the role alongside it rather than
 * pretending to know farm names the app has never fetched.
 */
function FarmPicker({
  lang,
  farms,
  onPick,
}: {
  lang: Lang;
  farms: FarmScope[];
  onPick: (farmId: string) => void;
}): ReactNode {
  return (
    <div className="screen farmpick">
      <h1>{t(lang, "farms.pick")}</h1>
      <ul>
        {farms.map((f) => (
          <li key={f.farm_id}>
            <button type="button" onClick={() => onPick(f.farm_id)}>
              <span className="role">{f.role}</span>
              <span className="fid">{f.farm_id.slice(0, 8)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
