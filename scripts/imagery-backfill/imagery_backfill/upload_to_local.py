"""Import a backfill bundle into a local AgriPulse env (dev compose).

Reads `<bundle>/sentinel_hub/...` raw COGs, re-clips each against every
target block's boundary, computes per-block aggregates, uploads TIFFs to
MinIO at the block's real `aoi_hash`, and inserts AgriPulse rows that
mimic the daily Celery integration:

  * `imagery_aoi_subscriptions` — one row per (block, s2_l2a), active.
  * `imagery_ingestion_jobs`    — one row per (subscription, scene),
                                   status='succeeded'.
  * `pgstac.items`              — one item per scene (upsert via
                                   `pgstac.create_items`).
  * `block_index_aggregates`    — six rows per (block, scene).
  * `audit_events`              — three rows per (block, scene):
                                   scene_discovered, scene_ingested,
                                   indices_computed.

The `subscription.last_successful_ingest_at` lands at the most recent
scene_datetime so the daily sweep only picks scenes after the bundle's
window.

INPUTS: --bundle, --tenant-id, --farm-id. The script discovers blocks
under the farm itself; it does NOT need an AOI file. Block boundaries
are read from `blocks.boundary_utm` (the DB-canonical form) so re-clip
math is consistent with the production pipeline.

Hard-coded for the dev compose stack (PG on :5432, MinIO on :9000 with
credentials from infra/dev/compose.yaml).
"""

from __future__ import annotations

import io
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import boto3
import click
import psycopg
from psycopg.types.json import Json
from psycopg.rows import dict_row

from imagery_backfill.indices import (
    STANDARD_INDEX_CODES,
    compute_aggregates,
    compute_all_indices,
)
from imagery_backfill.rasterio_io import load_bands_and_mask, write_index_cog_bytes
from imagery_backfill.sentinel_hub import S2_L2A_BAND_ORDER

# Dev-env defaults baked from infra/dev/compose.yaml.
# Live-cluster invocation:
#   --pg-dsn  postgres://agripulse:$(pg-pw)@localhost:5432/agripulse   # via port-forward
#   --s3-endpoint ""                                                    # real AWS S3
#   --s3-bucket agripulse-imagery-dev
#   --aws-region eu-south-1
#   (omit --s3-key / --s3-secret to fall back to the boto3 default
#    credential chain — picks up AWS_PROFILE=agripulse).
_DEFAULT_PG_DSN = "postgresql://agripulse:agripulse@localhost:5432/agripulse"
_DEFAULT_S3_ENDPOINT = "http://localhost:9000"
_DEFAULT_S3_KEY = "agripulse"
_DEFAULT_S3_SECRET = "agripulse-dev"
_DEFAULT_S3_BUCKET = "agripulse-uploads"
_DEFAULT_AWS_REGION = "us-east-1"

_RAW_CT = "image/tiff; application=geotiff; profile=cloud-optimized"


# ---- helpers --------------------------------------------------------


def _safe_schema(schema: str) -> str:
    if not schema.replace("_", "").isalnum():
        raise click.UsageError(f"unsafe schema name: {schema!r}")
    return schema


def _asset_key(scene_id: str, aoi_hash: str, band_or_index: str) -> str:
    return f"sentinel_hub/s2_l2a/{scene_id}/{aoi_hash}/{band_or_index}.tif"


def _stac_item_id(scene_id: str, aoi_hash: str) -> str:
    return f"sentinel_hub/s2_l2a/{scene_id}/{aoi_hash}"


def _bbox_polygon(geojson_polygon: dict[str, Any]) -> list[float]:
    coords = geojson_polygon["coordinates"][0]
    xs = [pt[0] for pt in coords]
    ys = [pt[1] for pt in coords]
    return [min(xs), min(ys), max(xs), max(ys)]


def _iso_utc_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


# ---- core -----------------------------------------------------------


@click.command()
@click.option("--bundle", "bundle_dir", type=click.Path(exists=True, file_okay=False, path_type=Path), required=True,
              help="Path to the bundle produced by `imagery-backfill`.")
