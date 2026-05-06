import axios, { type AxiosError, type AxiosInstance } from "axios";

import { getAccessToken, triggerSignInRedirect } from "@/auth/token";
import { ApiError, type ProblemDetails } from "./errors";

const baseURL: string = import.meta.env.VITE_API_BASE_URL ?? "/api";

export const apiClient: AxiosInstance = axios.create({
  baseURL,
  // Trust the access token; cookies aren't part of the auth path.
  withCredentials: false,
  headers: {
    Accept: "application/json",
    "Content-Type": "application/json",
  },
});

apiClient.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.set("Authorization", `Bearer ${token}`);
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    // 401 → kick the user back through the OIDC flow. The interceptor
    // never throws on unauthenticated calls because the redirect itself
    // unmounts the React tree.
    //
    // Only redirect when the failing request actually carried a Bearer
    // token. A 401 on an anonymous request means we fired before the
    // OIDC user finished loading — redirecting in that case bounces
    // through Keycloak silent-renew and back, looking like a flicker
    // loop on the home page. Callers gate their requests on token
    // presence; this is the defensive layer.
    const hadAuthHeader = Boolean(error.config?.headers?.Authorization);
    if (error.response?.status === 401 && hadAuthHeader) {
      triggerSignInRedirect();
    }

    const correlationId = error.response?.headers?.["x-correlation-id"] as string | undefined;

    // Lift RFC 7807 payloads into our typed ApiError. If the body isn't
    // problem+json (network failure, opaque proxy error), construct a
    // synthetic problem so callers always see the same shape.
    const data: unknown = error.response?.data;
    if (isProblemDetails(data)) {
      return Promise.reject(new ApiError(data, correlationId));
    }

    const status = error.response?.status ?? 0;
    return Promise.reject(
      new ApiError(
        {
          type: "about:blank",
          title: error.message || "Network error",
          status,
          detail: error.message,
        },
        correlationId,
      ),
    );
  },
);

function isProblemDetails(value: unknown): value is ProblemDetails {
  return (
    typeof value === "object" &&
    value !== null &&
    "title" in value &&
    "status" in value &&
    typeof (value as ProblemDetails).status === "number"
  );
}
