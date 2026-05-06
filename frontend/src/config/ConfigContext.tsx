/* eslint-disable react-refresh/only-export-components */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useAuth } from "react-oidc-context";

import { getConfig, type ConfigResponse } from "@/api/config";

// Lazy-loaded once on first child mount that needs it. Cached for the
// session — config doesn't change between requests in MVP. Tests can
// inject a value via `<ConfigContext.Provider value={...}>`.

interface ConfigContextValue {
  config: ConfigResponse | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export const ConfigContext = createContext<ConfigContextValue>({
  config: null,
  loading: false,
  error: null,
  reload: () => {},
});

interface ConfigProviderProps {
  children: ReactNode;
  /** Tests inject a value to bypass the network. */
  value?: ConfigResponse;
}

export function ConfigProvider({ children, value }: ConfigProviderProps): JSX.Element {
  const auth = useAuth();
  const accessToken = auth.user?.access_token;
  const [config, setConfig] = useState<ConfigResponse | null>(value ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (): Promise<void> => {
    setLoading(true);
    setError(null);
    try {
      const next = await getConfig();
      setConfig(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (value !== undefined) return; // tests pre-seed
    if (config !== null) return; // already loaded
    // /v1/config is auth-protected. If we fire it before the OIDC user
    // has loaded, the axios 401 interceptor would kick the user back
    // through signinRedirect on every page reload — looking like an
    // auth-server flicker loop.
    if (!accessToken) return;
    void load();
  }, [accessToken, config, load, value]);

  return (
    <ConfigContext.Provider value={{ config, loading, error, reload: () => void load() }}>
      {children}
    </ConfigContext.Provider>
  );
}

/**
 * Throws when invoked outside ConfigProvider OR before the initial load
 * completes. Components that should render a placeholder while loading
 * call `useOptionalConfig()` instead.
 */
export function useConfig(): ConfigResponse {
  const ctx = useContext(ConfigContext);
  if (ctx.config === null) {
    throw new Error("useConfig() called before ConfigContext loaded");
  }
  return ctx.config;
}

export function useOptionalConfig(): {
  config: ConfigResponse | null;
  loading: boolean;
  error: string | null;
} {
  const ctx = useContext(ConfigContext);
  return { config: ctx.config, loading: ctx.loading, error: ctx.error };
}