@click.option("--tenant-id", "tenant_id", type=click.UUID, required=True,
              help="Target tenant UUID. The tenant's schema_name is read from public.tenants.")
@click.option("--farm-id", "farm_id", type=click.UUID, required=True,
              help="Target farm UUID. All active blocks under this farm will receive history.")
@click.option("--pg-dsn", default=_DEFAULT_PG_DSN, show_default=True)
@click.option("--s3-mode", type=click.Choice(["minio", "aws"]), default="minio",
              show_default=True,
              help='"minio" → use --s3-endpoint + --s3-key/--s3-secret (local). '
                   '"aws"  → real AWS S3 with boto3 default credential chain.')
@click.option("--s3-endpoint", default=_DEFAULT_S3_ENDPOINT, show_default=True,
              help="Ignored in --s3-mode aws.")
@click.option("--s3-key", default=_DEFAULT_S3_KEY, show_default=True,
              help="Ignored in --s3-mode aws.")
@click.option("--s3-secret", default=_DEFAULT_S3_SECRET, show_default=True)
@click.option("--s3-bucket", default=_DEFAULT_S3_BUCKET, show_default=True)
@click.option("--aws-region", default=_DEFAULT_AWS_REGION, show_default=True,
              help="AWS region for --s3-mode aws. Use eu-south-1 for live.")
@click.option("--dry-run", is_flag=True,
              help="Discover scenes + blocks + plan, but write nothing.")
