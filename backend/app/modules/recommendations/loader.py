"""Compile a decision-tree spec into the stored JSON body.

`compile_tree` turns an authored YAML spec into the compiled form held in
`public.decision_tree_versions.tree_compiled`, and validates the node graph
on the way: the root exists, every `on_match` / `on_miss` resolves, every leaf
has an outcome, and there are no unreachable nodes.

Compilation is structural only. Predicate syntax inside `condition.tree` is
left to the shared evaluator — a malformed predicate simply never matches at
runtime, which matches the "permissive on missing data" contract.

This module used to load too. `sync_from_disk` read `seeds/*.yaml` at every
startup and republished any tree whose compiled hash differed, which is what
made a platform tree uneditable in the app: the file won, silently, at the
next restart. Public migration 0085 carried the 33 definitions into the
database, the startup sync stopped, and the files and the function are now
gone. A tree is a row, and the app is the only way to change one.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.logging import get_logger
from app.modules.recommendations.errors import DecisionTreeParseError
from app.modules.recommendations.status_codes import LEAF_KINDS, STATUS_CODES, kind_of

_log = get_logger(__name__)

# The closed block soil-texture vocabulary (mirrors farms.schemas.SoilTexture
# / the blocks.soil_texture CHECK). Tree targeting may only reference these.
_SOIL_TEXTURES: frozenset[str] = frozenset(
    {"sandy", "sandy_loam", "loam", "clay_loam", "clay", "silty_loam", "silty_clay"}
)


def _as_str_list(value: Any, *, key: str, source_path: str) -> list[str]:
    """Coerce a YAML targeting axis to a list of non-empty strings.

    Accepts a single string (convenience for one-element axes) or a list.
    ``None`` / missing → empty list (= matches any).
    """
    if value is None:
        return []
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list):
        raise DecisionTreeParseError(
            path=source_path, detail=f"{key!r} must be a string or a list of strings"
        )
    out: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item:
            raise DecisionTreeParseError(
                path=source_path, detail=f"{key!r} entries must be non-empty strings"
            )
        if item not in out:  # dedupe, preserve order
            out.append(item)
    return out


def _validate_targeting(
    spec: dict[str, Any], source_path: str
) -> tuple[list[str], list[str], list[str]]:
    """Parse + validate the three targeting axes from a tree spec.

    Returns ``(crop_paths, country_codes, soil_textures)``. ``crop_paths``
    accepts the new plural key and/or the legacy singular ``crop_path``;
    country codes are normalized to upper-case ISO-3166 alpha-2; soil
    textures must belong to the closed block vocabulary. An axis that is
    absent / empty means "matches any" (enforced by the engine matcher).
    """
    crop_paths = _as_str_list(spec.get("crop_paths"), key="crop_paths", source_path=source_path)
    for legacy in _as_str_list(spec.get("crop_path"), key="crop_path", source_path=source_path):
        if legacy not in crop_paths:
            crop_paths.append(legacy)
    for path in crop_paths:
        # Dot-joined catalog codes; reject empty segments so a typo like
        # ``mango..short`` can't silently widen the match.
        if any(seg == "" for seg in path.split(".")):
            raise DecisionTreeParseError(
                path=source_path, detail=f"crop path {path!r} has an empty segment"
            )

    raw_countries = _as_str_list(
        spec.get("country_codes"), key="country_codes", source_path=source_path
    )
    country_codes: list[str] = []
    for code in raw_countries:
        upper = code.upper()
        if len(upper) != 2 or not upper.isalpha():
            raise DecisionTreeParseError(
                path=source_path,
                detail=f"country code {code!r} must be two letters (ISO 3166-1 alpha-2)",
            )
        if upper not in country_codes:
            country_codes.append(upper)

    soil_textures = _as_str_list(
        spec.get("soil_textures"), key="soil_textures", source_path=source_path
    )
    for soil in soil_textures:
        if soil not in _SOIL_TEXTURES:
            raise DecisionTreeParseError(
                path=source_path,
                detail=(
                    f"soil texture {soil!r} is not a valid block soil texture "
                    f"({', '.join(sorted(_SOIL_TEXTURES))})"
                ),
            )

    return crop_paths, country_codes, soil_textures


def compile_tree(spec: dict[str, Any], *, source_path: str) -> dict[str, Any]:
    """Validate + normalize an authored YAML spec into the compiled JSON
    shape consumed by ``engine.evaluate_tree``.

    Raises ``DecisionTreeParseError`` on structural problems (missing
    root, dangling pointer, leaf without outcome). The exception is
    surfaced at startup-time sync; never at request time.
    """
    if not isinstance(spec, dict):
        raise DecisionTreeParseError(path=source_path, detail="top-level must be a mapping")

    code = spec.get("code")
    if not isinstance(code, str) or not code:
        raise DecisionTreeParseError(path=source_path, detail="missing 'code'")

    crop_paths, country_codes, soil_textures = _validate_targeting(spec, source_path)
    # Legacy single-value column: the first targeted path (or None). Kept so
    # crop_id resolution + crop-scoped reads/display keep working unchanged.
    crop_path = crop_paths[0] if crop_paths else None

    scope = spec.get("scope", "block")
    if scope not in ("block", "cell"):
        raise DecisionTreeParseError(
            path=source_path, detail=f"'scope' must be 'block' or 'cell', got {scope!r}"
        )

    name_en = spec.get("name_en")
    if not isinstance(name_en, str) or not name_en:
        raise DecisionTreeParseError(path=source_path, detail="missing 'name_en'")

    nodes_raw = spec.get("nodes")
    if not isinstance(nodes_raw, dict) or not nodes_raw:
        raise DecisionTreeParseError(path=source_path, detail="'nodes' must be a non-empty mapping")

    root = spec.get("root", "root")
    if not isinstance(root, str) or root not in nodes_raw:
        raise DecisionTreeParseError(
            path=source_path,
            detail=f"'root' {root!r} is not a node in 'nodes'",
        )

    # Walk reachability so a typo in on_match/on_miss surfaces here, not
    # at sweep time when a tenant block hits the dead branch.
    _validate_reachability(nodes_raw, root, source_path)

    # Validate the optional `parameters:` declaration block (PR-B) and
    # walk the node tree to verify every `{source: params, name: x}`
    # ref names a declared parameter. Trees that don't declare params
    # skip this entirely and behave exactly like pre-PR-B trees.
    parameters_decl = _validate_parameters_block(spec, source_path)
    _validate_params_refs(nodes_raw, parameters_decl, source_path)
    _validate_condition_ops(nodes_raw, source_path)

    # Validate the optional scientific-provenance blocks (KB P1-A).
    # These are display/governance metadata only — the evaluator never
    # reads them. They ride inside `tree_compiled` so they version
    # immutably with the tree and surface through the existing
    # DecisionTreeVersionResponse without a schema migration. Trees that
    # omit them get `null` and behave exactly as before.
    evidence = _validate_evidence_block(spec, source_path)
    transferability = _validate_transferability_block(spec, source_path)

    compiled: dict[str, Any] = {
        "code": code,
        "name_en": name_en,
        "name_ar": spec.get("name_ar"),
        "description_en": spec.get("description_en"),
        "description_ar": spec.get("description_ar"),
        "crop_code": spec.get("crop_code"),
        "crop_path": crop_path,
        "crop_paths": crop_paths,
        "country_codes": country_codes,
        "soil_textures": soil_textures,
        "scope": scope,
        "applicable_regions": list(spec.get("applicable_regions") or []),
        "parameters": parameters_decl,
        "evidence": evidence,
        "transferability": transferability,
        "root": root,
        "nodes": nodes_raw,
    }
    return compiled


# Allowed `type:` values in a parameter declaration. Each maps to a
# permissive coercion: the engine just stores values; the YAML loader
# checks the *default* fits the declared type so a buggy YAML surfaces
# at startup, not during evaluation.
_PARAM_TYPES: frozenset[str] = frozenset({"number", "integer", "boolean", "string", "enum"})


def _validate_parameters_block(spec: dict[str, Any], source_path: str) -> dict[str, dict[str, Any]]:
    """Strict-parse the optional ``parameters:`` block.

    Each entry must have a ``type`` and a ``default``. ``enum`` types
    additionally require a non-empty ``values`` list and the default
    must be one of the values. Returns a normalized mapping keyed by
    parameter name; an empty dict when no ``parameters:`` block exists.
    """
    raw = spec.get("parameters")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise DecisionTreeParseError(path=source_path, detail="'parameters' must be a mapping")

    normalized: dict[str, dict[str, Any]] = {}
    for name, decl in raw.items():
        if not isinstance(name, str) or not name:
            raise DecisionTreeParseError(
                path=source_path, detail="parameter names must be non-empty strings"
            )
        if not isinstance(decl, dict):
            raise DecisionTreeParseError(
                path=source_path,
                detail=f"parameter {name!r} declaration must be a mapping",
            )
        type_ = decl.get("type")
        if type_ not in _PARAM_TYPES:
            raise DecisionTreeParseError(
                path=source_path,
                detail=f"parameter {name!r} 'type' must be one of {sorted(_PARAM_TYPES)}",
            )
        if "default" not in decl:
            raise DecisionTreeParseError(
                path=source_path,
                detail=f"parameter {name!r} missing 'default'",
            )
        default = decl["default"]
        if type_ == "enum":
            values = decl.get("values")
            if not isinstance(values, list) or not values:
                raise DecisionTreeParseError(
                    path=source_path,
                    detail=f"enum parameter {name!r} requires non-empty 'values'",
                )
            if default not in values:
                raise DecisionTreeParseError(
                    path=source_path,
                    detail=f"enum parameter {name!r} default {default!r} not in values",
                )

        normalized[name] = {
            "type": type_,
            "default": default,
            "description": decl.get("description"),
            "min": decl.get("min"),
            "max": decl.get("max"),
            "values": list(decl.get("values") or []) if type_ == "enum" else None,
        }
    return normalized


# ---------------------------------------------------------------------
# Scientific-provenance blocks (KB P1-A) — `evidence:` + `transferability:`
#
# Optional, evaluator-invisible metadata that lets a seeded knowledge-base
# condition carry its provenance (peer-reviewed / FAO / USDA / extension
# citations + an evidence-quality grade) and per-region applicability. The
# research task that drives the KB demands "do not fabricate; state
# uncertainty explicitly" — `evidence.confidence` + `evidence.notes` are
# where that uncertainty is recorded.
# ---------------------------------------------------------------------

# Evidence-quality grade — how strong the *science* is (distinct from a
# leaf's result `confidence`, which is firing probability).
_EVIDENCE_CONFIDENCE: frozenset[str] = frozenset({"very_high", "high", "medium", "low"})

# Authoritative source categories the research task accepts.
_CITATION_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "peer_reviewed",
        "fao",
        "usda",
        "extension",
        "university",
        "research_institution",
        "remote_sensing",
        "government",
    }
)

# Per-region transferability suitability grades.
_TRANSFERABILITY_GRADES: frozenset[str] = frozenset(
    {"very_high", "high", "medium", "low", "not_applicable"}
)
# The three regions the research task scores every finding against.
_TRANSFERABILITY_REGIONS: frozenset[str] = frozenset({"egypt", "middle_east", "global"})


def _validate_evidence_block(spec: dict[str, Any], source_path: str) -> dict[str, Any] | None:
    """Strict-parse the optional ``evidence:`` block.

    Shape::

        evidence:
          confidence: high            # required: very_high|high|medium|low
          notes: "..."                # optional free-text (uncertainty)
          citations:                  # optional
            - source_type: peer_reviewed
              title: "..."            # required
              doi: "10.xxxx/yyyy"     # optional
              url: "https://..."      # optional
              year: 2019              # optional int

    Returns a normalized dict, or ``None`` when no block is present.
    """
    raw = spec.get("evidence")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DecisionTreeParseError(path=source_path, detail="'evidence' must be a mapping")

    confidence = raw.get("confidence")
    if confidence not in _EVIDENCE_CONFIDENCE:
        raise DecisionTreeParseError(
            path=source_path,
            detail=(
                f"evidence 'confidence' must be one of "
                f"{sorted(_EVIDENCE_CONFIDENCE)}, got {confidence!r}"
            ),
        )

    notes = raw.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise DecisionTreeParseError(path=source_path, detail="evidence 'notes' must be a string")

    citations_raw = raw.get("citations")
    citations: list[dict[str, Any]] = []
    if citations_raw is not None:
        if not isinstance(citations_raw, list):
            raise DecisionTreeParseError(
                path=source_path, detail="evidence 'citations' must be a list"
            )
        for i, cite in enumerate(citations_raw):
            citations.append(_validate_citation(cite, i, source_path))

    return {"confidence": confidence, "notes": notes, "citations": citations}


def _validate_citation(cite: Any, index: int, source_path: str) -> dict[str, Any]:
    if not isinstance(cite, dict):
        raise DecisionTreeParseError(
            path=source_path, detail=f"evidence citation #{index} must be a mapping"
        )
    source_type = cite.get("source_type")
    if source_type not in _CITATION_SOURCE_TYPES:
        raise DecisionTreeParseError(
            path=source_path,
            detail=(
                f"citation #{index} 'source_type' must be one of "
                f"{sorted(_CITATION_SOURCE_TYPES)}, got {source_type!r}"
            ),
        )
    title = cite.get("title")
    if not isinstance(title, str) or not title:
        raise DecisionTreeParseError(
            path=source_path,
            detail=f"citation #{index} requires a non-empty 'title'",
        )
    year = cite.get("year")
    if year is not None and not isinstance(year, int):
        raise DecisionTreeParseError(
            path=source_path, detail=f"citation #{index} 'year' must be an integer"
        )
    for opt in ("doi", "url"):
        val = cite.get(opt)
        if val is not None and not isinstance(val, str):
            raise DecisionTreeParseError(
                path=source_path,
                detail=f"citation #{index} {opt!r} must be a string",
            )
    return {
        "source_type": source_type,
        "title": title,
        "doi": cite.get("doi"),
        "url": cite.get("url"),
        "year": year,
    }


def _validate_transferability_block(
    spec: dict[str, Any], source_path: str
) -> dict[str, Any] | None:
    """Strict-parse the optional ``transferability:`` block.

    Shape::

        transferability:
          egypt: high
          middle_east: high
          global: medium

    Keys are restricted to the three research regions; each value is a
    suitability grade. Missing regions normalize to ``None``. Returns
    ``None`` when no block is present.
    """
    raw = spec.get("transferability")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DecisionTreeParseError(path=source_path, detail="'transferability' must be a mapping")

    normalized: dict[str, Any] = {region: None for region in sorted(_TRANSFERABILITY_REGIONS)}
    for region, grade in raw.items():
        if region not in _TRANSFERABILITY_REGIONS:
            raise DecisionTreeParseError(
                path=source_path,
                detail=(
                    f"transferability region {region!r} must be one of "
                    f"{sorted(_TRANSFERABILITY_REGIONS)}"
                ),
            )
        if grade not in _TRANSFERABILITY_GRADES:
            raise DecisionTreeParseError(
                path=source_path,
                detail=(
                    f"transferability[{region}] must be one of "
                    f"{sorted(_TRANSFERABILITY_GRADES)}, got {grade!r}"
                ),
            )
        normalized[region] = grade
    return normalized


def _validate_params_refs(
    nodes: dict[str, Any],
    parameters_decl: dict[str, dict[str, Any]],
    source_path: str,
) -> None:
    """Walk every node's condition tree and every leaf's outcome.parameters
    looking for ``{source: params, name: x}`` refs. Each `x` must be a
    declared parameter; missing declarations surface as a parse error
    at startup so trees never ship referencing a typo'd parameter."""
    declared = set(parameters_decl.keys())

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("source") == "params":
                ref_name = value.get("name")
                if not isinstance(ref_name, str) or ref_name not in declared:
                    raise DecisionTreeParseError(
                        path=source_path,
                        detail=(
                            f"params ref {ref_name!r} is not declared in "
                            "the tree's 'parameters' block"
                        ),
                    )
                return
            for child in value.values():
                _walk(child)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        condition = node.get("condition")
        if isinstance(condition, dict):
            _walk(condition.get("tree"))
        outcome = node.get("outcome")
        if isinstance(outcome, dict):
            _walk(outcome.get("parameters"))


