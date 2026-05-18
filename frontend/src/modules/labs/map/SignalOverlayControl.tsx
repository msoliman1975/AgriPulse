import { useTranslation } from "react-i18next";

import type { SignalDefinition } from "@/api/signals";

interface Props {
  // Definitions the operator can choose from. The picker shows code +
  // name; the value emitted is the definition id (stable across name
  // changes).
  definitions: readonly SignalDefinition[];
  selectedDefinitionId: string | null;
  observationCount: number;
  skippedCount: number;
  isLoading: boolean;
  isError: boolean;
  onChange: (definitionId: string | null) => void;
}

/**
 * Bottom-right floating control on the Labs map. Operator picks a
 * signal_code; the parent fetches that signal's observations + feeds
 * them through buildSignalOverlay before passing the FC down to
 * MapCanvas as `signalOverlay`.
 *
 * Kept intentionally compact — V1 is "show me where readings exist".
 * Value-driven styling (numeric heatmap, categorical color-coding,
 * boolean true/false) is a follow-up; design needs a separate pass.
 */
export function SignalOverlayControl({
  definitions,
  selectedDefinitionId,
  observationCount,
  skippedCount,
  isLoading,
  isError,
  onChange,
}: Props) {
  const { t } = useTranslation("signals");

  return (
    <div
      className="pointer-events-auto absolute bottom-2 right-2 z-10 min-w-[220px] rounded-md border border-slate-300 bg-white/95 p-2 text-xs shadow-md"
      role="region"
      aria-label={t("overlay.regionLabel")}
    >
      <label className="flex flex-col gap-1">
        <span className="font-semibold text-slate-900">{t("overlay.title")}</span>
        <select
          className="rounded border border-slate-300 px-1.5 py-1 text-xs"
          value={selectedDefinitionId ?? ""}
          onChange={(event) => {
            const value = event.target.value;
            onChange(value === "" ? null : value);
          }}
          aria-label={t("overlay.selectLabel")}
        >
          <option value="">{t("overlay.none")}</option>
          {definitions.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name} ({d.code})
            </option>
          ))}
        </select>
      </label>

      {selectedDefinitionId ? (
        <p className="mt-1.5 text-[10px] text-slate-500" aria-live="polite">
          {isError
            ? t("overlay.loadFailed")
            : isLoading
              ? t("overlay.loading")
              : skippedCount > 0
                ? t("overlay.withSkipped", { shown: observationCount, skipped: skippedCount })
                : t("overlay.count", { count: observationCount })}
        </p>
      ) : null}
    </div>
  );
}
