"""CLI entry point. Orchestrates the whole pipeline."""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import click

from imagery_backfill.aoi import (
    Block,
    derive_job_id,
    derive_subscription_id,
    load_blocks,
)
from imagery_backfill.indices import (
    STANDARD_INDEX_CODES,
    compute_aggregates,
    compute_all_indices,
)
from imagery_backfill.manifest import (
    ManifestRecord,
    aggregates_to_dict,
    asset_key,
    build_pgstac_item,
    read_existing_manifest_keys,
    stac_item_id,
    write_manifest_line,
    write_summary,
)
from imagery_backfill.rasterio_io import (
    load_bands_and_mask,
    write_index_cog,
    write_raw_bands_tif,
)
from imagery_backfill.sentinel_hub import (
    S2_L2A_BAND_ORDER,
    DiscoveredScene,
    SentinelHubClient,
    SentinelHubError,
)

_DEFAULT_DEV_CLIENT_ID = "67611d57-1a8d-4833-9a7b-02abde5b23b8"
_AWS_SECRET_NAME = "agripulse/dev/sentinel-hub-client-secret"
_AWS_PROFILE = "agripulse"
_BUCKET_PLACEHOLDER = "{BUCKET}"


@click.command()
@click.option("--aoi", "aoi_path", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--tenant-id", "tenant_id", type=click.UUID, required=True)
@click.option("--farm-id", "farm_id", type=click.UUID, required=True)
@click.option("--out", "out_dir", type=click.Path(file_okay=False, path_type=Path), required=True)
@click.option("--from", "from_date", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
@click.option("--to", "to_date", type=click.DateTime(formats=["%Y-%m-%d"]), required=True)
@click.option("--cloud-cover-max-pct", type=click.IntRange(0, 100), default=80, show_default=True)
@click.option("--utm-epsg", type=int, default=32636, show_default=True)
@click.option("--sh-client-id", "sh_client_id", envvar="SENTINEL_HUB_CLIENT_ID", default=None)
@click.option("--sh-client-secret", "sh_client_secret", envvar="SENTINEL_HUB_CLIENT_SECRET", default=None)
@click.option("--from-aws-secrets", "from_aws_secrets", is_flag=True)
def main(
    aoi_path: Path,
    tenant_id: UUID,
    farm_id: UUID,
    out_dir: Path,
    from_date: datetime,
    to_date: datetime,
    cloud_cover_max_pct: int,
    utm_epsg: int,
    sh_client_id: str | None,
    sh_client_secret: str | None,
    from_aws_secrets: bool,
) -> None:
    from_date = from_date.replace(tzinfo=UTC)
    to_date = to_date.replace(tzinfo=UTC)
    if to_date <= from_date:
        raise click.UsageError("--to must be strictly after --from")

    client_id, client_secret = _resolve_credentials(
        sh_client_id=sh_client_id,
        sh_client_secret=sh_client_secret,
        from_aws_secrets=from_aws_secrets,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.jsonl"
    summary_path = out_dir / "summary.json"
    already_done = read_existing_manifest_keys(manifest_path)
    if already_done:
        click.echo(f"resuming: {len(already_done)} (block, scene) pairs already in manifest")

    blocks = load_blocks(aoi_path, tenant_id=tenant_id, farm_id=farm_id, utm_epsg=utm_epsg)
    click.echo(f"loaded {len(blocks)} block(s) from {aoi_path}")

    collection_id = f"tenant_{tenant_id.hex}__s2_l2a"
    per_block_counts: dict[str, dict[str, int]] = {}
    started_at = time.time()
    total_scenes = 0
    total_skipped_existing = 0
    total_fetched = 0
    total_errors = 0

    with SentinelHubClient(client_id=client_id, client_secret=client_secret) as sh:
        for block in blocks:
            click.echo(f"\n=== block {block.name} ({block.block_id}) ===")
            try:
                scenes = sh.discover(
                    aoi_geojson_wgs84=block.boundary_wgs84,
                    from_datetime=from_date,
                    to_datetime=to_date,
                    max_cloud_cover_pct=cloud_cover_max_pct,
                )
            except SentinelHubError as exc:
                click.echo(f"  ! discover failed: {exc}", err=True)
                total_errors += 1
                continue
            click.echo(f"  discovered {len(scenes)} scene(s) under {cloud_cover_max_pct}% cloud")

            fetched = 0
            skipped_existing = 0
            errors = 0
            for scene in scenes:
                key = (str(block.block_id), scene.scene_id)
                if key in already_done:
                    skipped_existing += 1
                    continue
                try:
                    _process_scene(
                        sh=sh,
                        block=block,
                        scene=scene,
                        out_dir=out_dir,
                        manifest_path=manifest_path,
                        utm_epsg=utm_epsg,
                        collection_id=collection_id,
                        cloud_cover_max_pct=cloud_cover_max_pct,
                    )
                    fetched += 1
                    click.echo(
                        f"  + {scene.scene_datetime.date()} {scene.scene_id} "
                        f"(cloud={scene.cloud_cover_pct})"
                    )
                except (SentinelHubError, OSError, ValueError) as exc:
                    errors += 1
                    click.echo(f"  ! {scene.scene_id}: {exc}", err=True)

            per_block_counts[block.name] = {
                "discovered": len(scenes),
                "skipped_existing": skipped_existing,
                "fetched": fetched,
                "errors": errors,
            }
            total_scenes += len(scenes)
            total_fetched += fetched
            total_skipped_existing += skipped_existing
            total_errors += errors

    elapsed = time.time() - started_at
    write_summary(
        summary_path,
        {
            "run": {
                "started_at": datetime.now(UTC).isoformat(),
                "elapsed_seconds": round(elapsed, 2),
                "tenant_id": str(tenant_id),
                "farm_id": str(farm_id),
                "aoi_source": str(aoi_path),
                "window": {"from": from_date.isoformat(), "to": to_date.isoformat()},
                "cloud_cover_max_pct": cloud_cover_max_pct,
                "utm_epsg": utm_epsg,
                "provider": "sentinel_hub",
                "product": "s2_l2a",
                "stac_collection_id": collection_id,
            },
            "totals": {
                "blocks": len(blocks),
                "scenes_discovered": total_scenes,
                "scenes_fetched_this_run": total_fetched,
                "scenes_skipped_existing": total_skipped_existing,
                "errors": total_errors,
            },
            "per_block": per_block_counts,
        },
    )
    click.echo(
        f"\nfetched {total_fetched} new scene(s); "
        f"skipped {total_skipped_existing} existing; "
        f"{total_errors} error(s) in {elapsed:.1f}s"
    )
    click.echo(f"manifest: {manifest_path}")
    click.echo(f"summary:  {summary_path}")
    if total_errors:
        sys.exit(1)


def _process_scene(
    *,
    sh: SentinelHubClient,
    block: Block,
    scene: DiscoveredScene,
    out_dir: Path,
    manifest_path: Path,
    utm_epsg: int,
    collection_id: str,
    cloud_cover_max_pct: int,
) -> None:
    raw_key = asset_key(scene_id=scene.scene_id, aoi_hash=block.aoi_hash, band_or_index="raw_bands")
    raw_path = out_dir / raw_key

    fetch_result = sh.fetch_multiband(
        scene_id=scene.scene_id,
        scene_datetime=scene.scene_datetime,
        aoi_geojson_utm=block.boundary_utm,
        utm_epsg=utm_epsg,
    )
    write_raw_bands_tif(raw_path, fetch_result.cog_bytes)

    bands, aoi_mask, write_profile = load_bands_and_mask(
        raw_path,
        band_names=S2_L2A_BAND_ORDER,
        aoi_geojson_utm=block.boundary_utm,
    )
    index_arrays = compute_all_indices(bands)
    assets: dict[str, str] = {"raw_bands": raw_key}
    aggregates_payload: dict[str, dict[str, Any]] = {}
    for index_code in STANDARD_INDEX_CODES:
        agg = compute_aggregates(index_arrays[index_code], aoi_mask)
        key = asset_key(scene_id=scene.scene_id, aoi_hash=block.aoi_hash, band_or_index=index_code)
        write_index_cog(
            out_dir / key,
            index_array=index_arrays[index_code],
            aoi_mask=aoi_mask,
            profile=write_profile,
        )
        assets[index_code] = key
        aggregates_payload[index_code] = aggregates_to_dict(
            agg, cloud_cover_pct=scene.cloud_cover_pct
        )

    subscription_id = derive_subscription_id(block.block_id, "s2_l2a")
    job_id = derive_job_id(subscription_id, scene.scene_id)
    item_id = stac_item_id(scene_id=scene.scene_id, aoi_hash=block.aoi_hash)
    scene_dt_iso = _iso_utc_z(scene.scene_datetime)
    record = ManifestRecord(
        block={
            "block_id": block.block_id,
            "name": block.name,
            "boundary_wgs84": block.boundary_wgs84,
            "boundary_utm36n": block.boundary_utm,
            "aoi_hash": block.aoi_hash,
            "area_m2": block.area_m2,
        },
        subscription={
            "subscription_id": subscription_id,
            "product_code": "s2_l2a",
            "provider_code": "sentinel_hub",
            "cloud_cover_max_pct": cloud_cover_max_pct,
            "is_active": True,
        },
        ingestion_job={
            "job_id": job_id,
            "scene_id": scene.scene_id,
            "scene_datetime": scene.scene_datetime.astimezone(UTC).isoformat(),
            "status": "succeeded",
            "cloud_cover_pct": _decimal_or_none(scene.cloud_cover_pct),
            "stac_item_id": item_id,
            "assets_written": [raw_key],
        },
        pgstac_item=build_pgstac_item(
            collection_id=collection_id,
            scene_id=scene.scene_id,
            scene_datetime_iso=scene_dt_iso,
            aoi_hash=block.aoi_hash,
            block=block,
            cloud_cover_pct=scene.cloud_cover_pct,
            bucket_placeholder=_BUCKET_PLACEHOLDER,
            asset_paths=assets,
            band_names=S2_L2A_BAND_ORDER,
        ),
        assets=assets,
        aggregates=aggregates_payload,
    )
    write_manifest_line(manifest_path, record)


def _resolve_credentials(
    *,
    sh_client_id: str | None,
    sh_client_secret: str | None,
    from_aws_secrets: bool,
) -> tuple[str, str]:
    if from_aws_secrets:
        return _read_aws_secret(sh_client_id)
    if not sh_client_id or not sh_client_secret:
        raise click.UsageError(
            "Sentinel Hub credentials missing. Provide --sh-client-id + --sh-client-secret, "
            "or set SENTINEL_HUB_CLIENT_ID + SENTINEL_HUB_CLIENT_SECRET, "
            "or pass --from-aws-secrets."
        )
    return sh_client_id, sh_client_secret


def _read_aws_secret(client_id_override: str | None) -> tuple[str, str]:
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError as exc:
        raise click.UsageError(
            "--from-aws-secrets requires boto3. Reinstall with `pip install .[aws]`."
        ) from exc
    session = boto3.Session(
        profile_name=os.environ.get("AWS_PROFILE", _AWS_PROFILE),
        region_name="eu-south-1",
    )
    sm = session.client("secretsmanager")
    response = sm.get_secret_value(SecretId=_AWS_SECRET_NAME)
    secret = response.get("SecretString") or ""
    if not secret:
        raise click.UsageError(f"AWS secret {_AWS_SECRET_NAME!r} is empty")
    if secret.lstrip().startswith("{"):
        import json
        parsed = json.loads(secret)
        client_id = client_id_override or parsed.get("client_id") or _DEFAULT_DEV_CLIENT_ID
        client_secret = parsed.get("client_secret") or parsed.get("password")
        if not client_secret:
            raise click.UsageError(
                f"AWS secret {_AWS_SECRET_NAME!r} JSON is missing `client_secret`"
            )
        return client_id, client_secret
    return client_id_override or _DEFAULT_DEV_CLIENT_ID, secret


def _iso_utc_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal_or_none(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None
