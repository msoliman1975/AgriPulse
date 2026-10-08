import { App as CapApp } from "@capacitor/app";
import { Browser } from "@capacitor/browser";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import {
  ApiError,
  compareVersions,
  fetchAppVersion,
  loadSnapshot,
  writeSnapshot,
  type Holding,
  type Snapshot,
} from "@/api/client";
import {
  APP_LINK_PREFIX,
  completeSignIn,
  currentSession,
  loadSession,
  sessionClaims,
  signOut,
} from "@/auth/session";
import { dirOf, formatDateTime, t, type Lang } from "@/i18n";
import { storedLang, storeLang } from "@/lang";
import { AccountScreen } from "@/screens/AccountScreen";
import { HoldingScreen } from "@/screens/HoldingScreen";
import { HoldingsScreen } from "@/screens/HoldingsScreen";
import { SignInScreen } from "@/screens/SignInScreen";
import { UpdateRequiredScreen } from "@/screens/UpdateRequiredScreen";
import { APP_VERSION } from "@/version";

type Tab = "holdings" | "account";

/** The role the API needs for /investor/*. Anyone else is a staff account. */
const INVESTOR_ROLE = "Investor";

export function App(): ReactNode {
  const [booted, setBooted] = useState(false);
  const [lang, setLangState] = useState<Lang>("ar");
  const [langChosen, setLangChosen] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  const [signInError, setSignInError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("holdings");
  const [open, setOpen] = useState<Holding | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [offline, setOffline] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [update, setUpdate] = useState<{ url: string | null } | null>(null);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    setLangChosen(true);
    void storeLang(l);
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = dirOf(lang);
  }, [lang]);

  // Start: the stored session and language, then the app link listener.
  useEffect(() => {
    void (async () => {
      const [session, l] = await Promise.all([loadSession(), storedLang()]);
      if (l) {
        setLangState(l);
        setLangChosen(true);
      }
      setSignedIn(session !== null);
      setBooted(true);
    })();
    const sub = CapApp.addListener("appUrlOpen", ({ url }) => {
      if (!url.startsWith(APP_LINK_PREFIX)) return;
      void Browser.close().catch(() => undefined);
      completeSignIn(url)
        .then(() => {
          setSignInError(null);
          setSignedIn(true);
        })
        .catch(() => setSignInError("signIn.failed"));
    });
    return () => {
      void sub.then((s) => s.remove());
    };
  }, []);

  const isInvestor = signedIn && sessionClaims().role === INVESTOR_ROLE;

  const doSignOut = useCallback(async () => {
    await signOut();
    await writeSnapshot(null);
    setSnapshot(null);
    setOpen(null);
    setTab("holdings");
    setSignedIn(false);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const { data, offline: off } = await loadSnapshot();
      setSnapshot(data);
      setOffline(off);
      if (!langChosen) setLangState(data.me.preferred_language);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401 && currentSession() === null) {
        setSignedIn(false);
        return;
      }
      setLoadError(t(lang, "common.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [lang, langChosen]);

  // After sign-in: the version check, then the data.
  useEffect(() => {
    if (!isInvestor) return;
    fetchAppVersion()
      .then((v) => {
        if (compareVersions(APP_VERSION, v.min_version) < 0) setUpdate({ url: v.download_url });
      })
      .catch(() => undefined);
    void refresh();
    // refresh() reads lang only for its error text; do not refetch on a switch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isInvestor]);

  // Android back: close the holding first, then leave the app.
  useEffect(() => {
    const sub = CapApp.addListener("backButton", () => {
      if (open) setOpen(null);
      else void CapApp.minimizeApp();
    });
    return () => {
      void sub.then((s) => s.remove());
    };
  }, [open]);

  if (!booted) return <main className="splash" />;
  if (update) return <UpdateRequiredScreen lang={lang} url={update.url} />;
  if (!signedIn) {
    return (
      <SignInScreen
        lang={lang}
        onLang={setLang}
        error={signInError ? t(lang, "signIn.failed") : null}
      />
    );
  }
  if (!isInvestor) {
    return (
      <main className="signin">
        <div className="signin-body">
          <p className="error">{t(lang, "signIn.notInvestor")}</p>
          <button type="button" className="btn btn-block" onClick={() => void doSignOut()}>
            {t(lang, "account.signOut")}
          </button>
        </div>
      </main>
    );
  }
  if (open) return <HoldingScreen lang={lang} holding={open} onBack={() => setOpen(null)} />;

  return (
    <div className="shell">
      <header className="top">
        <div>
          <h1>{t(lang, tab === "holdings" ? "holdings.title" : "account.title")}</h1>
          {snapshot?.me.company_name ? (
            <p className="muted small">{snapshot.me.company_name}</p>
          ) : null}
        </div>
        <button
          type="button"
          className="icon-btn"
          aria-label={t(lang, "common.retry")}
          disabled={loading}
          onClick={() => void refresh()}
        >
          <span aria-hidden className={loading ? "spin" : ""}>
            ↻
          </span>
        </button>
      </header>
      {offline && snapshot ? (
        <p className="banner">
          {t(lang, "common.offline", { t: formatDateTime(lang, snapshot.savedAt) })}
        </p>
      ) : null}
      <div className="content">
        {loadError && !snapshot ? (
          <div className="empty">
            <p>{loadError}</p>
            <button type="button" className="btn" onClick={() => void refresh()}>
              {t(lang, "common.retry")}
            </button>
          </div>
        ) : !snapshot ? (
          <p className="empty muted">…</p>
        ) : tab === "holdings" ? (
          <HoldingsScreen lang={lang} snapshot={snapshot} onOpen={setOpen} />
        ) : (
          <AccountScreen
            lang={lang}
            me={snapshot.me}
            email={sessionClaims().email}
            onLang={setLang}
            onSignOut={() => void doSignOut()}
          />
        )}
        {snapshot && !offline ? (
          <p className="muted small center">
            {t(lang, "common.updated", { t: formatDateTime(lang, snapshot.savedAt) })}
          </p>
        ) : null}
      </div>
      <nav className="tabbar">
        {(["holdings", "account"] as Tab[]).map((k) => (
          <button
            key={k}
            type="button"
            className={tab === k ? "tabbar-item tabbar-on" : "tabbar-item"}
            onClick={() => setTab(k)}
          >
            {t(lang, k === "holdings" ? "nav.holdings" : "nav.account")}
          </button>
        ))}
      </nav>
    </div>
  );
}
