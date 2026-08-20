# R2 bucket CORS

Every photo in this platform is uploaded **straight from the browser to R2**
with a presigned PUT — the Scout app's flag and reading photos, and the web
console's farm and block attachments. The bytes never pass through the API,
which is what keeps a 4 MB photo on a field connection from occupying an API
worker.

That makes the upload a cross-origin request, and R2 refuses cross-origin
requests unless the bucket carries a CORS policy. Until 2026-08-19 this bucket
had none, so **every browser upload the platform has ever attempted was blocked
at the preflight**:

```
OPTIONS <presigned-url>  Origin: https://localhost
-> 403  CORS not configured for this bucket
```

There were zero attachment rows in any production tenant, on any surface,
which is what that looks like from the database.

## Why the origins are what they are

| Origin | Who |
| --- | --- |
| `https://localhost` | the Scout APK — Capacitor serves the app from `localhost`, and `capacitor.config.ts` sets `androidScheme: "https"` for a production build |
| `http://localhost` | the same, for a dev build, where `androidScheme` is `http` |
| `https://app.agripulse.cloud` | the web console |

`Content-Type` is signed into the presigned URL, so every upload carries a
custom header and a preflight is **always** required. There is no client-side
way to avoid it.

## Applying it

The policy lives here rather than in somebody's dashboard history, so it is
reviewable and survives the bucket being recreated. Apply it with the
**Set R2 bucket CORS** workflow (`workflow_dispatch`), which needs
`CLOUDFLARE_API_TOKEN` to carry R2 **Admin** permission — the API's own R2
credential is object-scoped and returns `AccessDenied` on `PutBucketCors`.

Equivalent by hand: Cloudflare → R2 → `agripulse-imagery` → Settings → CORS
Policy.

## Applied 2026-08-19

Verified against a live presigned URL from the production node, which is the
only check that means anything — the preflight is what was failing:

```
OPTIONS <presigned-url>  Origin: https://localhost
-> 204  Access-Control-Allow-Origin: https://localhost
        Access-Control-Allow-Methods: PUT, GET, HEAD
```

Then end to end: PUT a real JPEG → 200, raise a flag carrying its key → 201
with one photo and a working download URL. The test flag and its object were
removed afterwards.
