import { useCallback, useEffect, useState, type ReactNode } from "react";

import { getFarm } from "@/api/client";
import { fetchMe, type FarmScope } from "@/api/me";
import { currentSession } from "@/auth/session";
import { ALL_FARMS } from "@/components/FarmRail";
import { dirOf, t, type Lang } from "@/i18n";
import { adoptServerLang, initialLang } from "@/i18n/preference";
import { ensureDeviceRegistered } from "@/push/register";
import { AccountSheet } from "@/screens/AccountSheet";
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

/**
 * Which farm the rail is on, or `ALL_FARMS`.
 *
 * This key has had three meanings and is on its last one. It began as the
 * app's *mode*: one farm chosen in a settings screen, and every list, count and
 * capture silently meant that farm until it was changed — a scout on two farms
 * saw half their work and nothing said so. It then became a picker default
 * only, while the lists held every farm and grouped by it.
 *
 * Now it is the farm rail's position, and it is one piece of state rather than
 * two on purpose. The farm the lists are filtered to and the farm a reading is
 * filed against are the same question asked twice, and the way to file a
 * reading against the wrong farm was for those two answers to differ.
 *
 * `ALL_FARMS` is a real, remembered answer: cross-farm lists, and the capture
 * sheet asks outright.
 */
const FARM_KEY = "agripulse.scout.farm";

/** The two places a scout can be. Capture is a button, not a tab: it is an
 *  action taken from wherever you are, not a place you go. And the account is
 *  a sheet, not a tab — see `AccountSheet`. */
type Tab = "tasks" | "records";

