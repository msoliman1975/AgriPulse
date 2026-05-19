# AgriPulse marketing site

Static marketing site for **agripulse.cloud**. Astro + Tailwind.

> Slogan: *Plan the season. Grow the harvest. Predict the yield.*

## Pages

- `/` — Home
- `/product` — Feature deep-dive (insights, plan, signals, recommendations, integrations)
- `/pricing` — Grove / Estate / Enterprise tiers + FAQ
- `/about` — Mission, region focus, founders' note
- `/contact` — Form + direct emails + offices

## Local dev

```bash
cd marketing
pnpm install
pnpm dev        # http://localhost:4321
pnpm build      # → dist/
pnpm preview    # serve the built dist/
```

## Brand

Tokens live in `tailwind.config.mjs`:

- `leaf.700` `#0f6e56` — primary action / wordmark accent
- `leaf.500` `#1d9e75` — bright brand green (logo)
- `pulse` `#e24b4a` — accent / live indicators
- `sand.100` `#f7f6f1` — page bg
- `ink` `#1f2420` — body text
- `muted` `#6c7268` — secondary text

The favicon and inline logo SVG live in `public/favicon.svg` and `src/components/Logo.astro`.

## Deploy

`pnpm build` writes a fully static site to `dist/`. The whole site is ~130 KB
(no JS shipped to the browser beyond what each page needs for animations).

### Option A — GoDaddy hosting (user-selected)

> **DNS conflict to resolve first.** `agripulse.cloud` is registered at GoDaddy
> but its nameservers are currently delegated to AWS Route53. To serve the
> apex from GoDaddy's hosting, you need to either:
>
> 1. **Switch nameservers back to GoDaddy** — simplest, but breaks Route53
>    ACM cert validation for the app (`api.*`, `app.*`, `keycloak.*` etc.).
>    Keep this option only if the app moves to a fully separate domain.
> 2. **Keep nameservers at Route53 and add A/CNAME records** pointing the apex
>    to GoDaddy's hosting IPs. GoDaddy will give you those IPs (or a CNAME
>    target) under *Hosting → Settings → Server*. Add them as an A record on
>    `agripulse.cloud` and a CNAME on `www.agripulse.cloud` in Route53.
>    *Recommended* — preserves the app's existing ACM + Route53 wiring.

Upload steps (cPanel-style GoDaddy hosting):

1. Run `pnpm build`.
2. Open GoDaddy → *Hosting* → *cPanel admin* → *File Manager*.
3. Navigate to `public_html/` (or the docroot the plan calls *Web Root*).
4. Delete the default `index.html` / placeholder GoDaddy files.
5. Upload **the contents of `dist/`** (not the `dist` folder itself) into the
   web root. The result should be:
   ```
   public_html/
     index.html
     favicon.svg
     robots.txt
     about/index.html
     contact/index.html
     pricing/index.html
     product/index.html
     sitemap-index.xml
     sitemap-0.xml
     _astro/…
   ```
6. In GoDaddy, enable **Free SSL** (Let's Encrypt) on the hosting account.
7. Force HTTPS redirect via cPanel → *Domains* → *Force HTTPS Redirect*.
8. Verify each route in a private window.

### Option B — S3 + CloudFront (if you change your mind)

If you ever want to host on AWS instead, the build is already CloudFront-ready:

- Bucket: `agripulse-marketing-prod` (private, OAC-restricted)
- CloudFront with default root object `index.html`, error responses
  `403/404 → /index.html`
- ACM cert in `us-east-1` for `agripulse.cloud` + `www.agripulse.cloud`
- Route53 ALIAS `agripulse.cloud` → CloudFront distribution

A Terraform module for this can live in `infra/terraform/modules/marketing-site/`.

## Updating content

Edits are page-by-page. The shared chrome lives in:

- `src/layouts/Base.astro` — `<head>` and overall page frame
- `src/components/Header.astro` — top nav
- `src/components/Footer.astro` — footer
- `src/components/Logo.astro` — logo + wordmark (single SVG, monochrome optional)

After any change, run `pnpm build` and re-upload `dist/`.
