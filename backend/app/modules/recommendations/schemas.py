"""Pydantic schemas for the recommendations REST surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.recommendations import status_codes

ActionType = Literal[
    "irrigate",
    "fertilize",
    "spray",
    "scout",
    "harvest_window",
    "prune",
    "no_action",
    "other",
]
RecommendationState = Literal["open", "applied", "dismissed", "deferred", "expired"]
Severity = Literal["info", "warning", "critical"]

# The four kinds a leaf can be, and the five status codes an evaluation
# resolves to. Both come from `status_codes.py`, which is the one place the
# list is written; re-declaring them here would let the API and the engine
# drift apart.
LeafKind = status_codes.LeafKind
StatusCode = status_codes.StatusCode


class StatusDefinitionResponse(BaseModel):
    """One entry of the platform status list.

    The frontend reads this instead of holding its own copy of the codes and
    colours. A frontend copy of a backend list has drifted before.
    """

    code: StatusCode
    # Highest rank wins when one block holds several verdicts. `na` is 0, so
    # a tree with nothing to say never outranks a real answer.
    rank: int
    color: str
    label_en: str
    label_ar: str


class VerdictResponse(BaseModel):
    """One tree's answer about one block, or one of its grid cells.

    A row exists for every leaf the tree reached, including the ones that
    found nothing wrong. No row means the tree did not run there.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    farm_id: UUID
    block_id: UUID
    # NULL = the whole block. Set = one grid cell; row and column are joined
    # in so a reader can say "zone B4" instead of showing a UUID.
    cell_id: UUID | None = None
    cell_row: int | None = None
    cell_col: int | None = None
    scope: str
    tree_id: UUID
    tree_code: str
    tree_version: int
    leaf_node_id: str
    kind: LeafKind
    status_code: StatusCode
    # Set on alert and recommendation verdicts only.
    severity: Severity | None = None
    text_en: str
    text_ar: str | None = None
    # The interval this answer has held. `valid_to` is null while it is the
    # current one; a replay reads a row whose interval contains the date.
    valid_from: datetime
    valid_to: datetime | None = None
    last_evaluated_at: datetime
    # The work item this verdict came with, when it had one.
    alert_id: UUID | None = None
    recommendation_id: UUID | None = None
    # The sweep that last produced this answer. `confirm()` re-points it on
    # every run that reaches the same leaf, so it names the newest walk, not
    # the one that first opened the interval. It is how a reader gets from a
    # colour on a map to the conditions behind it:
    # `GET /decision-tree-traces?run_id=<this>&block_id=<block>` returns the
    # trace, and that trace carries `node_path` and `resolved_values`.
    last_run_id: UUID | None = None


class BlockVerdictsResponse(BaseModel):
    """Every tree's answer about one block."""

    block_id: UUID
    # Echoed exactly as the caller sent it, time zone or not. The comparison
    # itself uses a separate UTC instant: subtracting a naive datetime from a
    # timestamptz raises TypeError.
    as_of: datetime | None = None
    # The highest-ranking status across the block's verdicts, which is what
    # the block reads as. None when no tree has run on it.
    worst_status: StatusCode | None = None
    # The newest evaluation behind these rows. None when the list is empty.
    last_evaluated_at: datetime | None = None
    verdicts: list[VerdictResponse] = Field(default_factory=list)


class VerdictReasoningResponse(BaseModel):
    """One verdict with the node walk that produced it.

    The same shape a tree author sees under `/decision-tree-traces/{id}`,
    reachable by the roles that read verdicts rather than the ones that
    author trees.
    """

    model_config = ConfigDict(from_attributes=True)

    verdict_id: UUID
    block_id: UUID
    cell_id: UUID | None = None
    cell_row: int | None = None
    cell_col: int | None = None
    scope: str
    tree_id: UUID
    tree_code: str
    tree_version: int
    leaf_node_id: str
    kind: LeafKind
    status_code: StatusCode
    severity: Severity | None = None
    valid_from: datetime
    last_evaluated_at: datetime
    # False when retention has pruned the run behind this verdict. The
    # verdict still stands; only the walk is gone.
    reasoning_available: bool = False
    trace_id: UUID | None = None
    # The walk as prose, both languages, composed by
    # `recommendations.narrative`. The step list below stays for the reader
    # auditing a threshold; this is what the screen leads with, and what a
    # report or an email quotes so one block is never described two ways.
    narrative_en: str = ""
    narrative_ar: str = ""
    # The leaf's own sentence, which the narrative ends by quoting. Sent
    # separately so a caller can show it alone.
    text_en: str | None = None
    text_ar: str | None = None
    evaluated_at: datetime | None = None
    # The ordered walk: [{node_id, matched, label_en, label_ar, condition,
    # values}]. Empty when `reasoning_available` is false.
    node_path: list[dict[str, Any]] = Field(default_factory=list)
    # Merged resolved refs, {"indices.ndvi.mean": "0.39"}.
    resolved_values: dict[str, Any] = Field(default_factory=dict)
    # Tenant overrides in force for this walk, so a threshold that differs
    # from the tree's declared default is visible.
    param_overrides: dict[str, Any] = Field(default_factory=dict)


