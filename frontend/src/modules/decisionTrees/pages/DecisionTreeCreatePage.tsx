import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate } from "react-router-dom";

import { useCreateDecisionTree } from "@/queries/decisionTrees";
import { useCapability } from "@/rbac/useCapability";

const STARTER_YAML = `code: my_tree_v1
name_en: My new tree
name_ar: شجرتي الجديدة
description_en: One-paragraph what + why.
description_ar: ...

crop_code: null
applicable_regions: []

root: root
nodes:
  root:
    label_en: Decision question
    condition:
      tree:
        op: lt
        left: { source: indices, index_code: ndvi, key: baseline_deviation }
        right: -0.5
    on_match: leaf_action
    on_miss:  leaf_no_action

  leaf_action:
    label_en: Suggested action
    outcome:
      action_type: scout
      severity: warning
      confidence: 0.7
      valid_for_hours: 72
      parameters:
        priority: medium
      text_en: Schedule a scouting visit.
      text_ar: حدِّد زيارة فحص.

  leaf_no_action:
    outcome:
      action_type: no_action
      severity: info
      confidence: 0.9
      text_en: No action.
      text_ar: لا إجراء.
`;

export function DecisionTreeCreatePage(): ReactNode {
  const navigate = useNavigate();
  const { t } = useTranslation("decisionTrees");
  const canManage = useCapability("decision_tree.manage");

  const [code, setCode] = useState("");
  const [cropCode, setCropCode] = useState("");
  const [yamlBody, setYamlBody] = useState(STARTER_YAML);

  const create = useCreateDecisionTree();

  if (!canManage) {
    return <Navigate to="/settings/decision-trees" replace />;
  }

  const submit = (event: React.FormEvent): void => {
    event.preventDefault();
    create.mutate(
      {
        code: code.trim(),
        crop_code: cropCode.trim() || null,
        tree_yaml: yamlBody,
      },
      {
        onSuccess: (tree) => {
          navigate(`/settings/decision-trees/${tree.code}`);
        },
      },
    );
  };

  return (
    <form onSubmit={submit} className="mx-auto flex max-w-5xl flex-col gap-4">
      <header>
        <h1 className="text-2xl font-semibold text-ap-ink">{t("create.title")}</h1>
        <p className="mt-1 text-sm text-ap-muted">{t("create.subtitle")}</p>
      </header>

      <section className="grid grid-cols-1 gap-3 rounded-xl border border-ap-line bg-ap-panel p-4 sm:grid-cols-2">
        <Field label={t("create.fields.code")} hint={t("create.fields.codeHint")}>
          <input
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder={t("create.fields.codePlaceholder")}
            pattern="^[a-z0-9][a-z0-9_-]*$"
            className={inputCls}
          />
        </Field>
        <Field label={t("create.fields.cropCode")} hint={t("create.fields.cropCodeHint")}>
          <input
            value={cropCode}
            onChange={(e) => setCropCode(e.target.value)}
            placeholder="citrus"
            className={inputCls}
          />
        </Field>
      </section>

      <section className="flex flex-col gap-2 rounded-xl border border-ap-line bg-ap-panel p-4">
        <div>
          <h2 className="text-sm font-semibold text-ap-ink">{t("create.fields.yaml")}</h2>
          <p className="text-xs text-ap-muted">{t("create.fields.yamlHint")}</p>
        </div>
        <textarea
          value={yamlBody}
          onChange={(e) => setYamlBody(e.target.value)}
          rows={28}
          spellCheck={false}
          className="w-full rounded-md border border-ap-line bg-ap-bg/40 px-3 py-2 font-mono text-xs text-ap-ink shadow-inner focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
        />
      </section>

      <footer className="flex flex-wrap items-center justify-end gap-2">
        {create.isError ? (
          <span className="text-xs text-ap-crit">
            {create.error?.message ?? t("create.saveFailed")}
          </span>
        ) : null}
        <button
          type="button"
          onClick={() => navigate("/settings/decision-trees")}
          className="rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-sm font-medium text-ap-ink hover:bg-ap-line/40"
        >
          {t("create.cancel")}
        </button>
        <button
          type="submit"
          disabled={create.isPending || !code.trim() || !yamlBody.trim()}
          className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
        >
          {create.isPending ? t("create.saving") : t("create.save")}
        </button>
      </footer>
    </form>
  );
}

const inputCls =
  "w-full rounded-md border border-ap-line bg-white px-2 py-1 text-sm text-ap-ink shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}): ReactNode {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ap-muted">{label}</span>
      {children}
      {hint ? <span className="text-[11px] text-ap-muted">{hint}</span> : null}
    </label>
  );
}