# Every operator ``app.shared.conditions.evaluator`` knows. The evaluator is
# deliberately permissive at request time — an unrecognised node raises
# ``ConditionParseError``, which ``evaluate`` catches and turns into a plain
# "did not match". That is the right behaviour for a half-loaded tenant, but
# it means a MISSPELLED operator is indistinguishable from a condition that
# legitimately failed: the branch silently takes ``on_miss`` for ever and no
# card, log line or trace ever says why.
#
# Author input reaches ``compile_tree`` from two directions (the seeds on disk
# and the authoring API), and neither had anything checking this. Writing
# ``gte`` instead of ``ge`` — the spelling most other rule engines use —
# produced a tree that compiled, published, ran, and quietly answered "no" to
# a question it never actually asked.
_CONDITION_OPS: frozenset[str] = frozenset({"lt", "le", "gt", "ge", "eq", "ne", "between", "in"})


def _validate_condition_ops(nodes: dict[str, Any], source_path: str) -> None:
    """Reject any comparison whose ``op`` the evaluator does not implement."""

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            if "op" in value:
                op = value.get("op")
                if op not in _CONDITION_OPS:
                    raise DecisionTreeParseError(
                        path=source_path,
                        detail=(
                            f"condition operator {op!r} is not one of " f"{sorted(_CONDITION_OPS)}"
                        ),
                    )
            for child in value.values():
                _walk(child)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        condition = node.get("condition")
        if isinstance(condition, dict):
            _walk(condition.get("tree"))


