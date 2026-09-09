/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_OIDC_AUTHORITY: string;
  readonly VITE_OIDC_CLIENT_ID: string;
  readonly VITE_OIDC_REDIRECT_URI: string;
  readonly VITE_OIDC_POST_LOGOUT_REDIRECT_URI: string;
  readonly VITE_OIDC_SCOPE: string;
  /** Client half of the telemetry kill switch. "false" makes track() a no-op
   *  at module level, so the queue is never even allocated. */
  readonly VITE_TELEMETRY_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/** Injected by the vite `define` in vite.config.ts — the build's git SHA. */
declare const __APP_VERSION__: string;
