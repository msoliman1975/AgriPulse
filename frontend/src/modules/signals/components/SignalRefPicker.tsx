import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SignalDefinition } from "@/api/signals";

import { buildSignalRef, refToJson, refToYaml, valueKeyForKind } from "./signalRef";

interface Props {
  // The signal definitions the author can pick from. Caller (each
  // editor surface) is responsible for the react-query fetch — this
  // component is dumb and just renders.
  definitions: readonly SignalDefinition[];
  isLoading?: boolean;
  isError?: boolean;
  // Which copy format the surrounding editor expects. Rules use JSON,
  // decision-trees use YAML.
  format: "json" | "yaml";
}

/**
 * Author-aid for the tenant-rule + decision-tree editors. Operator
 * picks a signal definition → the component derives the right value
 * key from the definition's value_kind, renders the ref object, and
 * offers a copy-to-clipboard button. The author then pastes the
 * snippet into the surrounding free-text editor at the spot they
 * want.
 *
 * D6 of the Custom Signals plan ([[project-custom-signals-plan]]).
 * Intentionally minimal: a full structured condition-tree GUI is a
 * much bigger project; this just removes "what was the exact code
 * again?" + "what's the JSON shape?" friction.
 */
export function SignalRefPicker({ definitions, isLoading, isError, format }: Props) {
  const { t } = useTranslation("signals");
  const [selectedId, setSelectedId] = useState<string>("");
  const [copied, setCopied] = useState(false);

  const selected = useMemo(
    () => definitions.find((d) => d.id === selectedId) ?? null,
    [definitions, selectedId],
  );
  const valueKey = selected ? valueKeyForKind(selected.value_kind) : null;
  const ref = selected && valueKey ? buildSignalRef(selected.code, valueKey) : null;
  const rendered = ref ? (format === "json" ? refToJson(ref) : refToYaml(ref)) : "";
  const isUnsupportedKind = selected !== null && valueKey === null;

  async function onCopy(): Promise<void> {
    if (!rendered) return;
    try {
      await navigator.clipboard.writeText(rendered);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can be blocked (insecure context, perm denial).
      // Fall back is fine — the snippet is selectable in the <pre> below.
    }
  }

  return (
    <div className="rounded-md border border-ap-line bg-ap-bg/40 p-2 text-xs">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-1 min-w-[180px] flex-col gap-1">
          <span className="text-xs font-medium text-ap-muted">{t("refPicker.title")}</span>
          <select
            disabled={isLoading || isError || definitions.length === 0}
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            className="rounded border border-ap-line bg-white px-2 py-1 text-xs shadow-sm focus:border-ap-primary focus:outline-none focus:ring-1 focus:ring-ap-primary"
            aria-label={t("refPicker.selectLabel")}
          >
            <option value="">
              {isLoading
                ? t("refPicker.loading")
                : isError
                  ? t("refPicker.loadFailed")
                  : definitions.length === 0
                    ? t("refPicker.empty")
                    : t("refPicker.placeholder")}
            </option>
            {definitions.map((d) => (
              <option key={d.id} value={d.id}>
                {d.code} — {d.name}
              </option>
            ))}
          </select>
        </label>
        {selected ? (
          <span
            className="rounded bg-ap-line/40 px-1.5 py-0.5 text-[10px] font-mono text-ap-muted"
            aria-label={t("refPicker.valueKeyLabel")}
          >
            {valueKey ?? t("refPicker.unsupportedKindShort")}
          </span>
        ) : null}
        <button
          type="button"
          onClick={onCopy}
          disabled={!ref}
          className="rounded border border-ap-line bg-white px-2 py-1 text-[11px] text-ap-ink shadow-sm hover:bg-ap-bg/40 disabled:opacity-50"
        >
          {copied ? t("refPicker.copied") : t("refPicker.copy")}
        </button>
      </div>

      {selected && isUnsupportedKind ? (
        <p className="mt-1.5 text-[11px] text-ap-warn">{t("refPicker.unsupportedKind")}</p>
      ) : null}

      {ref ? (
        <pre className="mt-1.5 overflow-x-auto rounded bg-white p-1.5 font-mono text-[11px] text-ap-ink">
          {rendered}
        </pre>
      ) : null}

      <p className="mt-1.5 text-[10px] text-ap-muted">{t("refPicker.hint")}</p>
    </div>
  );
}
