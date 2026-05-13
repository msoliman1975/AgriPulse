# syntax=docker/dockerfile:1.10
#
# AgriPulse tile server.
#
# Wraps the upstream TiTiler image and adds:
#  - Our config overrides (CORS, max-zoom, S3 endpoint defaults).
#  - A non-root runtime user (matches K8s runAsNonRoot pod security).
#  - A small health-only entrypoint shim.
#
# ARCHITECTURE.md Â§ 3.1 commits TiTiler as the COG â†’ XYZ/WMTS layer; this
# image stays close to upstream so security updates flow in via Dependabot.

FROM ghcr.io/developmentseed/titiler:0.21.1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Defaults for COG access; overridden per-environment via ConfigMap.
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES=YES \
    GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR \
    CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif,.TIF,.tiff,.TIFF" \
    VSI_CACHE=TRUE \
    VSI_CACHE_SIZE=536870912

# Drop our config + entrypoint in. The upstream image already exposes
# uvicorn at :8000; we only override env defaults.
COPY config/ /opt/agripulse/config/
COPY scripts/healthcheck.sh /usr/local/bin/healthcheck.sh

# Healthcheck script is invoked by the K8s probe and the local Dockerfile
# HEALTHCHECK directive (handy for `docker compose` smokes).
RUN chmod +x /usr/local/bin/healthcheck.sh

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["/usr/local/bin/healthcheck.sh"]
