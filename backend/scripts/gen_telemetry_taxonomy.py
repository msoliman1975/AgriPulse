"""Regenerate the TypeScript half of the telemetry vocabulary.

    python backend/scripts/gen_telemetry_taxonomy.py

`backend/app/modules/telemetry/taxonomy.yaml` is the single source of truth.
The server reads it at runtime; the client cannot, so its unions are generated
from it into `frontend/src/telemetry/taxonomy.generated.ts` and committed.

Committing generated code is a deliberate trade: it keeps the frontend build
free of a codegen step, and a drift test on each side
(`frontend/src/telemetry/taxonomy.test.ts` and
`backend/tests/unit/telemetry/test_taxonomy_generated_ts.py`) fails CI if this
script was not re-run. Without those tests this file would rot in a week.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
_YAML = _ROOT / "backend" / "app" / "modules" / "telemetry" / "taxonomy.yaml"
_TS = _ROOT / "frontend" / "src" / "telemetry" / "taxonomy.generated.ts"

_HEADER = """// GENERATED FILE — do not edit by hand.
//
// Source: backend/app/modules/telemetry/taxonomy.yaml
// Regenerate: python backend/scripts/gen_telemetry_taxonomy.py
//
// The server validates every event against the same YAML and rejects anything
// not named there, so editing this file alone changes nothing except which
// calls the compiler lets you write. Edit the YAML and re-run the script.
"""


def _union(names: list[str]) -> str:
    return "\n  | ".join(f'"{n}"' for n in names)


def render(spec: dict) -> str:
    events = sorted(spec["events"])
    features = sorted(spec["features"])
    flows = spec["flows"]

    props = "\n".join(
        f"  {name}: [{', '.join(chr(34) + p + chr(34) for p in spec['events'][name].get('props') or [])}],"
        for name in events
    )
    flow_entries = "\n".join(
        "  {name}: {{ timeoutMinutes: {t}, steps: [{s}] }},".format(
            name=name,
            t=int(flows[name]["timeout_minutes"]),
            s=", ".join(f'"{s}"' for s in flows[name]["steps"]),
        )
        for name in sorted(flows)
    )
    return f"""{_HEADER}
export const TAXONOMY_VERSION = {int(spec["version"])};

export type TelemetryEventName =
  | {_union(events)};

export type TelemetryFeature =
  | {_union(features)};

export type TelemetryFlow =
  | {_union(sorted(flows))};

/** Props keys the server keeps per event. Anything else is dropped on ingest. */
export const ALLOWED_PROPS: Record<TelemetryEventName, readonly string[]> = {{
{props}
}} as const;

export const FEATURES: readonly TelemetryFeature[] = [
{chr(10).join(f'  "{f}",' for f in features)}
] as const;

/** `timeoutMinutes` is what the server-side abandonment query uses; the client
 * never enforces it, because the case we care about is the user who left. */
export const FLOWS: Record<TelemetryFlow, {{ timeoutMinutes: number; steps: readonly string[] }}> = {{
{flow_entries}
}} as const;

export type TelemetryFlowStep<F extends TelemetryFlow = TelemetryFlow> =
  (typeof FLOWS)[F]["steps"][number];
"""


def main() -> int:
    spec = yaml.safe_load(_YAML.read_text(encoding="utf-8"))
    rendered = render(spec)
    check = "--check" in sys.argv
    current = _TS.read_text(encoding="utf-8") if _TS.exists() else None
    if current == rendered:
        print("up to date")
        return 0
    if check:
        print(f"STALE: {_TS} does not match {_YAML}", file=sys.stderr)
        return 1
    _TS.parent.mkdir(parents=True, exist_ok=True)
    _TS.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {_TS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
