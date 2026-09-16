import { describe, expect, it } from "vitest";

import {
  enumerateFindingSets,
  foldCatalogueOf,
  foldFindings,
  joinClauses,
  orphanRules,
  type FoldFinding,
} from "./betaFold";
import { parseBetaDoc, type CombinationRule } from "./betaTree";
import type { FindingSeverity } from "./betaConstants";

const CATALOGUE = new Map<string, FoldFinding>([
  [
    "dry",
    {
      code: "dry",
      clause_en: "leaf water is low",
      clause_ar: "ماء الورقة منخفض",
      name_en: "Low leaf water",
      name_ar: "انخفاض ماء الورقة",
      default_status: "stressed",
      source: "platform",
    },
  ],
  [
    "ndvi_low",
    {
      code: "ndvi_low",
      clause_en: "canopy vigour dropped",
      clause_ar: "انخفضت حيوية المجموع الخضري",
      name_en: "Canopy vigour dropped",
      name_ar: "انخفاض الحيوية",
      default_status: "watch",
      source: "platform",
    },
  ],
  [
    "pest_high",
    {
      code: "pest_high",
      clause_en: "anthracnose pressure is high",
      clause_ar: "ضغط الأنثراكنوز مرتفع",
      name_en: "Pest pressure high",
      name_ar: "ضغط آفات مرتفع",
      default_status: "stressed",
      source: "platform",
    },
  ],
]);

const SEVERITY = new Map<string, FindingSeverity>([
  ["dry", "warning"],
  ["ndvi_low", "info"],
  ["pest_high", "critical"],
]);

const RULE: CombinationRule = {
  codes: ["dry", "ndvi_low"],
  action_type: "irrigate",
  status: "stressed",
  text_en: "Water shortage is the cause. Irrigate before treating anything else.",
  text_ar: "نقص المياه هو السبب. اسقِ قبل معالجة أي شيء آخر.",
};

const ctx = { findings: CATALOGUE, severityByCode: SEVERITY };

describe("foldFindings", () => {
  it("takes the rule's text when the set matches exactly", () => {
    const card = foldFindings(["ndvi_low", "dry"], [RULE], ctx);
    expect(card.matched_rule).toBe(RULE);
    expect(card.text_en).toBe(RULE.text_en);
    expect(card.action_type).toBe("irrigate");
    expect(card.status).toBe("stressed");
  });

  it("composes when a third finding joins, because matching is exact", () => {
    // This is the main path, not a fallback: a third finding is common.
    const card = foldFindings(["dry", "ndvi_low", "pest_high"], [RULE], ctx);
    expect(card.matched_rule).toBeNull();
    expect(card.text_en).toBe(
      "anthracnose pressure is high, leaf water is low and canopy vigour dropped",
    );
  });

  it("orders the composed clauses by severity, highest first", () => {
    const card = foldFindings(["ndvi_low", "pest_high"], [], ctx);
    expect(card.text_en.startsWith("anthracnose pressure is high")).toBe(true);
    expect(card.severity).toBe("critical");
  });

  it("takes the worst default status when nothing overrides it", () => {
    expect(foldFindings(["ndvi_low"], [], ctx).status).toBe("watch");
    expect(foldFindings(["ndvi_low", "dry"], [], ctx).status).toBe("stressed");
  });

  it("produces nothing for an empty set", () => {
    const card = foldFindings([], [RULE], ctx);
    expect(card.finding_set).toEqual([]);
    expect(card.text_en).toBe("");
    expect(card.status).toBe("normal");
    expect(card.severity).toBeNull();
  });

  it("names codes no catalogue resolves instead of dropping them silently", () => {
    const card = foldFindings(["dry", "mystery"], [], ctx);
    expect(card.unresolved).toEqual(["mystery"]);
    expect(card.text_en).toBe("leaf water is low");
  });
});

describe("joinClauses", () => {
  it("joins English with a comma and 'and'", () => {
    expect(joinClauses(["a", "b", "c"], "en")).toBe("a, b and c");
    expect(joinClauses(["a"], "en")).toBe("a");
    expect(joinClauses([], "en")).toBe("");
  });

  it("joins Arabic with the Arabic comma and a leading waw on the last item", () => {
    expect(joinClauses(["أ", "ب", "ج"], "ar")).toBe("أ، ب وج");
  });
});

describe("enumerateFindingSets", () => {
  const YAML = `registers: [dry, pest_high]
combinations:
  - codes: [dry]
    action_type: irrigate
    status: stressed
    text_en: x
    text_ar: س
root: cond_1
nodes:
  cond_1:
    condition: { tree: { op: lt, left: { source: indices, index_code: ndmi, key: mean }, right: 0 } }
    on_match: reg_dry
    on_miss: sw_1
  reg_dry:
    register: { code: dry, severity: warning }
    next: sw_1
  sw_1:
    switch:
      on: { source: weather_risk, risk_code: anthracnose, field: score }
      cases: [{ op: ge, value: 70, go: reg_pest }]
      default: stop_1
  reg_pest:
    register: { code: pest_high, severity: critical }
    next: stop_1
  stop_1:
    stop: true
`;

  it("walks out every set the graph can produce, including the empty one", () => {
    const { sets, truncated } = enumerateFindingSets(parseBetaDoc(YAML));
    expect(truncated).toBe(false);
    expect(sets.map((s) => s.key)).toEqual(["", "dry", "pest_high", "dry+pest_high"]);
  });

  it("marks which sets a rule matches exactly", () => {
    const { sets } = enumerateFindingSets(parseBetaDoc(YAML));
    expect(sets.filter((s) => s.hasRule).map((s) => s.key)).toEqual(["dry"]);
  });

  it("terminates on a cycle instead of walking for ever", () => {
    const cyclic = parseBetaDoc(`root: a
nodes:
  a: { register: { code: x, severity: info }, next: b }
  b: { register: { code: x, severity: info }, next: a }
`);
    expect(enumerateFindingSets(cyclic).sets).toEqual([]);
  });

  it("says so when it hits its cap rather than presenting a partial list as final", () => {
    const { truncated } = enumerateFindingSets(parseBetaDoc(YAML), { limit: 1 });
    expect(truncated).toBe(true);
  });
});

describe("orphanRules", () => {
  it("flags a rule naming a set the graph cannot produce", () => {
    const sets = [{ codes: ["dry"], key: "dry", hasRule: false }];
    expect(orphanRules([RULE], sets)).toEqual([RULE]);
  });
});

describe("foldCatalogueOf", () => {
  it("lets the platform row win over a tenant row of the same code", () => {
    const merged = foldCatalogueOf([
      {
        code: "dry",
        clause_en: "the leaves are running dry",
        clause_ar: "ت",
        name_en: "Tenant wording",
        name_ar: "ت",
        default_status: "watch",
        source: "tenant",
      },
      {
        code: "dry",
        clause_en: "leaf water is low",
        clause_ar: "ماء الورقة منخفض",
        name_en: "Low leaf water",
        name_ar: "ا",
        default_status: "stressed",
        source: "platform",
      },
    ]);
    expect(merged.get("dry")?.source).toBe("platform");
    expect(merged.get("dry")?.clause_en).toBe("leaf water is low");
  });
});