export function App(): ReactNode {
  const [signedIn, setSignedIn] = useState(() => currentSession() !== null);
  const [lang, setLang] = useState<Lang>(initialLang);
  const [tab, setTab] = useState<Tab>("tasks");
  const [recording, setRecording] = useState(false);
  const [account, setAccount] = useState(false);
  // A work item open full-screen owns the whole viewport: the tab bar would
  // otherwise sit under a capture form and take a scout out of it mid-reading.
  const [fullScreen, setFullScreen] = useState(false);

  const [userId, setUserId] = useState<string | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [farms, setFarms] = useState<FarmScope[] | null>(null);
  const [farm, setFarm] = useState<string>(
    () => localStorage.getItem(FARM_KEY) ?? ALL_FARMS,
  );
  /**
   * Farm id -> the name people call it.
   *
   * The token carries ids and nothing else, so every screen that named a farm
   * showed eight characters of a UUID. Nobody knows a farm by `019fe30d`.
   * A missing entry is normal, not an error — see the lookup below — so the
   * callers take an id and hand back the best label they have.
   */
  const [farmNames, setFarmNames] = useState<Record<string, string>>({});

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
      // Drop a remembered farm the scout no longer holds. Falling back to
      // ALL_FARMS rather than to some other farm: the app must not quietly
      // start meaning a farm nobody chose.
      setFarm((current) =>
        current && !me.farms.some((s) => s.farm_id === current) ? ALL_FARMS : current,
      );
    });
    return () => {
      live = false;
    };
  }, [signedIn]);

  const scopes: FarmScope[] =
    farms && farms.length > 0
      ? farms
      : farms === null && FALLBACK_FARM_ID
        ? // Development only: the build-time override, shaped like a real grant
          // so nothing downstream has to know it is not one.
          [{ farm_id: FALLBACK_FARM_ID, role: "scout", granted_at: "" }]
        : [];

  // Registration is farm-gated: a Scout holds no tenant role, so a token
  // registered against a farm they do not hold is a 403 and a phone that never
  // buzzes. Every granted farm is registered, not just the one the rail is on
  // — the rail is a view, not a subscription, and keying pushes off it would
  // silently stop them for every other farm.  FCM also rotates tokens on
  // reinstall and restore, so this runs on every launch; a register-once app
  // quietly stops buzzing months later.
  const farmKey = scopes.map((f) => f.farm_id).join(",");
  useEffect(() => {
    if (!signedIn || !farmKey) return;
    for (const id of farmKey.split(",")) void ensureDeviceRegistered(id);
  }, [signedIn, farmKey]);

  // Names for every farm the scout holds. A list where one row has a name and
  // the rest have hex is worse than either.
  //
  // Per-farm failure is expected and survivable. A scout who belongs to two
  // tenants carries one `tenant_id` in their token, so the farm in the other
  // tenant genuinely cannot be read and keeps its id as a label rather than
  // taking the whole screen down with it.
  useEffect(() => {
    if (!farmKey) return;
    let live = true;
    void Promise.all(
      farmKey.split(",").map((id) =>
        getFarm(id)
          .then((farm) => [id, farm.name || farm.code] as const)
          .catch(() => null),
      ),
    ).then((pairs) => {
      if (!live) return;
      setFarmNames(Object.fromEntries(pairs.filter((p): p is [string, string] => p !== null)));
    });
    return () => {
      live = false;
    };
  }, [farmKey]);

  // The document, not just the container: the keyboard, scrollbars and text
  // selection follow the root direction, and Capacitor renders into a plain
  // index.html whose static dir="rtl" would otherwise outlive a switch to
  // English.
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = dirOf(lang);
  }, [lang]);

  /** The farm's name once known, its id until then — never an empty label. */
  const nameOfFarm = useCallback(
    (id: string): string => farmNames[id] ?? id.slice(0, 8),
    [farmNames],
  );

  const pickFarm = useCallback((id: string) => {
    localStorage.setItem(FARM_KEY, id);
    setFarm(id);
  }, []);

  // A scout granted exactly one farm is never asked which. The rail is not
  // rendered for them, so the filter has to follow the grant rather than wait
  // for a tap that cannot happen — and losing a second farm mid-session lands
  // here too.
  const only = scopes.length === 1 ? scopes[0].farm_id : null;
  useEffect(() => {
    if (only) setFarm(only);
  }, [only]);

  if (!signedIn) {
    return (
      <div className="app" dir={dirOf(lang)} lang={lang}>
        <SignInScreen lang={lang} onLangChange={setLang} onSignedIn={() => setSignedIn(true)} />
      </div>
    );
  }

  // Two states that are not the app: still asking, and a real answer of none.
  // `farms === null` is "still asking"; an empty array is a real answer.
  if (scopes.length === 0) {
    return (
      <div className="app" dir={dirOf(lang)} lang={lang}>
        <p className="empty">
          {farms === null
            ? t(lang, "farms.loading")
            : // Enrolled, signed in, and not yet put on a farm. Saying so beats
              // a generic failure the scout cannot act on.
              t(lang, "farms.none")}
        </p>
      </div>
    );
  }

  return (
    <div className="app" dir={dirOf(lang)} lang={lang}>
      {tab === "tasks" ? (
        <TasksScreen
          lang={lang}
          onLangChange={setLang}
          name={name}
          farms={scopes}
          farmName={nameOfFarm}
          farm={farm}
          onFarmChange={pickFarm}
          onOpenAccount={() => setAccount(true)}
          onFullScreen={setFullScreen}
        />
      ) : (
        <RecordsScreen
          lang={lang}
          onLangChange={setLang}
          name={name}
          farms={scopes}
          farmName={nameOfFarm}
          farm={farm}
          onFarmChange={pickFarm}
          onOpenAccount={() => setAccount(true)}
          userId={userId}
        />
      )}

      {recording ? (
        <RecordSheet
          lang={lang}
          farms={scopes}
          farmName={nameOfFarm}
          farm={farm}
          onClose={() => setRecording(false)}
        />
      ) : null}

      {account ? (
        <AccountSheet
          lang={lang}
          name={name}
          farms={scopes}
          farmName={nameOfFarm}
          onClose={() => setAccount(false)}
        />
      ) : null}

      {!fullScreen && !recording ? (
        <>
          {/* Recording is reachable from both screens, because the thing worth
              recording is noticed while reading either one. */}
          <button type="button" className="fab" onClick={() => setRecording(true)}>
            {t(lang, "record.fab")}
          </button>
          <nav className="tabs">
            {(["tasks", "records"] as Tab[]).map((k) => (
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
