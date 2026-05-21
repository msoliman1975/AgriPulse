// Starter templates surfaced on the Create page (PR-D8).
//
// Templates are inert YAML strings the author can pick to seed a new
// tree. The "empty" template is a minimal root + two placeholder
// leaves so backend compile_tree passes; the other templates mirror
// canonical patterns we ship as backend seeds.
//
// `code:` in each template is `REPLACE_ME` so the create flow rewrites
// it with the form's chosen code before posting.
//
// ASCII-only intentionally — non-ASCII characters in template
// literals were causing tsc on Windows to mis-tokenize the file
// (the file is valid UTF-8; the toolchain isn't). Translate any user-
// facing copy through i18n keys; the YAML itself stays ASCII.

import { STARTER_TREE_YAML } from "./treeStructure";

export interface TreeTemplate {
  id: string;
  /** i18n keys live in i18n/locales/en|ar/decisionTrees.json. */
  labelKey: string;
  descKey: string;
  yaml: string;
}

const SCOUT_FOR_STRESS_YAML = `code: REPLACE_ME
name_en: Scout for stress
name_ar: ""
description_en: >-
  When a block's NDVI drops below its own seasonal baseline, queue a
  scouting visit. Critical priority for severe drops; warning priority
  for moderate drops.
description_ar: ""

crop_code: null
applicable_regions: []

root: root
nodes:
  root:
    label_en: Is NDVI below its seasonal baseline?
    condition:
      tree:
        op: lt
        left:
          source: indices
          index_code: ndvi
          key: baseline_deviation
        right: -0.5
    on_match: severity_check
    on_miss: leaf_no_action

  severity_check:
    label_en: Is the drop severe?
    condition:
      tree:
        op: lt
        left:
          source: indices
          index_code: ndvi
          key: baseline_deviation
        right: -1.5
    on_match: leaf_scout_critical
    on_miss: leaf_scout_warning

  leaf_scout_critical:
    label_en: Severe stress - scout within 24h
    outcome:
      action_type: scout
      kind: recommendation
      severity: critical
      confidence: 0.85
      valid_for_hours: 72
      text_en: >-
        Severe NDVI drop. Schedule a field scouting visit within 24
        hours to identify the cause (water, pest, disease, nutrition).
      text_ar: ""

  leaf_scout_warning:
    label_en: Moderate stress - scout within 72h
    outcome:
      action_type: scout
      kind: recommendation
      severity: warning
      confidence: 0.65
      valid_for_hours: 168
      text_en: NDVI is below the historical baseline.
      text_ar: ""

  leaf_no_action:
    label_en: No action - NDVI within baseline
    outcome:
      action_type: no_action
      kind: recommendation
      confidence: 0.9
      text_en: NDVI is within the seasonal baseline; no scouting recommended.
      text_ar: ""
`;

const NDVI_BASELINE_ALERT_YAML = `code: REPLACE_ME
name_en: NDVI baseline alert
name_ar: ""
description_en: >-
  Alert when NDVI falls below its seasonal baseline. Severity tracks
  the magnitude of the drop so an oncall workflow can triage by urgency.
description_ar: ""

crop_code: null
applicable_regions: []

root: root
nodes:
  root:
    label_en: Has NDVI dropped meaningfully?
    condition:
      tree:
        op: lt
        left:
          source: indices
          index_code: ndvi
          key: baseline_deviation
        right: -0.5
    on_match: severity_check
    on_miss: leaf_no_action

  severity_check:
    label_en: Is the drop severe?
    condition:
      tree:
        op: lt
        left:
          source: indices
          index_code: ndvi
          key: baseline_deviation
        right: -1.5
    on_match: leaf_alert_critical
    on_miss: leaf_alert_warning

  leaf_alert_critical:
    label_en: Critical NDVI drop
    outcome:
      action_type: ndvi_drop
      kind: alert
      severity: critical
      text_en: NDVI dropped 1.5+ stdev below baseline - investigate immediately.
      text_ar: ""

  leaf_alert_warning:
    label_en: Warning NDVI drop
    outcome:
      action_type: ndvi_drop
      kind: alert
      severity: warning
      text_en: NDVI dropped between 0.5..1.5 stdev below baseline.
      text_ar: ""

  leaf_no_action:
    label_en: No alert
    outcome:
      action_type: no_action
      kind: recommendation
      confidence: 0.9
      text_en: NDVI within expected range.
      text_ar: ""
`;

const IRRIGATION_DECISION_YAML = `code: REPLACE_ME
name_en: Irrigation decision
name_ar: ""
description_en: >-
  Decide whether to irrigate based on near-term forecast rain. If rain
  is expected, defer irrigation; otherwise schedule it.
description_ar: ""

crop_code: null
applicable_regions: []

root: root
nodes:
  root:
    label_en: Is rain expected in the next 24h?
    condition:
      tree:
        op: gt
        left:
          source: weather
          scope: forecast_24h
          field: precipitation_mm_total
        right: 5
    on_match: leaf_defer
    on_miss: leaf_irrigate

  leaf_defer:
    label_en: Defer - let the rain do the work
    outcome:
      action_type: no_action
      kind: recommendation
      confidence: 0.85
      text_en: Rain 5mm+ expected in the next 24h - skip irrigation.
      text_ar: ""

  leaf_irrigate:
    label_en: Irrigate
    outcome:
      action_type: irrigate
      kind: recommendation
      confidence: 0.75
      text_en: No meaningful rain expected - irrigate this block.
      text_ar: ""
`;

export const TREE_TEMPLATES: TreeTemplate[] = [
  {
    id: "empty",
    labelKey: "create.templates.empty",
    descKey: "create.templates.emptyDesc",
    yaml: STARTER_TREE_YAML,
  },
  {
    id: "scout_for_stress",
    labelKey: "create.templates.scoutStress",
    descKey: "create.templates.scoutStressDesc",
    yaml: SCOUT_FOR_STRESS_YAML,
  },
  {
    id: "ndvi_baseline_alert",
    labelKey: "create.templates.ndviAlert",
    descKey: "create.templates.ndviAlertDesc",
    yaml: NDVI_BASELINE_ALERT_YAML,
  },
  {
    id: "irrigation_decision",
    labelKey: "create.templates.irrigation",
    descKey: "create.templates.irrigationDesc",
    yaml: IRRIGATION_DECISION_YAML,
  },
];

export function getTemplate(id: string): TreeTemplate | undefined {
  return TREE_TEMPLATES.find((t) => t.id === id);
}
