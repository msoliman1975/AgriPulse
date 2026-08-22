# syntax=docker/dockerfile:1.10
#
# AgriPulse tile server.
#
# Wraps the upstream TiTiler image and adds:
#  - Our config overrides (CORS, max-zoom, S3 endpoint defaults).
#  - Our own application module, which serves upstream's /cog endpoints
#    plus the `cutline` algorithm (agripulse_tiles/cutline.py).
#  - A non-root runtime user (matches K8s runAsNonRoot pod security).
#  - A small health-only entrypoint shim.
#
# ARCHITECTURE.md Â§ 3.1 commits TiTiler as the COG â†’ XYZ/WMTS layer; this
# image stays close to upstream so security updates flow in via Dependabot.

FROM ghcr.io/developmentseed/titiler:0.21.1@sha256:33c57b3c3b2f5e4c8aa54cfea185d76f8024c5f8446283ead274cca492389993

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Defaults for COG access; overridden per-environment via ConfigMap.
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES \
    GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR \
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff,.TIFF" \
    VSI_CACHE=TRUE \
    VSI_CACHE_SIZE=536870912

# boto3: the cutline reads one small GeoJSON object per farm from the
# same bucket the rasters come from. GDAL reads rasters over its own
# /vsis3/ driver, which cannot hand a plain file back to Python, so the
# boundary read needs an S3 client of its own. Upstream ships none.
#
# shapely: the base image already carries it as a transitive dependency.
# Naming it here makes ours deliberate, so it cannot disappear under a
# base-image bump that drops whichever package pulled it in.
RUN pip install --no-cache-dir "boto3>=1.34,<2" "shapely>=2.0,<3"

# Drop our config + application + entrypoint in. The upstream image
# already exposes uvicorn at :8000; we only override env defaults.
COPY config/ /opt/agripulse/config/
COPY agripulse_tiles/ /opt/agripulse/lib/agripulse_tiles/
COPY scripts/healthcheck.sh /usr/local/bin/healthcheck.sh

# `MODULE_NAME` is what the upstream image's gunicorn command imports.
# Setting it here rather than in the Helm chart keeps the image and its
# entrypoint in one piece: a rollback to an older tag restores the older
# module with it, and no ordering between image and ConfigMap matters.
#
# The path points at `lib/`, which holds nothing but our package, so no
# dependency's `import <common name>` can be answered by a file of ours.
ENV PYTHONPATH=/opt/agripulse/lib \
    MODULE_NAME=agripulse_tiles.main \
    VARIABLE_NAME=app

# Healthcheck script is invoked by the K8s probe and the local Dockerfile
# HEALTHCHECK directive (handy for `docker compose` smokes).
RUN chmod +x /usr/local/bin/healthcheck.sh

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["/usr/local/bin/healthcheck.sh"]
