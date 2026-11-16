# ADR 0004 — Crop images on a public, cacheable route

**Status:** Accepted
**Date:** 2026-11-16
**Authors:** AgriPulse platform

## Context

The investor app v2 (`docs/proposals/investor-app-v2-build-plan.md` § 3.1)
shows a picture of each crop: on holding cards, the holding screen, and on the
web on block cards, the plan board and the crop catalogue. The picture is
platform-curated, the same for every tenant, and says nothing about anyone's
farm. It is drawn by `<img>` tags (web) and an Android WebView (investor app),
neither of which can attach the API's bearer token. Every other object in the
uploads bucket is private and reached through short-lived presigned URLs.

## Decision

Platform admins upload a crop (or variety) image through a presigned PUT, the
same three-step flow as attachments. The light worker writes square WebP
renditions at 64, 128 and 256 px next to the original with Pillow. The API
serves the renditions without authentication from
`/api/v1/public/crop-images/<kind>/<owner>/<image>/<size>.webp`, with
`Cache-Control: public, max-age=31536000, immutable`. Every upload gets a new
key, so a new image is a new URL and a cached one never goes stale. API
responses carry `crop_image_url` (256 px) and `crop_icon_url` (64 px),
resolved variety override first, then crop; never the storage key. The public
route reads only keys it builds itself from typed UUIDs under
`platform/crop-images/`, so it cannot be pointed at any other object.

## Consequences

- **Positive:** images load in an `<img>` tag with no token and are cached by
  browsers and the WebView for a year; one rendition set serves web and app.
- **Negative:** Pillow is a new backend dependency (wheels bundle libwebp; no
  system packages). A rendition is missing for the few seconds between
  finalize and the worker run; clients fall back to a lettered avatar, and
  the route answers 404 with `no-store` so the gap is not cached.
- **Neutral:** old images are not deleted on replace or remove, so a cached
  URL keeps working; they are small and sit under `platform/`, outside any
  tenant purge.

## Alternatives considered

- **Presigned GET URLs in responses** — expire, so they cannot be cached for
  long and change on every read, defeating the image cache.
- **Authenticated proxy route** — `<img>` cannot send the bearer token.
- **Renditions in the request** — 5 MB decodes inside an API request; the
  worker already exists for this kind of work.

## Follow-ups

- [x] Update `docs/data_model.md` (`crops.image_s3_key`, `crop_varieties.image_s3_key`).
- [x] Tests: unit (keys, URL resolution, renditions, service) and integration (routes, catalogue, block crops, board).
