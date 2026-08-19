import { useEffect, useState, type ReactNode } from "react";

import { fetchMe, type FarmScope } from "@/api/me";
import { currentSession } from "@/auth/session";
import { dirOf, t, type Lang } from "@/i18n";
import { adoptServerLang, initialLang } from "@/i18n/preference";
import { ensureDeviceRegistered } from "@/push/register";
import { MeScreen } from "@/screens/MeScreen";
import { RecordSheet } from "@/screens/RecordSheet";
import { RecordsScreen } from "@/screens/RecordsScreen";
import { SignInScreen } from "@/screens/SignInScreen";
import { TasksScreen } from "@/screens/TasksScreen";

/**
 * Build-time farm, kept only as a development override. It used to be the only
 * source, which meant one APK per farm — and it failed in the worst direction:
 * a scout on any other farm signed in successfully and then saw "couldn't load
 * visits", because the app was asking about a farm their token does not cover.
 * Unset in `.env.production` on purpose.
 */
const FALLBACK_FARM_ID = import.meta.env.VITE_FARM_ID ?? "";

/** Remembered across launches so a two-farm scout is not asked every time. */
const PICKED_FARM_KEY = "agripulse.scout.farm";

/** The three places a scout can be. Capture is a button, not a tab: it is an
 *  action taken from wherever you are, not a place you go. */
type Tab = "tasks" | "records" | "me";

export function App(): ReactNode {
  const [signedIn, setSignedIn] = useState(() => currentSession() !== null);
  const [lang, setLang] = useState<Lang>(initialLang);
  const [tab, setTab] = useState<Tab>("tasks");
  const [recording, setRecording] = useState(false);
  // A work item open full-screen owns the whole viewport: the tab bar would
  // otherwise sit under a capture form and take a scout out of it mid-reading.
  const [fullScreen, setFullScreen] = useState(false);

  const [userId, setUserId] = useState<string | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [farms, setFarms] = useState<FarmScope[] | null>(null);
  const [farmId, setFarmId] = useState<string>(
    () => localStorage.getItem(PICKED_FARM_KEY) ?? "",
  );

  // One call answers both questions the app has after sign-in: where this
  // person may work, and which language to open in. Runs on every launch, not
  // just first sign-in, because a scout can gain or lose a farm between
  // sessions and the app has to follow.
  //
  // Failure is silent by design: the app is already usable in whatever
  // language it opened in, and blocking the visit list on a preference lookup
  // would be a worse trade for someone standing in a field.
  useEffect(() => {
    if (!signedIn) {
      setFarms(null);
      return;
    }
    let live = true;
    void fetchMe().then((me) => {
      if (!live) return;
      setFarms(me.farms);
      setUserId(me.userId);
      setName(me.name);
      // A choice made on this device wins — `adoptServerLang` enforces that,
      // not this call site.
      if (me.language) setLang(adoptServerLang(me.language));
      setFarmId((current) => {
        // Keep an explicit choice only while it is still granted; a farm the
        // scout no longer holds would 403 forever and read as a broken app.
        if (current && me.farms.some((s) => s.farm_id === current)) return current;
        if (me.farms.length === 1) return me.farms[0].farm_id;
        return "";
      });
    });
    return () => {
      live = false;
    };
  }, [signedIn]);

  // Registration is farm-gated, so it waits for the farm to resolve rather
  // than firing at sign-in and 403-ing against a farm the scout does not hold.
  // FCM also rotates tokens on reinstall and restore, so this runs on every
  // launch — a register-once app quietly stops buzzing months later.
  useEffect(() => {
    if (signedIn && farmId) void ensureDeviceRegistered(farmId);
  }, [signedIn, farmId]);

  // The document, not just the container: the keyboard, scrollbars and text
  // selection follow the root direction, and Capacitor renders into a plain
  // index.html whose static dir="rtl" would otherwise outlive a switch to
  // English.
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = dirOf(lang);
  }, [lang]);

  if (!signedIn) {
    return (
      <div className="app" dir={dirOf(lang)} lang={lang}>
        <SignInScreen lang={lang} onLangChange={setLang} onSignedIn={() => setSignedIn(true)} />
      </div>
    );
  }

  // `farms === null` is "still asking"; an empty array is a real answer.
  const resolved = farmId || (farms === null ? FALLBACK_FARM_ID : "");

  if (resolved) {
    return (
      <div className="app" dir={dirOf(lang)} lang={lang}>
        {tab === "tasks" ? (
          <TasksScreen
            lang={lang}
            onLangChange={setLang}
            name={name}
            farmId={resolved}
            onFullScreen={setFullScreen}
          />
        ) : tab === "records" ? (
          <RecordsScreen lang={lang} farmId={resolved} userId={userId} />
        ) : (
          <MeScreen
            lang={lang}
            onLangChange={setLang}
            name={name}
            farms={farms ?? []}
            farmId={resolved}
            onPickFarm={(id) => {
              localStorage.setItem(PICKED_FARM_KEY, id);
              setFarmId(id);
            }}
          />
        )}

        {recording ? (
          <RecordSheet lang={lang} farmId={resolved} onClose={() => setRecording(false)} />
        ) : null}

        {!fullScreen && !recording ? (
          <>
            {/* Recording is reachable from both list screens, because the
                thing worth recording is noticed while reading either one. */}
            {tab !== "me" ? (
              <button type="button" className="fab" onClick={() => setRecording(true)}>
                {t(lang, "record.fab")}
              </button>
            ) : null}
            <nav className="tabs">
              {(["tasks", "records", "me"] as Tab[]).map((k) => (
                <button
                  key={k}
                  type="button"
                  className={k === tab ? "on" : ""}
                  onClick={() => setTab(k)}
                >
                  {t(lang, `tab.${k}` as never)}
                </button>
              ))}
            </nav>
          </>
        ) : null}
      </div>
    );
  }

  return (
    <div className="app" dir={dirOf(lang)} lang={lang}>
      {farms && farms.length === 0 ? (
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
