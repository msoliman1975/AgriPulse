"""Set the crop attributes the T_ mango catalogue branches on, across one farm.

Written for Mango Republic (farm `0001` in the Valley Farms tenant), which is
the sandbox the catalogue was exercised against. It writes ONLY crop-attribute
values -- the three hand-entered fields every size-aware mango rule reads --
and never touches imagery, index rows or recommendations. Every leaf the rules
reach is still driven by the farm's real Sentinel-2 and Landsat readings.

Why it exists: eleven of the twenty-two trees branch on `tree_size_class`
before they look at a number, and several branch on `bearing_status` and the
growth stage on top of that. Mango Republic carried only two of the three size
classes and two of the four harvest groups, so a third of the catalogue's
branches could not be reached by any block on the farm and a broken branch
would have looked exactly like a quiet one.

What it sets:

  harvest_season_group  from the block's own variety, using the workbook's
                        four groups. Truthful, not spread for coverage: the
                        farm has no Keitt, so the `late` option stays unused
                        and the script says so rather than inventing one.

  tree_size_class       left alone by default. `--cover-sizes` moves a named
                        handful of blocks to `large` and clears one entirely,
                        so the large branch and the size-unknown branch both
                        get walked. That is demo data, not a measurement, and
                        the script prints the previous value of every row it
                        changes so the farm can be put back.

  bearing_status        same treatment under the same flag.

Run it from the cluster node, where the API and Keycloak resolve:

  python3 seed_mango_catalogue_demo.py --dry-run
  python3 seed_mango_catalogue_demo.py --cover-sizes

Credentials come from the environment: AGRIPULSE_USER, AGRIPULSE_PASSWORD.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

KC_BASE = os.environ.get("KC_BASE", "https://keycloak.agripulse.cloud")
API_BASE = os.environ.get("API_BASE", "https://api.agripulse.cloud/api/v1")
REALM = os.environ.get("KC_REALM", "agripulse")
CLIENT = os.environ.get("KC_CLIENT", "agripulse-api")

FARM_NAME = os.environ.get("FARM_NAME", "Mango Republic")

# The workbook groups the nine documented varieties into four harvest windows.
# Mango Republic's crop paths carry local spellings, so the mapping is by the
# path segment actually recorded on the block. Anything not listed here falls
# to `unconfirmed`, which is the workbook's own name for the group whose
# timing it could not source -- an honest default rather than a guess.
VARIETY_GROUP: dict[str, str] = {
    "sukkary": "early",
    "alphonso": "early",
    "kent": "mid",
    "eston": "mid",  # Osteen, as recorded on this farm
    "osteen": "mid",
    "ewais": "mid",
    "keitt": "late",
    "crimson": "unconfirmed",
    "yasmina": "unconfirmed",
    "yasmeena": "unconfirmed",
    "zebdia": "unconfirmed",
}

# Blocks moved off their recorded values under --cover-sizes, chosen to reach
# the branches nothing else on the farm reaches. `None` clears the attribute,
# which is what the size-unknown leaf is for.
COVERAGE: dict[str, dict[str, str | None]] = {
    "009": {"tree_size_class": "large", "bearing_status": "bearing"},
    "010": {"tree_size_class": "large", "bearing_status": "not_bearing"},
    "011": {"tree_size_class": "large", "bearing_status": "bearing"},
    "012": {"tree_size_class": "small", "bearing_status": "bearing"},
    "013": {"tree_size_class": None, "bearing_status": None},
}


def _post_form(url: str, form: dict[str, str]) -> dict:
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        return json.load(resp)


class _ApiError(Exception):
    """Carries the problem-detail body. A 422 from this API names the field
    and the reason in `detail`; discarding it turns a precise complaint into
    "Unprocessable Entity"."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def _items(payload: dict | list) -> list:
    """Collection endpoints are not consistent: some return a bare JSON list,
    others wrap it in `{"items": [...]}`. Accept either rather than guessing."""
    if isinstance(payload, list):
        return payload
    return payload.get("items", [])


def _api(token: str, path: str, *, method: str = "GET", body: dict | None = None) -> dict:
    payload = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{API_BASE}{path}", data=payload, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            return json.load(resp)
    except urllib.error.HTTPError as exc:  # a 422 body names the field
        raise _ApiError(exc.code, exc.read().decode("utf-8", "replace")) from exc


