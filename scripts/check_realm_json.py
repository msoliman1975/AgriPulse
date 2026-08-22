#!/usr/bin/env python3
"""Refuse a realm file that would crash Keycloak at boot.

Keycloak parses the realm import into ``RealmRepresentation`` with unknown
fields rejected, so one key the class does not declare exits the container:

    ERROR: Failed to run import
    ERROR: Unrecognized field "_comment_users"

That is not a warning and not a skipped field. A StatefulSet does not
restart when a ConfigMap changes, so a bad key sits harmless until the next
image bump and then takes down every pod that rolls. ``_comment_users``
went in on 2026-06-09 and surfaced on 2026-08-22, 74 days later, when the
first pod to actually read the file went to CrashLoopBackOff.

Underscore-prefixed keys are the whole class of "I wanted a comment in a
format that has none". Put the explanation in
``infra/helm/keycloak/templates/realm-configmap.yaml`` instead, where it
cannot reach the parser.

Usage: check_realm_json.py <realm.json> [<realm.json> ...]
Exit 0 if every file is clean, 1 otherwise. A path that does not exist is
skipped, so the caller can list optional files.
"""

from __future__ import annotations

import json
import pathlib
import sys


def check(path: pathlib.Path) -> bool:
    """Return True when the file is safe to hand to Keycloak."""
    try:
        realm = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"  {path}: not valid JSON — {exc}")
        return False

    if not isinstance(realm, dict):
        print(f"  {path}: top level is {type(realm).__name__}, expected an object")
        return False

    bad = sorted(key for key in realm if key.startswith("_"))
    if bad:
        print(f"  {path}: Keycloak will refuse these keys and the pod will not start: {bad}")
        print("  Put the explanation in realm-configmap.yaml, not in the JSON.")
        return False

    print(f"  {path}: ok — {len(realm)} top-level keys, none starting with an underscore")
    return True


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: check_realm_json.py <realm.json> [...]")
        return 2
    ok = True
    for name in argv:
        path = pathlib.Path(name)
        if not path.is_file():
            print(f"  {path}: not present, skipped")
            continue
        ok = check(path) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
