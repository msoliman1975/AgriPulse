"""Loader for `taxonomy.yaml` — the closed telemetry vocabulary.

Mirrors the `shared/rbac/check.py` pattern: a YAML file next to the module,
parsed once into a frozen registry. Validation lives here rather than in the
Pydantic schema because the vocabulary is data, not types — adding a feature
should be a one-line YAML change, not a code change.

The registry is the *only* thing that decides what may be stored. An unknown
event name, feature or flow is rejected; an unknown `props` key is dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_TAXONOMY_FILE = Path(__file__).resolve().parent / "taxonomy.yaml"


class TaxonomyError(ValueError):
    """`taxonomy.yaml` is malformed. Raised at import/first-use, never per-request."""


@dataclass(frozen=True)
class Flow:
    name: str
    timeout_minutes: int
    steps: tuple[str, ...]


@dataclass(frozen=True)
class Taxonomy:
    """The vocabulary. Frozen — callers must not mutate it per request."""

    version: int
    # event name -> allowed props keys
    events: dict[str, frozenset[str]]
    features: frozenset[str]
    flows: dict[str, Flow]

    # --- membership --------------------------------------------------------

    def has_event(self, name: str) -> bool:
        return name in self.events

    def has_feature(self, name: str) -> bool:
        return name in self.features

    def has_flow(self, name: str) -> bool:
        return name in self.flows

    def allows_step(self, flow: str, step: str) -> bool:
        spec = self.flows.get(flow)
        return spec is not None and step in spec.steps

    def filter_props(self, event_name: str, props: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Return (kept, dropped_count) for one event's props.

        Unknown keys are dropped silently rather than rejected: a stale client
        shipping an extra key should not lose the whole event, and the point of
        the allow-list is that unknown data never lands, not that it 400s.
        """
        allowed = self.events.get(event_name, frozenset())
        kept = {k: v for k, v in props.items() if k in allowed}
        return kept, len(props) - len(kept)


def _parse_events(raw: object) -> dict[str, frozenset[str]]:
    if not isinstance(raw, dict) or not raw:
        raise TaxonomyError("taxonomy.yaml: 'events' must be a non-empty mapping")
    events: dict[str, frozenset[str]] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise TaxonomyError(f"taxonomy.yaml: event '{name}' must be a mapping")
        props = spec.get("props") or []
        if not isinstance(props, list) or any(not isinstance(p, str) for p in props):
            raise TaxonomyError(f"taxonomy.yaml: event '{name}' props must be a list of strings")
        events[str(name)] = frozenset(props)
    return events


def _parse_features(raw: object) -> frozenset[str]:
    if not isinstance(raw, list) or not raw:
        raise TaxonomyError("taxonomy.yaml: 'features' must be a non-empty list")
    if any(not isinstance(f, str) for f in raw):
        raise TaxonomyError("taxonomy.yaml: 'features' must be strings")
    features = frozenset(str(f) for f in raw)
    if len(features) != len(raw):
        raise TaxonomyError("taxonomy.yaml: duplicate feature")
    return features


def _parse_flows(raw: object) -> dict[str, Flow]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TaxonomyError("taxonomy.yaml: 'flows' must be a mapping")
    flows: dict[str, Flow] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise TaxonomyError(f"taxonomy.yaml: flow '{name}' must be a mapping")
        timeout = spec.get("timeout_minutes")
        if not isinstance(timeout, int) or timeout <= 0:
            raise TaxonomyError(f"taxonomy.yaml: flow '{name}' needs a positive timeout_minutes")
        steps = spec.get("steps") or []
        if not isinstance(steps, list) or any(not isinstance(s, str) for s in steps):
            raise TaxonomyError(f"taxonomy.yaml: flow '{name}' steps must be a list of strings")
        flows[str(name)] = Flow(
            name=str(name), timeout_minutes=timeout, steps=tuple(str(s) for s in steps)
        )
    return flows


def _parse(doc: object) -> Taxonomy:
    if not isinstance(doc, dict):
        raise TaxonomyError("taxonomy.yaml: top level must be a mapping")

    version = doc.get("version")
    if not isinstance(version, int):
        raise TaxonomyError("taxonomy.yaml: 'version' must be an int")

    return Taxonomy(
        version=version,
        events=_parse_events(doc.get("events")),
        features=_parse_features(doc.get("features")),
        flows=_parse_flows(doc.get("flows")),
    )


def load_taxonomy_from_yaml(text: str) -> Taxonomy:
    """Parse a taxonomy document. Exposed so tests can feed a fixture."""
    return _parse(yaml.safe_load(text) or {})


@lru_cache(maxsize=1)
def get_taxonomy() -> Taxonomy:
    """The process-wide vocabulary, parsed once."""
    return load_taxonomy_from_yaml(_TAXONOMY_FILE.read_text(encoding="utf-8"))