class FarmVerdictsResponse(BaseModel):
    """Every block of one farm, with its verdicts. One statement behind it."""

    farm_id: UUID
    as_of: datetime | None = None
    blocks: list[BlockVerdictsResponse] = Field(default_factory=list)


class FarmVerdictHistoryResponse(BaseModel):
    """Every verdict that stood at any point in a window, as intervals.

    One row per change, not per day. The client rebuilds a frame for a given
    day with the same test the SQL uses:
    `valid_from <= day AND (valid_to IS NULL OR valid_to > day)`.
    """

    farm_id: UUID
    from_at: datetime
    to_at: datetime
    tree_code: str | None = None
    # True when the guard cut the list. The caller has more history than a
    # replay can draw, and should narrow the window or name a tree rather
    # than draw a map that is quietly missing rows.
    truncated: bool = False
    verdicts: list[VerdictResponse] = Field(default_factory=list)


ActionHorizon = Literal["immediate", "short_term", "long_term", "monitoring"]


class RecommendationActionItem(BaseModel):
    """One localized action item within a time horizon (KB P1-B)."""

    text_en: str
    text_ar: str | None = None


class RecommendationResponse(BaseModel):
    """One row from `recommendations`."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    block_id: UUID
    # Sub-block grid cell for cell-scoped recommendations (per-cell P2); NULL
    # for block-scoped. cell_row/cell_col give a readable zone label.
    cell_id: UUID | None = None
    cell_row: int | None = None
    cell_col: int | None = None
    farm_id: UUID
    tree_id: UUID
    tree_code: str
    tree_version: int
    block_crop_id: UUID | None
    action_type: ActionType
    severity: Severity
    parameters: dict[str, Any]
    # 4-horizon structured guidance (KB P1-B). Keyed by ActionHorizon;
    # absent horizons are simply omitted. Empty for trees whose leaf
    # carries only the single `text_en` summary.
    actions: dict[ActionHorizon, list[RecommendationActionItem]] = Field(default_factory=dict)
    confidence: Decimal
    tree_path: list[dict[str, Any]]
    text_en: str
    text_ar: str | None
    valid_until: datetime | None
    state: RecommendationState
    applied_at: datetime | None
    applied_by: UUID | None
    dismissed_at: datetime | None
    dismissed_by: UUID | None
    dismissal_reason: str | None
    deferred_until: datetime | None
    outcome_notes: str | None
    created_at: datetime
    updated_at: datetime
    # Aggregation + recurrence (0079). A cell-scoped tree that fires on many
    # cells of one block returns ONE row here — the group — with
    # `member_count` cells behind it; the members are never listed. The
    # Action Center gives them a richer shape (`aggregation` / `recurrence`
    # objects plus a members endpoint); this list is the flat module view, so
    # the fields travel flat.
    is_group: bool = False
    member_count: int = 0
    occurrence_count: int = 1
    day_streak: int = 1
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class RecommendationTransitionRequest(BaseModel):
    """PATCH /api/v1/recommendations/{id} body — drives state transitions.

    Exactly one of ``apply``, ``dismiss``, ``defer_until`` may be set.
    """

    model_config = ConfigDict(extra="forbid")

    apply: bool = False
    dismiss: bool = False
    defer_until: datetime | None = None
    dismissal_reason: str | None = Field(default=None, max_length=500)
    outcome_notes: str | None = Field(default=None, max_length=2000)


class RecommendationScheduleRequest(BaseModel):
    """POST /api/v1/recommendations/{id}/schedule body.

    Spawns a board activity from this recommendation and transitions
    the rec to ``applied`` in one transaction. The rec's ``block_id``
    and inferred activity type are defaults the caller can override.
    """

    model_config = ConfigDict(extra="forbid")

    scheduled_date: datetime | None = None
    """If omitted, scheduled = today. Time component is ignored."""
    activity_type: (
        Literal[
            "planting",
            "fertilizing",
            "spraying",
            "pruning",
            "harvesting",
            "irrigation",
            "soil_prep",
            "observation",
        ]
        | None
    ) = None
    block_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)


class DecisionTreeResponse(BaseModel):
    """One row from `public.decision_trees` plus the current version."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    # NULL = platform-shipped business knowledge; non-NULL = the
    # caller's own tenant-authored tree (PR-A).
    tenant_id: UUID | None = None
    name_en: str
    name_ar: str | None
    description_en: str | None
    description_ar: str | None
    crop_id: UUID | None
    # Multi-axis targeting sets (PR-2) — surfaced so the list shows readable
    # crop/country targeting instead of a raw crop_id UUID.
    crop_paths: list[str] = Field(default_factory=list)
    country_codes: list[str] = Field(default_factory=list)
    soil_textures: list[str] = Field(default_factory=list)
    # Execution granularity: 'block' (default) or 'cell' (PR-C1).
    scope: str = "block"
    applicable_regions: list[str]
    is_active: bool
    current_version: int | None
    # Soft-delete flag (deleted_at IS NOT NULL). Archived trees are hidden
    # from the default catalog + never evaluated, but stay restorable.
    archived: bool = False


