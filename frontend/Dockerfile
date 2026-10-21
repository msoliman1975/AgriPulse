# syntax=docker/dockerfile:1.10

# --- Builder ----------------------------------------------------------------
# pnpm via corepack (bundled with Node 20+). pnpm-lock.yaml is the cache key
# so the dependency layer is reused across non-dependency changes.
FROM node:22-alpine@sha256:968df39aedcea65eeb078fb336ed7191baf48f972b4479711397108be0966920 AS builder

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

# Build identity for telemetry's `app_version`. vite.config.ts reads this from
# the process env at config time.
#
# NOT named VITE_APP_VERSION: vite inlines every VITE_* var into
# `import.meta.env`, so that name puts a SECOND copy of the value in the bundle
# — untruncated, and therefore disagreeing with the 7-character `app_version`
# that events actually carry. Two values with one meaning is a trap; there is
# one here.
#
# This has to be passed in: the builder stage copies source, not `.git`, so
# the `git rev-parse` fallback in vite.config.ts cannot work here, and
# GITHUB_SHA is workflow env that a container build does not inherit. Without
# the arg every event from a released image recorded "dev", which is how it
# shipped the first time.
#
# The default keeps a bare `docker build` working; CI always passes the real
# short SHA, which is also the image tag.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

RUN pnpm build

# --- Runtime ----------------------------------------------------------------
# Static-served via nginx. The image is unprivileged (nginx-unprivileged
# variant) to satisfy K8s SecurityContext.runAsNonRoot=true policies.
FROM nginxinc/nginx-unprivileged:1.31-alpine@sha256:85bcbc6b2edd325462560c597d784ecee415024f1c6a004e53ac5f202b8ca561 AS runtime

# nginx-unprivileged listens on 8080 by default; ARCHITECTURE.md § 3.2 sits
# behind NGINX Ingress, so the in-pod port doesn't need to be 80.
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 8080
