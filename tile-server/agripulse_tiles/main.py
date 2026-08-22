"""The AgriPulse tile server application.

Upstream TiTiler's `/cog` endpoints, plus one post-processing algorithm of
our own: `cutline`, which cuts an index raster to a farm boundary at
render time. See `cutline.py` for why that has to happen here rather than
in the stored file.

Why this module exists at all: TiTiler's algorithm registry is frozen, and
`register()` returns a NEW registry rather than adding to the shared one.
A factory is bound to whichever registry it was built with, so an extra
algorithm can only reach the endpoints by building the factory here.

What is deliberately left out of upstream's application: the `/stac` and
`/mosaicjson` factories. Nothing in AgriPulse calls them. Everything the
frontend does call - `/cog/tiles/...` and `/cog/statistics` - is served by
the same `TilerFactory` upstream uses, with the same dependencies.
"""

from __future__ import annotations

import logging

import rasterio
from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security.api_key import APIKeyQuery
from rio_tiler.io import Reader
from starlette.middleware.cors import CORSMiddleware
from starlette_cramjam.middleware import CompressionMiddleware
from titiler.application import __version__ as titiler_version
from titiler.application.settings import ApiSettings
from titiler.core.algorithm import algorithms as default_algorithms
from titiler.core.errors import DEFAULT_STATUS_CODES, add_exception_handlers
from titiler.core.factory import (
    AlgorithmFactory,
    ColorMapFactory,
    TilerFactory,
    TMSFactory,
)
from titiler.core.middleware import (
    CacheControlMiddleware,
    LoggerMiddleware,
    LowerCaseQueryStringMiddleware,
    TotalTimeMiddleware,
)
from titiler.extensions import cogValidateExtension, cogViewerExtension

from agripulse_tiles import __version__
from agripulse_tiles.cutline import Cutline

logging.getLogger("botocore.credentials").setLevel(logging.WARNING)

api_settings = ApiSettings()

algorithms = default_algorithms.register({"cutline": Cutline})

app_dependencies = []
if api_settings.global_access_token:

    def validate_access_token(access_token: str = Security(APIKeyQuery(name="access_token"))):
        """Reject a request that does not carry the shared token."""
        if access_token != api_settings.global_access_token:
            raise HTTPException(status_code=401, detail="Invalid access token")

    app_dependencies.append(Depends(validate_access_token))


app = FastAPI(
    title=api_settings.name,
    openapi_url="/api",
    docs_url="/api.html",
    description="AgriPulse tile server: TiTiler COG endpoints plus a farm-boundary cutline.",
    version=titiler_version,
    root_path=api_settings.root_path,
    dependencies=app_dependencies,
)

cog = TilerFactory(
    reader=Reader,
    router_prefix="/cog",
    process_dependency=algorithms.dependency,
    extensions=[cogValidateExtension(), cogViewerExtension()],
)
app.include_router(cog.router, prefix="/cog", tags=["Cloud Optimized GeoTIFF"])

app.include_router(TMSFactory().router, tags=["Tiling Schemes"])
app.include_router(
    AlgorithmFactory(supported_algorithm=algorithms).router,
    tags=["Algorithms"],
)
app.include_router(ColorMapFactory().router, tags=["ColorMaps"])

add_exception_handlers(app, DEFAULT_STATUS_CODES)

if api_settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=api_settings.cors_origins,
        allow_credentials=True,
        allow_methods=api_settings.cors_allow_methods,
        allow_headers=["*"],
    )

app.add_middleware(
    CompressionMiddleware,
    minimum_size=0,
    exclude_mediatype={
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/jp2",
        "image/webp",
    },
    compression_level=6,
)

app.add_middleware(
    CacheControlMiddleware,
    cachecontrol=api_settings.cachecontrol,
    exclude_path={r"/healthz"},
)

if api_settings.debug:
    app.add_middleware(LoggerMiddleware, headers=True, querystrings=True)
    app.add_middleware(TotalTimeMiddleware)

if api_settings.lower_case_query_parameters:
    app.add_middleware(LowerCaseQueryStringMiddleware)


@app.get(
    "/healthz",
    description="Health Check.",
    summary="Health Check.",
    operation_id="healthCheck",
    tags=["Health Check"],
)
def application_health_check():
    """Health check.

    `algorithms` lists what the post-processing registry holds. A missing
    `cutline` there means every tile is being served uncut, which is
    otherwise only visible as colour outside a farm border.
    """
    return {
        "versions": {
            "agripulse": __version__,
            "titiler": titiler_version,
            "rasterio": rasterio.__version__,
            "gdal": rasterio.__gdal_version__,
            "proj": rasterio.__proj_version__,
            "geos": rasterio.__geos_version__,
        },
        "algorithms": sorted(algorithms.data),
    }