class EvaluateBlockResponse(BaseModel):
    """POST /api/v1/blocks/{block_id}/recommendations:evaluate response."""

    block_id: UUID
    # The lineage run this evaluation was recorded under; query its traces at
    # GET /decision-trees/eval-traces?run_id=…
    run_id: UUID | None = None
    trees_evaluated: int
    # Counts every targeting exclusion — country and soil as well as crop,
    # despite the name, which predates the other two axes.
    trees_skipped_crop: int
    recommendations_opened: int
    traces_written: int = 0
    # Verdicts stored for this block: one per tree that reached a leaf,
    # including the trees that found nothing wrong. Counts the rows opened
    # plus the ones confirmed, so a quiet night reports work rather than
    # zero (tenant 0091).
    verdicts_written: int = 0


class ExplainStep(BaseModel):
    """One node visited while walking a tree against a block."""

    node_id: str
    # None on leaf nodes — those are the verdict, not a check.
    matched: bool | None
    label_en: str | None
    label_ar: str | None
    # Resolved left-hand (and ref-valued right-hand) values, keyed by
    # dotted ref, e.g. {"index.ndvi.mean": "0.39"}.
    values: dict[str, Any] = Field(default_factory=dict)
    # The node's raw condition tree, so the reader can show the threshold
    # the value was compared against. None on leaves.
    condition: dict[str, Any] | None = None


class ExplainTree(BaseModel):
    """One tree's verdict for a block.

    ``status``:
      * ``fired``    — reached a leaf that opens a recommendation/alert
      * ``clear``    — reached a status or no_action leaf; ``status_code``
        says which, and the leaf's own words ride along
      * ``per_cell`` — cell-scoped; evaluated per grid cell, not here
      * ``skipped``  — targeting (crop/country/soil) excluded this block
      * ``error``    — the walk hit a malformed node
    """

    tree_id: UUID
    code: str
    name_en: str | None = None
    name_ar: str | None = None
    version: int | None = None
    scope: str = "block"
    status: str
    steps: list[ExplainStep] = Field(default_factory=list)
    # The status code the leaf resolved to, for every walk that reached one.
    # `clear` used to be the whole answer for a tree that found nothing,
    # which read the same as a tree nobody had run.
    status_code: StatusCode | None = None
    # The walk as prose, composed by `recommendations.narrative` — the same
    # module the Farm Health card reads, so the dock and that card cannot
    # describe one block two ways. Empty for a skipped tree and for a walk
    # that errored before reaching a leaf.
    narrative_en: str = ""
    narrative_ar: str = ""
    kind: str | None = None
    action_type: str | None = None
    severity: str | None = None
    confidence: float | None = None
    text_en: str | None = None
    text_ar: str | None = None
    error: str | None = None
    # Populated only when ``status == 'skipped'``: which targeting axis
    # rejected the tree ('crop' | 'country' | 'soil'), what the tree demanded,
    # and what the block (or its farm, for country) actually had. ``None``
    # actual = the value is unset, which is the usual cause and was previously
    # indistinguishable from a genuine mismatch.
    skip_axis: str | None = None
    skip_required: list[str] = Field(default_factory=list)
    skip_actual: str | None = None