def main(
    bundle_dir: Path,
    tenant_id: UUID,
    farm_id: UUID,
    pg_dsn: str,
    s3_mode: str,
    s3_endpoint: str,
    s3_key: str,
    s3_secret: str,
    s3_bucket: str,
    aws_region: str,
    dry_run: bool,
) -> None:
    manifest_path = bundle_dir / "manifest.jsonl"
    if not manifest_path.exists():
        raise click.UsageError(f"no manifest.jsonl in {bundle_dir}")

    started = time.time()

    # ---- Load manifest: scene_id -> (scene_datetime, cloud_cover_pct, raw_path)
    scenes: dict[str, dict[str, Any]] = {}
    with manifest_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            scene_id = rec["ingestion_job"]["scene_id"]
            if scene_id in scenes:
                continue
            raw_rel = rec["assets"]["raw_bands"]
            raw_path = bundle_dir / raw_rel
            if not raw_path.exists():
                click.echo(f"  ! missing raw {raw_path}", err=True)
                continue
            cc = rec["ingestion_job"].get("cloud_cover_pct")
            scenes[scene_id] = {
                "scene_datetime": datetime.fromisoformat(rec["ingestion_job"]["scene_datetime"]),
                "cloud_cover_pct": Decimal(cc) if cc is not None else None,
                "raw_path": raw_path,
            }
    click.echo(f"bundle: {len(scenes)} unique scene(s)")

    # ---- DB: resolve tenant schema + farm + blocks + product/provider ----
    with psycopg.connect(pg_dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT schema_name FROM public.tenants "
                "WHERE id = %s AND deleted_at IS NULL",
                (tenant_id,),
            )
            row = cur.fetchone()
            if not row:
                raise click.UsageError(f"tenant {tenant_id} not found")
            schema = _safe_schema(row["schema_name"])
            click.echo(f"tenant schema: {schema}")

            cur.execute(
                "SELECT id, code FROM public.imagery_products WHERE code='s2_l2a'"
            )
            product_row = cur.fetchone()
            cur.execute(
                "SELECT id FROM public.imagery_providers WHERE code='sentinel_hub'"
            )
            provider_row = cur.fetchone()
            product_id: UUID = product_row["id"]
            click.echo(f"product s2_l2a: {product_id}")

            cur.execute(f"SET LOCAL search_path TO {schema}, public")
            cur.execute(
                "SELECT id, code, name, aoi_hash, "
                "ST_AsGeoJSON(boundary)::jsonb AS boundary_wgs84, "
                "ST_AsGeoJSON(boundary_utm)::jsonb AS boundary_utm "
                "FROM blocks WHERE farm_id = %s AND deleted_at IS NULL "
                "ORDER BY code",
                (farm_id,),
            )
            blocks = cur.fetchall()
            if not blocks:
                raise click.UsageError(f"no active blocks under farm {farm_id}")

        collection_id = f"{schema}__s2_l2a"

    click.echo(f"farm blocks: {len(blocks)}  ({', '.join(b['code'] for b in blocks)})")
    click.echo(f"pgstac collection: {collection_id}")

    plan_total_jobs = len(blocks) * len(scenes)
    click.echo(f"plan: {len(blocks)} subs, {plan_total_jobs} jobs, "
               f"{plan_total_jobs * 6} aggregates, "
               f"{plan_total_jobs * 3} audit events, "
               f"{plan_total_jobs * 7} S3 objects")
    if dry_run:
        click.echo("--dry-run set; exiting before any writes.")
        return

    # ---- S3 client (MinIO local OR real AWS S3) ----
    # `--s3-mode aws` uses the boto3 default credential chain (env vars,
    # AWS_PROFILE, IRSA, instance role) so a laptop with
    # `AWS_PROFILE=agripulse` just works without echoing keys on the
    # command line. `minio` keeps the local-compose path unchanged.
    s3_kwargs: dict[str, Any] = {"region_name": aws_region}
    if s3_mode == "minio":
        s3_kwargs["endpoint_url"] = s3_endpoint
        s3_kwargs["aws_access_key_id"] = s3_key
        s3_kwargs["aws_secret_access_key"] = s3_secret
    s3 = boto3.client("s3", **s3_kwargs)
    try:
        s3.head_bucket(Bucket=s3_bucket)
    except Exception as exc:
        raise click.UsageError(f"S3 bucket {s3_bucket!r} not reachable: {exc}") from exc

    # ---- per-scene RAW cache: read once, reuse across all 6 blocks ----
    # The raw_bands.tif from the bundle came from the user's original AOI
    # which is a superset of every sub-block. We read each band into RAM
    # once per scene, then re-mask per block.
    raw_bands_bytes_cache: dict[str, bytes] = {}

    sub_ids_by_block: dict[UUID, UUID] = {}
    most_recent_scene_dt = max(s["scene_datetime"] for s in scenes.values())
    requested_at_anchor = datetime.now(UTC)

    with psycopg.connect(pg_dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

            # 1. Create / fetch subscriptions per block.
            for block in blocks:
                cur.execute(
                    "SELECT id FROM imagery_aoi_subscriptions "
                    "WHERE block_id=%s AND product_id=%s AND is_active=true",
                    (block["id"], product_id),
                )
                row = cur.fetchone()
                if row:
                    sub_id = row[0]
                else:
                    sub_id = uuid.uuid4()
                    cur.execute(
                        "INSERT INTO imagery_aoi_subscriptions "
                        "(id, block_id, product_id, cadence_hours, cloud_cover_max_pct, "
                        " is_active, last_successful_ingest_at, last_attempted_at) "
                        "VALUES (%s, %s, %s, %s, %s, true, %s, %s)",
                        (
                            sub_id,
                            block["id"],
                            product_id,
                            24,
                            80,
                            most_recent_scene_dt,
                            most_recent_scene_dt,
                        ),
                    )
                sub_ids_by_block[block["id"]] = sub_id
        conn.commit()
    click.echo(f"subscriptions ready: {len(sub_ids_by_block)}")

    # 2. Per scene: read raw once, then re-clip + write per block.
    total_jobs = 0
    total_uploads = 0
    progress_every = max(1, len(scenes) // 20)

    for scene_idx, (scene_id, scene_info) in enumerate(sorted(scenes.items(), key=lambda kv: kv[1]["scene_datetime"])):
        scene_dt: datetime = scene_info["scene_datetime"]
        cloud_pct: Decimal | None = scene_info["cloud_cover_pct"]
        raw_path: Path = scene_info["raw_path"]
        raw_bytes = raw_path.read_bytes()

        with psycopg.connect(pg_dsn, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SET search_path TO {schema}, public")

                # Resume guard: if all 6 blocks already have a succeeded job
                # for this scene, skip the entire scene to avoid duplicate
                # audit rows (audit_events has no natural dedupe).
                cur.execute(
                    "SELECT count(*) FROM imagery_ingestion_jobs "
                    "WHERE scene_id=%s AND status='succeeded' AND block_id = ANY(%s)",
                    (scene_id, [b["id"] for b in blocks]),
                )
                already_count = cur.fetchone()[0]
                if already_count >= len(blocks):
                    if (scene_idx + 1) % progress_every == 0 or scene_idx + 1 == len(scenes):
                        click.echo(f"  [{scene_idx + 1}/{len(scenes)}] (already imported)")
                    continue

                for block in blocks:
                    block_id: UUID = block["id"]
                    block_aoi_hash: str = block["aoi_hash"]
                    block_boundary_utm = block["boundary_utm"]
                    block_boundary_wgs84 = block["boundary_wgs84"]
                    block_farm_id = farm_id
                    sub_id = sub_ids_by_block[block_id]
                    job_id = uuid.uuid4()
                    item_id = _stac_item_id(scene_id, block_aoi_hash)

                    # --- Upload raw bytes (same per scene; key differs by block aoi_hash)
                    raw_key = _asset_key(scene_id, block_aoi_hash, "raw_bands")
                    s3.put_object(
                        Bucket=s3_bucket,
                        Key=raw_key,
                        Body=raw_bytes,
                        ContentType=_RAW_CT,
                    )
                    total_uploads += 1

                    # --- Re-clip against block boundary (read from in-RAM bytes)
                    # rasterio doesn't open from bytes directly without MemoryFile,
                    # but load_bands_and_mask uses the filesystem path. The bundle
                    # raw file already exists on disk, so reuse the same path —
                    # the mask geometry is what changes per block.
                    bands, aoi_mask, write_profile = load_bands_and_mask(
                        raw_path,
                        band_names=S2_L2A_BAND_ORDER,
                        aoi_geojson_utm=block_boundary_utm,
                    )
                    index_arrays = compute_all_indices(bands)

                    assets: dict[str, str] = {"raw_bands": raw_key}
                    aggregate_rows: list[tuple[Any, ...]] = []
                    for index_code in STANDARD_INDEX_CODES:
                        agg = compute_aggregates(index_arrays[index_code], aoi_mask)
                        idx_key = _asset_key(scene_id, block_aoi_hash, index_code)
                        idx_bytes = write_index_cog_bytes(
                            index_array=index_arrays[index_code],
                            aoi_mask=aoi_mask,
                            profile=write_profile,
                        )
                        s3.put_object(
                            Bucket=s3_bucket,
                            Key=idx_key,
                            Body=idx_bytes,
                            ContentType=_RAW_CT,
                        )
                        total_uploads += 1
                        assets[index_code] = idx_key
                        aggregate_rows.append((
                            scene_dt,
                            block_id,
                            index_code,
                            product_id,
                            agg.mean, agg.min, agg.max,
                            agg.p10, agg.p50, agg.p90, agg.std_dev,
                            agg.valid_pixel_count, agg.total_pixel_count,
                            cloud_pct,
                            item_id,
                        ))

                    # --- INSERT ingestion job (status=succeeded)
                    # Plausible timing: requested at "discovery", started ~5 min later,
                    # completed ~3 min after start. The discovery itself is anchored
                    # to the day after the scene (matches the next-day sweep cadence).
                    requested_at = (scene_dt + timedelta(days=1)).replace(
                        hour=2, minute=0, second=scene_idx % 60, microsecond=0
                    )
                    started_at_job = requested_at + timedelta(minutes=5, seconds=12)
                    completed_at = started_at_job + timedelta(minutes=3, seconds=27)
                    cur.execute(
                        "INSERT INTO imagery_ingestion_jobs "
                        "(id, subscription_id, block_id, product_id, scene_id, "
                        " scene_datetime, requested_at, started_at, completed_at, "
                        " status, cloud_cover_pct, valid_pixel_pct, error_message, "
                        " error_code, stac_item_id, assets_written) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
                        "        'succeeded', %s, %s, NULL, NULL, %s, %s) "
                        "ON CONFLICT (subscription_id, scene_id) DO NOTHING",
                        (
                            job_id, sub_id, block_id, product_id, scene_id,
                            scene_dt, requested_at, started_at_job, completed_at,
                            cloud_pct,
                            # Approx valid_pixel_pct from NDVI aggregates (any
                            # index has the same valid/total ratio for a given
                            # block since the mask is identical).
                            None,
                            item_id,
                            Json(list(assets.values())),
                        ),
                    )

                    # --- block_index_aggregates: 6 rows
                    cur.executemany(
                        "INSERT INTO block_index_aggregates "
                        "(time, block_id, index_code, product_id, "
                        " mean, min, max, p10, p50, p90, std_dev, "
                        " valid_pixel_count, total_pixel_count, cloud_cover_pct, "
                        " stac_item_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (time, block_id, index_code, product_id) DO NOTHING",
                        aggregate_rows,
                    )

                    # --- pgstac item
                    stac_doc = {
                        "type": "Feature",
                        "stac_version": "1.0.0",
                        "id": item_id,
                        "collection": collection_id,
                        "geometry": block_boundary_wgs84,
                        "bbox": _bbox_polygon(block_boundary_wgs84),
                        "properties": {
                            "datetime": _iso_utc_z(scene_dt),
                            "eo:cloud_cover": float(cloud_pct) if cloud_pct is not None else None,
                            "agripulse:scene_id": scene_id,
                            "agripulse:aoi_hash": block_aoi_hash,
                        },
                        "assets": {
                            "raw_bands": {
                                "href": f"s3://{s3_bucket}/{raw_key}",
                                "type": _RAW_CT,
                                "roles": ["data"],
                                "bands": list(S2_L2A_BAND_ORDER),
                            },
                            **{
                                index_code: {
                                    "href": f"s3://{s3_bucket}/{assets[index_code]}",
                                    "type": _RAW_CT,
                                    "roles": ["data", "index"],
                                    "title": index_code.upper(),
                                }
                                for index_code in STANDARD_INDEX_CODES
                            },
                        },
                        "links": [],
                    }
                    # pgstac.upsert_item takes a single item JSON string.
                    cur.execute(
                        "SELECT pgstac.upsert_item(%s::jsonb)",
                        (json.dumps(stac_doc),),
                    )

                    # --- audit_events: 3 rows per (block, scene)
                    audit_rows = [
                        (
                            requested_at,
                            uuid.uuid4(),
                            "imagery.scene_discovered",
                            None, "system",
                            None, "ingestion_job", job_id,
                            block_farm_id,
                            Json({"scene_id": scene_id, "cloud_cover_pct": str(cloud_pct) if cloud_pct is not None else None}),
                        ),
                        (
                            completed_at,
                            uuid.uuid4(),
                            "imagery.scene_ingested",
                            None, "system",
                            None, "ingestion_job", job_id,
                            block_farm_id,
                            Json({"stac_item_id": item_id}),
                        ),
                        (
                            completed_at + timedelta(seconds=30),
                            uuid.uuid4(),
                            "imagery.indices_computed",
                            None, "system",
                            None, "ingestion_job", job_id,
                            block_farm_id,
                            Json({"stac_item_id": item_id, "indices": list(STANDARD_INDEX_CODES)}),
                        ),
                    ]
                    cur.executemany(
                        "INSERT INTO audit_events "
                        "(time, id, event_type, actor_user_id, actor_kind, "
                        " correlation_id, subject_kind, subject_id, farm_id, details) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        audit_rows,
                    )

                    total_jobs += 1

            conn.commit()

        if (scene_idx + 1) % progress_every == 0 or scene_idx + 1 == len(scenes):
            elapsed = time.time() - started
            click.echo(
                f"  [{scene_idx + 1}/{len(scenes)}] scenes done "
                f"({total_jobs} jobs, {total_uploads} uploads, {elapsed:.0f}s)"
            )

    elapsed = time.time() - started
    click.echo(
        f"\nimport complete: {total_jobs} jobs, "
        f"{total_jobs * 6} aggregates, "
        f"{total_jobs * 3} audit events, "
        f"{total_uploads} S3 objects in {elapsed:.0f}s"
    )


if __name__ == "__main__":
    main()