def collect_crop_attribute_codes(nodes: dict[str, Any]) -> set[str]:
    """Every ``{source: crop_attribute, code: x}`` code the tree references.

    Public and pure so the authoring service can check the codes against
    the catalog without importing the walker's internals. Unlike the params
    refs above this cannot be validated inside ``compile_tree``: the valid
    set is data (``public.crop_attribute_definitions``) scoped to the tree's
    target crops, and compile_tree is sync, DB-free, and runs at startup for
    the platform seeds.

    Only comparison operands are walked, not ``outcome.parameters`` — a
    crop_attribute ref is a value ref, and the outcome block holds literals.
    """
    codes: set[str] = set()

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("source") == "crop_attribute":
                code = value.get("code")
                if isinstance(code, str) and code:
                    codes.add(code)
                return
            for child in value.values():
                _walk(child)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        condition = node.get("condition")
        if isinstance(condition, dict):
            _walk(condition.get("tree"))
    return codes


def _validate_reachability(
    nodes: dict[str, Any], root: str, source_path: str, *, max_steps: int = 1024
) -> None:
    seen: set[str] = set()
    stack: list[str] = [root]
    steps = 0
    while stack:
        steps += 1
        if steps > max_steps:
            raise DecisionTreeParseError(
                path=source_path,
                detail=f"reachability check exceeded {max_steps} steps",
            )
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        node = nodes.get(nid)
        if not isinstance(node, dict):
            raise DecisionTreeParseError(
                path=source_path,
                detail=f"node {nid!r} is not a mapping",
            )
        if "outcome" in node:
            outcome = node["outcome"]
            if not isinstance(outcome, dict):
                raise DecisionTreeParseError(
                    path=source_path,
                    detail=f"leaf {nid!r} 'outcome' must be a mapping",
                )
            # Leaf kind discriminator. Four kinds: alert, recommendation,
            # status, no_action. A tree published before `status` existed
            # names no kind and says `action_type: no_action` instead, so
            # that spelling still compiles and means kind=no_action.
            declared_kind = outcome.get("kind")
            if declared_kind is not None and declared_kind not in LEAF_KINDS:
                raise DecisionTreeParseError(
                    path=source_path,
                    detail=(
                        f"leaf {nid!r} 'outcome.kind' must be one of "
                        f"{sorted(LEAF_KINDS)}, got {declared_kind!r}"
                    ),
                )
            kind = kind_of(outcome)
            # An action type is what a person does about it, so only the two
            # kinds that ask for work carry one.
            if kind in ("alert", "recommendation") and not isinstance(
                outcome.get("action_type"), str
            ):
                raise DecisionTreeParseError(
                    path=source_path,
                    detail=f"leaf {nid!r} 'outcome.action_type' must be a string",
                )
            _validate_outcome_status(outcome, nid, source_path, kind=kind)
            if kind == "alert":
                severity = outcome.get("severity")
                if severity not in ("info", "warning", "critical"):
                    raise DecisionTreeParseError(
                        path=source_path,
                        detail=(
                            f"alert leaf {nid!r} requires 'severity' in "
                            f"info/warning/critical, got {severity!r}"
                        ),
                    )
            # Optional 4-horizon `actions:` block (KB P1-B).
            _validate_outcome_actions(outcome, nid, source_path)
            continue
        # Decision node — both branches must point at known nodes.
        for branch in ("on_match", "on_miss"):
            target = node.get(branch)
            if not isinstance(target, str) or target not in nodes:
                raise DecisionTreeParseError(
                    path=source_path,
                    detail=f"node {nid!r} {branch!r} → {target!r} is not a known node",
                )
            stack.append(target)