class ExplainBlockResponse(BaseModel):
    """GET /api/v1/blocks/{block_id}/decision-trees:explain response."""

    block_id: UUID
    evaluated_at: datetime
    crop_path: str | None = None
    trees: list[ExplainTree] = Field(default_factory=list)


# =====================================================================
# Decision-tree authoring (PlatformAdmin)
# =====================================================================


class DecisionTreeVersionResponse(BaseModel):
    """One row from `public.decision_tree_versions`. Includes both raw
    YAML and compiled JSON so the editor can round-trip without
    re-compiling."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tree_id: UUID
    version: int
    tree_yaml: str
    tree_compiled: dict[str, Any]
    compiled_hash: str
    published_at: datetime | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class DecisionTreeDetailResponse(BaseModel):
    """Tree metadata + all versions. Drives the editor's version-history
    panel and the diff view."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    # NULL = platform-shipped; non-NULL = caller's own tenant (PR-A).
    tenant_id: UUID | None = None
    name_en: str
    name_ar: str | None
    description_en: str | None
    description_ar: str | None
    crop_id: UUID | None
    # Multi-axis targeting sets (PR-2). Empty set on an axis = matches any.
    crop_paths: list[str] = Field(default_factory=list)
    country_codes: list[str] = Field(default_factory=list)
    soil_textures: list[str] = Field(default_factory=list)
    scope: str = "block"
    applicable_regions: list[str]
    is_active: bool
    current_version: int | None
    versions: list[DecisionTreeVersionResponse]


class DecisionTreeCreateRequest(BaseModel):
    """POST /api/v1/decision-trees — create a new tree with a first
    draft version. The compiled body comes in as `tree_compiled`; the
    server validates it via `compile_tree` (same path the YAML loader
    uses) and stores the raw author-supplied YAML alongside for the
    editor to round-trip."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    crop_code: str | None = None
    # Multi-axis targeting (PR-5). When provided, these are injected into the
    # YAML spec before compilation (so the structured pickers don't have to
    # edit the YAML body). None = leave whatever the YAML declares.
    crop_paths: list[str] | None = None
    country_codes: list[str] | None = None
    soil_textures: list[str] | None = None
    # Execution granularity (PR-C1): 'block' (default) or 'cell'.
    scope: Literal["block", "cell"] | None = None
    tree_yaml: str = Field(min_length=1)


class DecisionTreeUpdateRequest(BaseModel):
    """PATCH /api/v1/decision-trees/{code} — update editable tree-level
    metadata (name, description, multi-axis targeting, execution scope)
    without appending a structural version. The node structure is edited
    separately through the versions endpoint; this keeps the metadata
    panel in the authoring UI a direct, full-replace form."""

    model_config = ConfigDict(extra="forbid")

    name_en: str = Field(min_length=1, max_length=200)
    name_ar: str | None = Field(default=None, max_length=200)
    description_en: str | None = Field(default=None, max_length=4000)
    description_ar: str | None = Field(default=None, max_length=4000)
    # Crop targeting is required — every tree declares at least one crop
    # path. Country + soil sets may be empty (empty = "matches any" on
    # that axis), matching the create-time semantics.
    crop_paths: list[str] = Field(min_length=1)
    country_codes: list[str] = Field(default_factory=list)
    soil_textures: list[str] = Field(default_factory=list)
    scope: Literal["block", "cell"] = "block"


class DecisionTreeVersionCreateRequest(BaseModel):
    """POST /api/v1/decision-trees/{code}/versions — append a new
    draft version to an existing tree."""

    model_config = ConfigDict(extra="forbid")

    tree_yaml: str = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=500)


class DecisionTreeVersionPublishResponse(BaseModel):
    """POST /api/v1/decision-trees/{code}/versions/{version}:publish."""

    code: str
    version: int
    published_at: datetime


class DecisionTreeDryRunRequest(BaseModel):
    """POST /api/v1/decision-trees/{code}:dry-run — evaluate a draft
    against a real block without writing a recommendation row."""

    model_config = ConfigDict(extra="forbid")

    block_id: UUID
    # Either evaluate the persisted version OR an unsaved YAML body
    # (so the editor can test before saving).
    version: int | None = None
    tree_yaml: str | None = None


class DryRunCandidateBlock(BaseModel):
    """One block the tree would target — drives the dry-run block picker."""

    block_id: UUID
    # "Farm / Block" display label (block name, or code when unnamed).
    label: str
    # The same label from the Arabic columns, each part falling back on its
    # own. NULL only when neither part has an Arabic name.
    label_ar: str | None = None


class DryRunCell(BaseModel):
    """One grid cell's verdict in a ``scope: cell`` dry-run."""

    cell_id: UUID
    cell_row: int | None = None
    cell_col: int | None = None
    matched: bool
    action_type: str | None = None
    severity: str | None = None
    text_en: str | None = None
    error: str | None = None


