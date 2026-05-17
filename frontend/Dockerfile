# syntax=docker/dockerfile:1.10

# --- Builder ----------------------------------------------------------------
# pnpm via corepack (bundled with Node 20+). pnpm-lock.yaml is the cache key
# so the dependency layer is reused across non-dependency changes.
FROM node:26-alpine@sha256:e71ac5e964b9201072425d59d2e876359efa25dc96bb1768cb73295728d6e4ea AS builder

ENV CI=1 PNPM_HOME=/pnpm PATH=/pnpm:$PATH

WORKDIR /build

RUN corepack enable

# Copy dependency manifests first; the install layer caches on these.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# App source.
COPY tsconfig.json tsconfig.app.json tsconfig.node.json global.d.ts ./
COPY vite.config.ts vitest.config.ts tailwind.config.ts postcss.config.js ./
COPY index.html ./
# Vite inlines VITE_* env at build time. .env.production carries the
# dev-cluster hostnames; override per-env with `docker build --build-arg`
# once the staging/prod pipeline lands.
COPY .env.production ./
COPY src ./src
COPY public ./public
# Root tsconfig.json references ./e2e as a TS project; tsc -b fails without
# it. e2e only lives in the discarded builder stage, so no runtime cost.
COPY e2e ./e2e

RUN pnpm build

# --- Runtime ----------------------------------------------------------------
# Static-served via nginx. The image is unprivileged (nginx-unprivileged
# variant) to satisfy K8s SecurityContext.runAsNonRoot=true policies.
FROM nginxinc/nginx-unprivileged:1.29-alpine@sha256:0c79d56aee561a1d81c63f00eee5fb5fe29279560cdc55e91425133104c7fbe6 AS runtime

# nginx-unprivileged listens on 8080 by default; ARCHITECTURE.md § 3.2 sits
# behind NGINX Ingress, so the in-pod port doesn't need to be 80.
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 8080
