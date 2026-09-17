/**
 * The combinations tab.
 *
 * The table's rows are the finding sets this tree can actually produce, walked
 * out of the graph, not a list of the rules an author happened to write. That
 * is the difference that matters: a rule matches a set EXACTLY, so most real
 * cells compose, and an author who only sees their own rules never learns
 * which sets they left to compose.
 *
 * Each row says which it is — Rule or Composes — and shows the text either
 * way, so the composed sentence is read before it reaches a grower rather
 * than after.
 *
 * Codes are picked from the tree's `registers` list. There is no text box: a
 * typed code that nothing registers is a rule that never fires, and it reads
 * as working copy rather than as a mistake.
 */

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Field } from "@/components/Field";
import { Modal } from "@/components/Modal";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";
import type { Finding } from "@/api/decisionTreesBeta";

import {
  ACTION_TYPES,
  FINDING_STATUSES,
  findingSetKey,
  type ActionType,
  type FindingSeverity,
  type FindingStatus,
} from "../lib/betaConstants";
import { enumerateFindingSets, foldFindings, foldCatalogueOf, orphanRules } from "../lib/betaFold";
import type { BetaTreeDoc, CombinationRule } from "../lib/betaTree";
import { useFindingStatusLabel } from "../lib/useStatusLabel";

const INPUT_CLASS = "w-full rounded-lg border border-ap-line px-2.5 py-1.5 text-sm text-ap-ink";

interface CombinationsTabProps {
  doc: BetaTreeDoc | null;
  /** The tree's declared `registers`. Codes are picked from here. */
  declaredCodes: readonly string[];
  /** Severity per code, read off the register nodes. */
  severityByCode: ReadonlyMap<string, FindingSeverity>;
  findings: readonly Finding[];
  rules: readonly CombinationRule[];
  readOnly?: boolean;
  onChangeRules: (rules: CombinationRule[]) => void;
}