def token() -> str:
    user = os.environ.get("AGRIPULSE_USER")
    password = os.environ.get("AGRIPULSE_PASSWORD")
    if not user or not password:
        sys.exit("Set AGRIPULSE_USER and AGRIPULSE_PASSWORD.")
    return _post_form(
        f"{KC_BASE}/realms/{REALM}/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": CLIENT,
            "username": user,
            "password": password,
        },
    )["access_token"]


def variety_of(crop_path: str) -> str:
    """Last segment of `mango.crimson`, lowercased. `mango` alone -> ''."""
    parts = crop_path.split(".")
    return parts[-1].lower() if len(parts) > 1 else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print, change nothing")
    ap.add_argument(
        "--cover-sizes",
        action="store_true",
        help="also move the COVERAGE blocks so every size branch is reachable",
    )
    args = ap.parse_args()

    tok = token()

    farm = next((f for f in _items(_api(tok, "/farms")) if f["name"] == FARM_NAME), None)
    if farm is None:
        sys.exit(f"No farm named {FARM_NAME!r} in this tenant.")

    # The assignment rows carry no block code, so build the map once rather
    # than fetching a block per assignment.
    code_by_block = {
        b["id"]: b.get("code") or b.get("name") or b["id"][:8]
        for b in _items(_api(tok, f"/farms/{farm['id']}/blocks"))
    }

    rows = _items(_api(tok, f"/farms/{farm['id']}/crop-assignments"))
    print(f"{FARM_NAME}: {len(rows)} crop assignments")

    groups_used: set[str] = set()
    rejected: list[str] = []
    changed = 0

    for row in rows:
        block_crop_id = row["block_crop_id"]
        block_code = code_by_block.get(row.get("block_id"), "?")
        crop_path = row.get("crop_path", "")

        current = _api(tok, f"/crop-assignments/{block_crop_id}/attributes")

        # Send back only codes the catalog still serves as active definitions.
        # The stored values also carry retired codes (`003`, `004`,
        # `implantation_date`) left over from hand-authored fields that
        # migrations 0072 and 0079 turned off; echoing those into a whole-form
        # PUT would either 422 or resurrect them.
        live = {d["code"] for d in current.get("definitions", []) if d.get("is_active", True)}
        before = {k: v for k, v in current.get("values", {}).items() if k in live}
        values = dict(before)

        group = VARIETY_GROUP.get(variety_of(crop_path), "unconfirmed")
        values["harvest_season_group"] = group
        groups_used.add(group)

        if args.cover_sizes and block_code in COVERAGE:
            for code, value in COVERAGE[block_code].items():
                if value is None:
                    values.pop(code, None)
                else:
                    values[code] = value

        if values == before:
            continue

        delta = {
            k: (before.get(k), values.get(k))
            for k in set(before) | set(values)
            if before.get(k) != values.get(k)
        }
        if args.dry_run:
            print(f"  {block_code:>4}  {crop_path:<16} {delta}")
            changed += 1
            continue

        # The PUT is a WHOLE-FORM replace and it runs the `required_when`
        # rules over everything submitted, not only over what changed. On this
        # farm all 36 blocks carry `establishment_method`, and 8 of them carry
        # `grafted_tree`, which makes transplant_date, age_at_transplant_months
        # and rootstock_type required -- none of which was ever filled in. The
        # values were written by tenant migration 0084's bulk copy, which does
        # not run the validator, so those 8 blocks cannot be saved through the
        # form at all until somebody supplies three horticultural facts. That
        # is a real defect and not this script's to paper over: report the
        # block and move on rather than inventing a transplant date.
        try:
            _api(
                tok,
                f"/crop-assignments/{block_crop_id}/attributes",
                method="PUT",
                body={"attributes": values},
            )
        except _ApiError as exc:
            print(f"  {block_code:>4}  {crop_path:<16} REJECTED {exc.detail[:160]}")
            rejected.append(block_code)
            continue
        print(f"  {block_code:>4}  {crop_path:<16} {delta}")
        changed += 1

    print()
    print(f"{'would change' if args.dry_run else 'changed'}: {changed} assignments")
    if rejected:
        print(f"rejected by the form validator: {len(rejected)} -> {sorted(rejected)}")
    print(f"harvest groups present on this farm: {sorted(groups_used)}")
    missing = {"early", "mid", "late", "unconfirmed"} - groups_used
    if missing:
        print(f"harvest groups with no block here: {sorted(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
