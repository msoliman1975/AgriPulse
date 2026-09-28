/**
 * How a block's health class is built from its grid cells, for one tenant.
 *
 * Two tenant settings keys (public migration 0094), shown as one choice
 * rather than as two raw keys: `health.cell_rollup` picks the rule and
 * `health.cell_share_pct` is read only by the `share` rule. The server checks
 * both against `app/shared/settings/constraints.py`, so this form mirrors
 * those bounds and does not add its own.
 */

import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { ResolvedSetting } from "@/api/integrations";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { StatusBanner } from "@/components/StatusBanner";
import { SourcePill } from "@/modules/settings/components/SourcePill";

export const CELL_ROLLUP_KEY = "health.cell_rollup";
export const CELL_SHARE_KEY = "health.cell_share_pct";

const RULES = ["worst", "share", "most_common"] as const;
type Rule = (typeof RULES)[number];

function asRule(value: unknown): Rule {
  return RULES.includes(value as Rule) ? (value as Rule) : "worst";
}

function asPct(value: unknown): string {
  return typeof value === "number" ? String(value) : "20";
}

interface Props {
  rollup: ResolvedSetting;
  share: ResolvedSetting | undefined;
  onSave: (key: string, value: unknown) => Promise<unknown>;
}

export function CellRollupCard({ rollup, share, onSave }: Props): ReactNode {
  const { t } = useTranslation("integrations");
  const [rule, setRule] = useState<Rule>(() => asRule(rollup.value));
  const [pct, setPct] = useState(() => asPct(share?.value));
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<"saved" | "failed" | null>(null);

  useEffect(() => setRule(asRule(rollup.value)), [rollup.value]);
  useEffect(() => setPct(asPct(share?.value)), [share?.value]);

  const pctNumber = Number(pct);
  const pctValid = /^\d+$/.test(pct) && pctNumber >= 1 && pctNumber <= 100;
  const ruleChanged = rule !== asRule(rollup.value);
  const pctChanged = rule === "share" && share !== undefined && pct !== asPct(share.value);
  const canSave = (ruleChanged || pctChanged) && (rule !== "share" || pctValid) && !saving;

  const onSubmit = async (): Promise<void> => {
    setSaving(true);
    setResult(null);
    try {
      // The share first: a tenant switching to `share` should never have a
      // moment where the rule is on and the percent is the old one.
      if (pctChanged) await onSave(CELL_SHARE_KEY, pctNumber);
      if (ruleChanged) await onSave(CELL_ROLLUP_KEY, rule);
      setResult("saved");
    } catch {
      setResult("failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card noPadding className="flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-ap-ink">{t("cellRollup.title")}</h2>
        <SourcePill source={rollup.source} />
      </div>
      <p className="text-sm text-ap-muted">{t("cellRollup.help")}</p>

      <fieldset className="flex flex-col gap-2">
        <legend className="sr-only">{t("cellRollup.title")}</legend>
        {RULES.map((option) => (
          <div key={option} className="flex flex-col">
            <label className="flex items-center gap-2 text-sm font-medium text-ap-ink">
              <input
                type="radio"
                name="cell-rollup"
                value={option}
                checked={rule === option}
                onChange={() => setRule(option)}
                aria-describedby={`cell-rollup-help-${option}`}
              />
              {t(`cellRollup.rule.${option}`)}
            </label>
            <p id={`cell-rollup-help-${option}`} className="ps-6 text-xs text-ap-muted">
              {t(`cellRollup.ruleHelp.${option}`)}
            </p>
          </div>
        ))}
      </fieldset>

      {rule === "share" ? (
        <label className="flex flex-wrap items-center gap-2 text-sm text-ap-ink">
          {t("cellRollup.shareLabel")}
          <input
            type="number"
            min={1}
            max={100}
            step={1}
            dir="ltr"
            value={pct}
            onChange={(e) => setPct(e.target.value)}
            aria-invalid={!pctValid}
            className="w-24 rounded-md border border-ap-line bg-white px-2 py-1 text-sm"
          />
          {!pctValid ? (
            <span className="text-xs text-ap-crit">{t("cellRollup.shareError")}</span>
          ) : null}
        </label>
      ) : null}

      {result === "saved" ? <StatusBanner kind="info">{t("cellRollup.saved")}</StatusBanner> : null}
      {result === "failed" ? (
        <StatusBanner kind="crit">{t("cellRollup.failed")}</StatusBanner>
      ) : null}

      <div>
        <Button onClick={() => void onSubmit()} disabled={!canSave}>
          {t("save")}
        </Button>
      </div>
    </Card>
  );
}