export function CombinationsTab({
  doc,
  declaredCodes,
  severityByCode,
  findings,
  rules,
  readOnly = false,
  onChangeRules,
}: CombinationsTabProps): JSX.Element {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const statusLabel = useFindingStatusLabel();
  const [editing, setEditing] = useState<{ index: number | null } | null>(null);

  const catalogue = useMemo(() => foldCatalogueOf(findings), [findings]);
  const enumerated = useMemo(() => enumerateFindingSets(doc), [doc]);
  const orphans = useMemo(() => orphanRules(rules, enumerated.sets), [rules, enumerated.sets]);

  const ruleIndexByKey = useMemo(() => {
    const map = new Map<string, number>();
    rules.forEach((r, i) => {
      const key = findingSetKey(r.codes);
      if (!map.has(key)) map.set(key, i);
    });
    return map;
  }, [rules]);

  const isAr = i18n.language === "ar";

  return (
    <div className="flex flex-col gap-4">
      <Card
        title={t("combinations.title")}
        actions={
          !readOnly ? (
            <Button size="sm" onClick={() => setEditing({ index: null })}>
              {t("combinations.addRule")}
            </Button>
          ) : null
        }
        bodyClassName="flex flex-col gap-3"
      >
        <p className="text-sm text-ap-muted">{t("combinations.subtitle")}</p>
        {enumerated.truncated ? (
          <StatusBanner kind="warn">
            {t("combinations.truncated", { count: enumerated.sets.length })}
          </StatusBanner>
        ) : null}

        {enumerated.sets.length === 0 ? (
          <EmptyState message={t("combinations.empty")} />
        ) : (
          <Table>
            <caption className="sr-only">{t("combinations.title")}</caption>
            <Thead>
              <Tr className="border-b border-ap-line text-start text-meta uppercase text-ap-muted">
                <Th className="px-2 py-2 text-start">{t("combinations.columns.set")}</Th>
                <Th className="px-2 py-2 text-start">{t("combinations.columns.source")}</Th>
                <Th className="px-2 py-2 text-start">{t("combinations.columns.actionType")}</Th>
                <Th className="px-2 py-2 text-start">{t("combinations.columns.status")}</Th>
                <Th className="px-2 py-2 text-start">{t("combinations.columns.textEn")}</Th>
                <Th className="px-2 py-2 text-start">{t("combinations.columns.textAr")}</Th>
                <Th className="px-2 py-2" />
              </Tr>
            </Thead>
            <Tbody>
              {enumerated.sets.map((set) => {
                const card = foldFindings(set.codes, rules, {
                  findings: catalogue,
                  severityByCode,
                });
                const ruleIndex = ruleIndexByKey.get(set.key);
                return (
                  <Tr key={set.key || "empty-set"} className="align-top">
                    <Td className="px-2 py-2">
                      {set.codes.length === 0 ? (
                        <span className="text-ap-muted">{t("combinations.emptySet")}</span>
                      ) : (
                        <span dir="ltr" className="flex flex-wrap gap-1 font-mono text-xs">
                          {set.codes.map((c) => (
                            <span
                              key={c}
                              className="rounded bg-ap-line/60 px-1.5 py-0.5 text-ap-ink"
                            >
                              {c}
                            </span>
                          ))}
                        </span>
                      )}
                    </Td>
                    <Td className="px-2 py-2">
                      {set.hasRule ? (
                        <Pill kind="ok">{t("combinations.hasRule")}</Pill>
                      ) : (
                        <Pill kind="neutral">{t("combinations.composes")}</Pill>
                      )}
                    </Td>
                    <Td className="px-2 py-2">
                      {card.action_type
                        ? t(`actionType.${card.action_type}`)
                        : t("actionType.unset")}
                    </Td>
                    <Td className="px-2 py-2">{statusLabel(card.status)}</Td>
                    <Td dir="ltr" className="px-2 py-2 text-ap-ink">
                      {card.text_en || "—"}
                    </Td>
                    <Td dir="rtl" className="px-2 py-2 text-ap-ink">
                      {card.text_ar || "—"}
                    </Td>
                    <Td className="px-2 py-2 text-end">
                      {readOnly || set.codes.length === 0 ? null : ruleIndex !== undefined ? (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => setEditing({ index: ruleIndex })}
                        >
                          {t("combinations.editRule")}
                        </Button>
                      ) : (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => {
                            onChangeRules([
                              ...rules,
                              {
                                codes: set.codes,
                                action_type: card.action_type ?? "scout",
                                status: card.status,
                                text_en: card.text_en,
                                text_ar: card.text_ar,
                              },
                            ]);
                            setEditing({ index: rules.length });
                          }}
                        >
                          {t("combinations.addRule")}
                        </Button>
                      )}
                    </Td>
                  </Tr>
                );
              })}
            </Tbody>
          </Table>
        )}
        <p className="text-meta text-ap-muted">{t("combinations.composesHelp")}</p>
      </Card>

      {orphans.length > 0 ? (
        <Card title={t("combinations.orphanTitle")} bodyClassName="flex flex-col gap-2">
          <p className="text-sm text-ap-muted">{t("combinations.orphanHelp")}</p>
          <ul className="flex flex-col gap-1">
            {orphans.map((rule) => (
              <li key={findingSetKey(rule.codes)} className="flex items-center gap-2 text-sm">
                <span dir="ltr" className="font-mono text-xs">
                  {rule.codes.join(" + ")}
                </span>
                <span className="text-ap-muted">{isAr ? rule.text_ar : rule.text_en}</span>
                {!readOnly ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    className="ms-auto"
                    onClick={() =>
                      onChangeRules(
                        rules.filter((r) => findingSetKey(r.codes) !== findingSetKey(rule.codes)),
                      )
                    }
                  >
                    {t("combinations.removeRule")}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {editing ? (
        <RuleForm
          rule={editing.index === null ? null : rules[editing.index]}
          declaredCodes={declaredCodes}
          findings={findings}
          otherKeys={rules.filter((_, i) => i !== editing.index).map((r) => findingSetKey(r.codes))}
          onCancel={() => setEditing(null)}
          onSave={(next) => {
            if (editing.index === null) onChangeRules([...rules, next]);
            else onChangeRules(rules.map((r, i) => (i === editing.index ? next : r)));
            setEditing(null);
          }}
          onRemove={
            editing.index === null
              ? undefined
              : () => {
                  onChangeRules(rules.filter((_, i) => i !== editing.index));
                  setEditing(null);
                }
          }
        />
      ) : null}
    </div>
  );
}

// ---- The rule form ----------------------------------------------------

function RuleForm({
  rule,
  declaredCodes,
  findings,
  otherKeys,
  onCancel,
  onSave,
  onRemove,
}: {
  rule: CombinationRule | null;
  declaredCodes: readonly string[];
  findings: readonly Finding[];
  otherKeys: readonly string[];
  onCancel: () => void;
  onSave: (rule: CombinationRule) => void;
  onRemove?: () => void;
}): JSX.Element {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const statusLabel = useFindingStatusLabel();
  const [codes, setCodes] = useState<string[]>(rule?.codes ?? []);
  const [actionType, setActionType] = useState<ActionType>(rule?.action_type ?? "scout");
  const [status, setStatus] = useState<FindingStatus>(rule?.status ?? "issue");
  const [textEn, setTextEn] = useState(rule?.text_en ?? "");
  const [textAr, setTextAr] = useState(rule?.text_ar ?? "");

  const duplicate = codes.length > 0 && otherKeys.includes(findingSetKey(codes));
  const invalid = codes.length === 0 || duplicate;

  const toggle = (code: string): void =>
    setCodes((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code].sort(),
    );

  return (
    <Modal open onClose={onCancel} labelledBy="beta-rule-form-title" className="max-w-2xl">
      <div className="flex flex-col gap-4 p-4">
        <h2 id="beta-rule-form-title" className="text-card-title font-semibold text-ap-ink">
          {t("combinations.form.title")}
        </h2>

        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm font-medium text-ap-ink">
            {t("combinations.form.codes")}
          </legend>
          <p className="text-meta text-ap-muted">{t("combinations.form.codesHelp")}</p>
          <div className="flex flex-wrap gap-2">
            {declaredCodes.map((code) => {
              const finding = findings.find((f) => f.code === code && !f.shadowed);
              const on = codes.includes(code);
              return (
                <label
                  key={code}
                  className={`flex cursor-pointer items-center gap-2 rounded-lg border px-2.5 py-1.5 text-sm ${
                    on ? "border-ap-primary bg-ap-primary-soft" : "border-ap-line"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => toggle(code)}
                    className="h-3.5 w-3.5"
                  />
                  <span dir="ltr" className="font-mono text-xs">
                    {code}
                  </span>
                  <span className="text-ap-muted">
                    {finding ? (i18n.language === "ar" ? finding.name_ar : finding.name_en) : null}
                  </span>
                </label>
              );
            })}
          </div>
          {codes.length === 0 ? (
            <p className="text-sm text-ap-crit">{t("combinations.form.noCodes")}</p>
          ) : null}
          {duplicate ? (
            <p className="text-sm text-ap-crit">{t("combinations.form.duplicate")}</p>
          ) : null}
        </fieldset>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("combinations.form.actionType")}>
            {(props) => (
              <select
                {...props}
                value={actionType}
                onChange={(e) => setActionType(e.target.value as ActionType)}
                className={INPUT_CLASS}
              >
                {ACTION_TYPES.map((a) => (
                  <option key={a} value={a}>
                    {t(`actionType.${a}`)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={t("combinations.form.status")}>
            {(props) => (
              <select
                {...props}
                value={status}
                onChange={(e) => setStatus(e.target.value as FindingStatus)}
                className={INPUT_CLASS}
              >
                {FINDING_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {statusLabel(s)}
                  </option>
                ))}
              </select>
            )}
          </Field>
        </div>

        <Field label={t("combinations.form.textEn")}>
          {(props) => (
            <textarea
              {...props}
              dir="ltr"
              rows={3}
              value={textEn}
              onChange={(e) => setTextEn(e.target.value)}
              className={INPUT_CLASS}
            />
          )}
        </Field>
        <Field label={t("combinations.form.textAr")}>
          {(props) => (
            <textarea
              {...props}
              dir="rtl"
              rows={3}
              value={textAr}
              onChange={(e) => setTextAr(e.target.value)}
              className={INPUT_CLASS}
            />
          )}
        </Field>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            onClick={() =>
              onSave({
                codes: [...codes].sort(),
                action_type: actionType,
                status,
                text_en: textEn,
                text_ar: textAr,
              })
            }
            disabled={invalid}
          >
            {t("combinations.form.save")}
          </Button>
          <Button variant="secondary" onClick={onCancel}>
            {t("combinations.form.cancel")}
          </Button>
          {onRemove ? (
            <Button variant="danger" className="ms-auto" onClick={onRemove}>
              {t("combinations.removeRule")}
            </Button>
          ) : null}
        </div>
      </div>
    </Modal>
  );
}
