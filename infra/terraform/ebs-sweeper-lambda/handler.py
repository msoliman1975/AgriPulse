"""CD-15: EBS sweeper.

Snapshots and deletes EBS volumes that are:
  * in `available` state (unattached)
  * older than AGE_DAYS days (default 7)
  * NOT tagged `keep=true`

Dry-run mode (DRY_RUN=true, default) only logs the would-be actions.
Read CloudWatch logs for a week before flipping DRY_RUN=false in
infra/terraform/ebs-sweeper.tf.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Iterable

import boto3

_REGION = os.environ.get("REGION", "me-south-1")
_DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"
_AGE_DAYS = int(os.environ.get("AGE_DAYS", "7"))


def _log(level: str, **fields) -> None:
    print(json.dumps({"level": level, **fields}))


def _eligible(volumes: Iterable[dict], cutoff: dt.datetime) -> list[dict]:
    """Filter to volumes the sweeper should act on.

    `cutoff` is timezone-aware UTC; CreateTime from boto3 is also tz-aware.
    """
    out = []
    for v in volumes:
        if v.get("State") != "available":
            continue
        if v.get("CreateTime") and v["CreateTime"] >= cutoff:
            continue
        tags = {t["Key"]: t["Value"] for t in v.get("Tags", [])}
        if tags.get("keep", "").lower() == "true":
            continue
        out.append(v)
    return out


def handler(_event, _ctx):
    ec2 = boto3.client("ec2", region_name=_REGION)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=_AGE_DAYS)

    paginator = ec2.get_paginator("describe_volumes")
    volumes: list[dict] = []
    for page in paginator.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
        volumes.extend(page.get("Volumes", []))

    targets = _eligible(volumes, cutoff)
    _log(
        "info",
        msg="sweep starting",
        dry_run=_DRY_RUN,
        age_days=_AGE_DAYS,
        scanned=len(volumes),
        targets=len(targets),
    )

    deleted = 0
    snapshots: list[str] = []
    for v in targets:
        vid = v["VolumeId"]
        age = (dt.datetime.now(dt.timezone.utc) - v["CreateTime"]).days
        _log("info", msg="target", volume=vid, age_days=age, size_gb=v.get("Size"))
        if _DRY_RUN:
            continue
        snap = ec2.create_snapshot(
            VolumeId=vid,
            Description=f"CD-15 pre-sweep snapshot of {vid}",
            TagSpecifications=[
                {
                    "ResourceType": "snapshot",
                    "Tags": [
                        {"Key": "purpose", "Value": "pre-sweep"},
                        {"Key": "source-volume", "Value": vid},
                    ],
                },
            ],
        )
        snapshots.append(snap["SnapshotId"])
        _log("info", msg="snapshotted", volume=vid, snapshot=snap["SnapshotId"])
        ec2.delete_volume(VolumeId=vid)
        deleted += 1
        _log("info", msg="deleted", volume=vid)

    _log("info", msg="sweep done", deleted=deleted, snapshots=snapshots)
    return {"scanned": len(volumes), "targets": len(targets), "deleted": deleted, "snapshots": snapshots}