# 4-horizon recommendation actions (KB P1-B). A leaf outcome may split
# its guidance into these time horizons; each holds an ordered list of
# localized action items. Optional — leaves without it keep their single
# ``text_en`` summary as the only guidance.
_ACTION_HORIZONS: frozenset[str] = frozenset({"immediate", "short_term", "long_term", "monitoring"})


def _validate_outcome_status(
    outcome: dict[str, Any], nid: str, source_path: str, *, kind: str
) -> None:
    """Strict-parse a leaf outcome's ``status`` field.

    Only a ``status`` leaf names one. An alert leaf that named `good` would
    paint itself green while opening a red card, so naming a status on any
    other kind is an error and not a value we quietly drop.

    An unknown status is a hard error here on purpose. An unknown condition
    operator used to compile, publish and run without showing any error,
    because the evaluator caught the parse failure and answered "did not
    match"; that branch then took `on_miss` for ever with no card and no log
    line. A typo in a status must not be able to do the same.
    """
    declared = outcome.get("status")
    if declared is None:
        return
    if kind != "status":
        raise DecisionTreeParseError(
            path=source_path,
            detail=(
                f"leaf {nid!r} sets 'outcome.status' but its kind is {kind!r}. "
                f"Only a 'status' leaf names a status."
            ),
        )
    if declared not in STATUS_CODES:
        raise DecisionTreeParseError(
            path=source_path,
            detail=(
                f"leaf {nid!r} 'outcome.status' must be one of "
                f"{sorted(STATUS_CODES)}, got {declared!r}"
            ),
        )


