/** PKCE (RFC 7636): a random verifier and its S256 challenge, base64url. */

function base64url(bytes: Uint8Array): string {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function randomString(bytes = 32): string {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return base64url(buf);
}

export async function challengeFor(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

/** The payload of a JWT, without checking it: the api checks every token. */
export function jwtClaims(token: string): Record<string, unknown> {
  const part = token.split(".")[1] ?? "";
  const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  const text = decodeURIComponent(
    Array.from(atob(padded), (c) => "%" + c.charCodeAt(0).toString(16).padStart(2, "0")).join(""),
  );
  return JSON.parse(text) as Record<string, unknown>;
}
