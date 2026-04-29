"""TiTiler runtime settings overrides for MissionAgre.

Picked up by TiTiler's settings layer when this package directory is on
PYTHONPATH (the Helm chart mounts a ConfigMap to ``/opt/missionagre/config/``
and prepends it). Anything not set here falls back to TiTiler defaults.

ARCHITECTURE.md § 9 commits:
- COGs in object storage (UTM 36N, EPSG:32636)
- Web tiles in Web Mercator (EPSG:3857), reprojected on the fly
- Cloud-cover thresholds applied upstream — this layer just serves bytes
"""

from __future__ import annotations

import os

# CORS — the API and frontend live behind the same ingress, so explicit
# allowlists rather than `*`.
CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
CORS_ALLOW_METHODS = ["GET", "OPTIONS"]
CORS_ALLOW_CREDENTIALS = False

# Tile cache — soft defaults; tuned per env via the Helm chart's ConfigMap.
DEFAULT_MAX_ZOOM = int(os.getenv("DEFAULT_MAX_ZOOM", "22"))
DEFAULT_MIN_ZOOM = int(os.getenv("DEFAULT_MIN_ZOOM", "0"))

# Object storage — the S3-compatible endpoint comes from infra/dev locally
# (MinIO) and from the production S3 bucket in EKS. boto3 reads
# AWS_S3_ENDPOINT_URL from the environment.
AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL")  # None → AWS default
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "me-south-1")