class DryRunTargeting(BaseModel):
    """Whether the tree's crop / country / soil filters admit this block.

    Reported, never enforced: the dry-run evaluates regardless so an author
    can see what *would* happen, but a tree the sweep would skip here no
    longer looks like one that runs.
    """

    matched: bool
    axis: str | None = None
    required: list[str] = Field(default_factory=list)
    actual: str | None = None


class DecisionTreeDryRunResponse(BaseModel):
    """Result of a dry-run. Mirrors `EvaluationResult` shape.

    For a ``scope: cell`` tree the top-level ``path`` / ``outcome`` /
    ``evaluation_snapshot`` describe one **representative** cell — the first
    that fired, else the first evaluated — because a cell-scoped tree has no
    single block-level verdict. ``cells`` carries every cell's answer.
    """

    matched: bool
    scope: str = "block"
    targeting: DryRunTargeting | None = None
    outcome: dict[str, Any] | None
    path: list[dict[str, Any]]
    evaluation_snapshot: dict[str, Any]
    error: str | None
    # Zero on a block-scoped run; the block itself is the unit there.
    cells_evaluated: int = 0
    cells_matched: int = 0
    cells: list[DryRunCell] = Field(default_factory=list)


# =====================================================================
# On-demand tree run (authoring)
# =====================================================================


class TreeRunCandidateFarm(BaseModel):
    """One farm the tree targets, with the size of the run it implies.

    ``blocks_targeted`` is the number the tree would actually walk;
    ``blocks_total`` is the farm's active block count. The gap is what a
    targeting filter excluded — shown so an author picking a farm knows
    beforehand that only part of it is in scope.
    """

    farm_id: UUID
    name: str
    name_ar: str | None = None
    blocks_total: int
    blocks_targeted: int


class DecisionTreeRunRequest(BaseModel):
    """POST /api/v1/decision-trees/{code}:run — evaluate the tree's published
    version across one farm and open real recommendations.

    Carries no ``tree_yaml`` counterpart to the dry-run's, on purpose: a
    recommendation records the tree version that produced it, so a run from
    unsaved YAML would leave rows nothing can explain.
    """

    model_config = ConfigDict(extra="forbid")

    farm_id: UUID


class TreeRunBlockResult(BaseModel):
    """What the run did on one block of the farm."""

    block_id: UUID
    label: str
    label_ar: str | None = None
    # 0 when this block's crop / country / soil excluded the tree.
    trees_evaluated: int
    skipped_targeting: bool
    recommendations_opened: int
    # Fired and opened something vs fired and hit the open-recommendation
    # dedup. Separated because "0 opened" alone reads as a failed run.
    fired: int
    deduped: int
    errors: int


class DecisionTreeRunResponse(BaseModel):
    """Result of an on-demand tree run over a farm.

    ``recommendations_opened`` counts rows that reached the Action Center on
    this run. ``deduped`` counts blocks where the tree fired but an open
    recommendation from it already existed — the re-run case, and the reason
    a second click reports zero opened without anything having gone wrong.
    """

    run_id: UUID
    farm_id: UUID
    tree_code: str
    tree_version: int
    scope: str = "block"
    blocks_evaluated: int
    blocks_targeted: int
    recommendations_opened: int
    deduped: int
    cleared: int
    errors: int
    traces_written: int
    blocks: list[TreeRunBlockResult] = Field(default_factory=list)


# =====================================================================
# Evaluation lineage (tenant 0062)
# =====================================================================


