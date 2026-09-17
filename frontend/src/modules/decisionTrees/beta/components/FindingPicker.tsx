/**
 * Pick a finding code from the catalogue, and say which table it came from.
 *
 * The fold resolves the platform table first, then the tenant one (section
 * 6.2). So the source is not decoration: a tenant row with a platform row's
 * code is never read, and an author who picked the tenant wording would be
 * choosing text nobody will see. That row is marked shadowed and cannot be
 * picked.
 */

import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Pill } from "@/components/Pill";
import { localizedField } from "@/lib/localizedField";
import type { Finding } from "@/api/decisionTreesBeta";

import { useFindingStatusLabel } from "../lib/useStatusLabel";

interface FindingPickerProps {
  findings: readonly Finding[];
  value: string;
  onChange: (code: string) => void;
  /** Narrow the list to these codes — the combinations tab picks only from
   *  the tree's declared registers, never from the whole catalogue. */
  limitToCodes?: readonly string[];
  disabled?: boolean;
  id?: string;
  describedBy?: string;
}

export function FindingPicker({
  findings,
  value,
  onChange,
  limitToCodes,
  disabled,
  id,
  describedBy,
}: FindingPickerProps): JSX.Element {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const statusLabel = useFindingStatusLabel();
  const [search, setSearch] = useState("");

  const rows = useMemo(() => {
    const allowed = limitToCodes ? new Set(limitToCodes) : null;
    const q = search.trim().toLowerCase();
    return (
      findings
        // A shadowed row is never read by the fold, so it is never offered.
        .filter((f) => !f.shadowed && f.is_active)
        .filter((f) => (allowed ? allowed.has(f.code) : true))
        .filter(
          (f) =>
            q === "" ||
            f.code.toLowerCase().includes(q) ||
            f.name_en.toLowerCase().includes(q) ||
            f.name_ar.includes(search.trim()),
        )
        .sort((a, b) => a.code.localeCompare(b.code))
    );
  }, [findings, limitToCodes, search]);

  const selected = findings.find((f) => f.code === value) ?? null;

  return (
    <div className="flex flex-col gap-2">
      <input
        type="search"
        value={search}
        disabled={disabled}
        onChange={(e) => setSearch(e.target.value)}
        placeholder={t("findingPicker.search")}
        aria-label={t("findingPicker.search")}
        className="w-full rounded-lg border border-ap-line px-2.5 py-1.5 text-sm text-ap-ink"
      />
      <div className="max-h-56 overflow-y-auto rounded-lg border border-ap-line">
        {rows.length === 0 ? (
          <p className="p-4 text-center text-sm text-ap-muted">
            {findings.length === 0 ? t("findingPicker.empty") : t("findingPicker.noMatch")}
          </p>
        ) : (
          <ul id={id} aria-describedby={describedBy} className="divide-y divide-ap-line">
            {rows.map((f) => (
              <li key={`${f.source}:${f.code}`}>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => onChange(f.code)}
                  aria-pressed={f.code === value}
                  className={`flex w-full flex-col items-start gap-0.5 px-3 py-2 text-start hover:bg-ap-line/40 ${
                    f.code === value ? "bg-ap-primary-soft" : ""
                  }`}
                >
                  <span className="flex w-full flex-wrap items-center gap-2">
                    <span dir="ltr" className="font-mono text-xs font-semibold text-ap-ink">
                      {f.code}
                    </span>
                    <SourcePill source={f.source} />
                    <span className="ms-auto text-meta text-ap-muted">
                      {statusLabel(f.default_status)}
                    </span>
                  </span>
                  <span className="text-sm text-ap-ink">
                    {localizedField(i18n.language, f.name_en, f.name_ar)}
                  </span>
                  <span className="text-meta text-ap-muted">
                    {localizedField(i18n.language, f.clause_en, f.clause_ar)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {selected ? <p className="text-meta text-ap-muted">{t("findingPicker.sourceHelp")}</p> : null}
    </div>
  );
}

/** Which table a code resolved from. Same component on the picker, the node
 *  body and the catalogue screen, so the two words always mean one thing. */
export function SourcePill({ source }: { source: Finding["source"] }): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  return (
    <Pill kind={source === "platform" ? "info" : "neutral"}>{t(`findingPicker.${source}`)}</Pill>
  );
}
