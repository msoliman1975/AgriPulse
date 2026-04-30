// Decode a JWT payload safely without external deps. We only inspect
// claims for capability gating; signature is already validated by the
// backend on every request, so the frontend treats the JWT as a sealed
// token plus opaque-but-readable claims.

export interface FarmScopeClaim {
  farm_id: string;
  role: string;
}

export interface JwtClaims {
  sub?: string;
  tenant_id?: string;
  tenant_role?: string | null;
  platform_role?: string | null;
  farm_scopes?: FarmScopeClaim[];
  preferred_language?: "en" | "ar";
  preferred_unit?: "feddan" | "acre" | "hectare";
  exp?: number;
  iat?: number;
}

export function decodeJwt(token: string | null | undefined): JwtClaims | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length < 2) return null;
  try {
    const json = atob(padBase64(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
    return JSON.parse(json) as JwtClaims;
  } catch {
    return null;
  }
}

function padBase64(s: string): string {
  const pad = s.length % 4;
  return pad ? s + "=".repeat(4 - pad) : s;
}