def _validate_outcome_actions(outcome: dict[str, Any], nid: str, source_path: str) -> None:
    """Strict-parse a leaf outcome's optional ``actions:`` block.

    Shape::

        actions:
          immediate:
            - text_en: "..."
              text_ar: "..."   # optional
          short_term: [...]
          long_term: [...]
          monitoring: [...]

    Unknown horizon keys and items missing ``text_en`` are hard errors
    so a typo surfaces at startup sync, not silently at render time.
    """
    raw = outcome.get("actions")
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise DecisionTreeParseError(
            path=source_path, detail=f"leaf {nid!r} 'outcome.actions' must be a mapping"
        )
    for horizon, items in raw.items():
        if horizon not in _ACTION_HORIZONS:
            raise DecisionTreeParseError(
                path=source_path,
                detail=(
                    f"leaf {nid!r} actions horizon {horizon!r} must be one of "
                    f"{sorted(_ACTION_HORIZONS)}"
                ),
            )
        if not isinstance(items, list):
            raise DecisionTreeParseError(
                path=source_path,
                detail=f"leaf {nid!r} actions[{horizon}] must be a list",
            )
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise DecisionTreeParseError(
                    path=source_path,
                    detail=f"leaf {nid!r} actions[{horizon}][{i}] must be a mapping",
                )
            text_en = item.get("text_en")
            if not isinstance(text_en, str) or not text_en:
                raise DecisionTreeParseError(
                    path=source_path,
                    detail=(
                        f"leaf {nid!r} actions[{horizon}][{i}] requires a " "non-empty 'text_en'"
                    ),
                )
            text_ar = item.get("text_ar")
            if text_ar is not None and not isinstance(text_ar, str):
                raise DecisionTreeParseError(
                    path=source_path,
                    detail=(f"leaf {nid!r} actions[{horizon}][{i}] 'text_ar' must " "be a string"),
                )


def _hash_compiled(compiled: dict[str, Any]) -> str:
    payload = json.dumps(compiled, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
