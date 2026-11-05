# ADR 0003 — The Scout app keeps its session in the Android Keystore

**Status:** Accepted
**Date:** 2026-11-05
**Authors:** @msoliman1975

## Context

The Scout app signs in with `offline_access`, so its refresh token is the
sign-in for up to 90 days. It was kept in the WebView's `localStorage`, in
plain text, while a comment claimed the Android Keystore. Device backups could
also copy app data off the phone.

## Decision

Keep the session in the Android Keystore through
`@aparajita/capacitor-secure-storage`, pinned to an exact version. Turn
`android:allowBackup` off.

The plugin encrypts with AES-GCM under a key held in the Keystore. Its Android
code was read before adoption, and it makes no network calls.

`capacitor-secure-storage-plugin` was rejected because it encrypts with RSA
PKCS#1 v1.5 in chunks. `@capacitor/preferences` was rejected because it is
plain `SharedPreferences`, which does not encrypt.

## Consequences

- A new native dependency, which the repo's `mobile` CI job compiles.
- Reading the session is now asynchronous, so `main.tsx` restores it before the
  first render.
- Existing installs keep their sign-in: the old copy is moved across on first
  launch and deleted.
- A Keystore that cannot be read means signed out. With no offline queue in the
  app, that costs a sign-in and nothing else.
- Browser builds fall back to the plugin's `localStorage` store. That is for
  development only, and no production path runs there.
