/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_KEYCLOAK_ISSUER?: string;
  readonly VITE_KEYCLOAK_CLIENT_ID?: string;
  readonly VITE_KEYCLOAK_REDIRECT_URI?: string;
  readonly VITE_API_BASE_URL?: string;
}