class EvalRunResponse(BaseModel):
    """One recorded evaluation pass.

    ``kind='sweep'`` is the nightly Beat run over every block;
    ``'on_demand'`` is a single block evaluated through the API. Dry-runs
    never produce a run — they write nothing.
    """

    id: UUID
    kind: str
    actor_user_id: UUID | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    blocks_evaluated: int
    trees_evaluated: int
    trees_skipped: int
    recommendations_opened: int
    alerts_opened: int
    traces_written: int
    outcome: str
    error: str | None = None


class EvalTraceResponse(BaseModel):
    """One (tree x block[/cell]) verdict from a run — list view.

    Deliberately without ``node_path`` / ``resolved_values``: a page of full
    walks is megabytes the list never renders. Fetch one trace by id for those.

    ``status``:
      * ``fired``   — reached a leaf that opens a recommendation/alert
      * ``clear``   — evaluated to no_action
      * ``skipped`` — targeting excluded it; ``skip_axis`` says which axis
      * ``error``   — the walk hit a malformed node
    """

    id: UUID
    run_id: UUID
    evaluated_at: datetime
    farm_id: UUID
    block_id: UUID
    block_name: str | None = None
    block_name_ar: str | None = None
    cell_id: UUID | None = None
    cell_row: int | None = None
    cell_col: int | None = None
    tree_id: UUID
    tree_code: str
    tree_version: int
    scope: str
    status: str
    skip_axis: str | None = None
    # {"required": [...], "actual": "..."} — `actual: null` means the block or
    # its farm has no value on that axis at all.
    skip_detail: dict[str, Any] | None = None
    outcome: dict[str, Any] | None = None
    recommendation_id: UUID | None = None
    alert_id: UUID | None = None
    duration_ms: int | None = None
    error: str | None = None


class EvalTraceDetailResponse(EvalTraceResponse):
    """One trace with the walk attached — the drill-down payload.

    ``resolved_values`` is empty on a ``clear`` row by design: the walk is
    kept, the value dump is not (see tenant migration 0062).
    """

    node_path: list[dict[str, Any]] = Field(default_factory=list)
    resolved_values: dict[str, Any] = Field(default_factory=dict)
    param_overrides: dict[str, Any] = Field(default_factory=dict)


# =====================================================================
# Tree parameter overrides (PR-C)
# =====================================================================


class TreeParameterDeclaration(BaseModel):
    """One declared parameter from a tree's current published version.

    The settings UI renders one form row per declaration, prefilling
    with the current override value (if any), otherwise the declared
    default.
    """

    type: str
    default: Any
    description: str | None = None
    min: float | None = None
    max: float | None = None
    values: list[Any] | None = None  # only set for enum types


class TreeParameterOverridesResponse(BaseModel):
    """GET /api/v1/decision-trees/{code}/parameter-overrides response.

    Bundles the declared shape AND the current override values so the
    UI renders from a single payload.
    """

    code: str
    tree_id: UUID
    declarations: dict[str, TreeParameterDeclaration]
    overrides: dict[str, Any]


class TreeParameterOverrideUpsertRequest(BaseModel):
    """PUT /api/v1/decision-trees/{code}/parameter-overrides/{param_name}.

    ``value`` is intentionally permissive at the schema layer; the
    service coerces against the declared type and returns 400 on
    mismatch / range violation.
    """

    model_config = ConfigDict(extra="forbid")

    value: Any


class TreeParameterOverrideResponse(BaseModel):
    code: str
    param_name: str
    value: Any


class FarmTreeSelectionRow(BaseModel):
    """One tree, and whether this farm runs it (tenant migration 0089)."""

    tree_id: UUID
    code: str
    name_en: str
    name_ar: str | None = None
    scope: str
    version: int
    #: ``platform`` for a tree from the shipped catalog, ``tenant`` for one
    #: this tenant authored. A farm can turn off either.
    source: Literal["platform", "tenant"]
    crop_paths: list[str] = Field(default_factory=list)
    enabled: bool


class FarmTreeSelectionResponse(BaseModel):
    farm_id: UUID
    trees: list[FarmTreeSelectionRow]


class FarmTreeToggleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class FarmTreeToggleResponse(BaseModel):
    tree_id: UUID
    code: str
    enabled: bool
    #: False when the tree was already in the requested state. The call still
    #: succeeds; nothing was written and nothing was audited.
    changed: bool
