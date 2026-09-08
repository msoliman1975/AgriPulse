import { useTranslation } from "react-i18next";

import type { StatusCode, StatusDefinition } from "@/api/farmHealth";
import { Pill } from "@/components/Pill";
import { STATUS_ORDER, type BlockRow } from "../lib/blockRows";

interface BlockListProps {
  rows: BlockRow[];
  statuses: StatusDefinition[];
  selectedBlockId: string | null;
  onSelect: (blockId: string) => void;
}

/** The status list, keyed by code, for colour and label lookups. */
function byCode(statuses: StatusDefinition[]): Map<StatusCode, StatusDefinition> {
  return new Map(statuses.map((s) => [s.code, s]));
}

/**
 * The rail: one row per block, worst first.
 *
 * The bar is the point of the row. A block's single status says what its
 * worst cell reads; the bar says how much of the block is in each state,
 * which is the difference between one failing emitter and a dry corner.
 */
export function BlockList({ rows, statuses, selectedBlockId, onSelect }: BlockListProps) {
  const { t, i18n } = useTranslation(["farmHealth"]);
  const lookup = byCode(statuses);
  // The status list ships both languages. Reading `label_en` unconditionally
  // is how English shipped under Arabic names once already.
  const arabic = i18n.language.startsWith("ar");
  const labelOf = (code: StatusCode | null): string => {
    const entry = lookup.get(code ?? "na");
    if (!entry) return code ?? "";
    return arabic ? (entry.label_ar ?? entry.label_en) : entry.label_en;
  };

  if (rows.length === 0) {
    return <p className="px-3 py-6 text-sm text-ap-muted">{t("farmHealth:rail.noBlocks")}</p>;
  }

  return (
    <ul className="flex flex-col gap-1 p-2">
      {rows.map((row) => {
        const total = row.verdicts.length;
        const selected = row.blockId === selectedBlockId;
        return (
          <li key={row.blockId}>
            <button
              type="button"
              aria-current={selected}
              onClick={() => onSelect(row.blockId)}
              className={[
                "grid w-full gap-2 rounded-card border px-3 py-2.5 text-left",
                selected
                  ? "border-ap-primary bg-ap-primary-soft"
                  : "border-transparent hover:bg-ap-bg",
              ].join(" ")}
            >
              <span className="flex items-baseline gap-2">
                <span className="text-card-title font-semibold tabular-nums text-ap-ink">
                  {row.code}
                </span>
                {row.crop ? (
                  <span className="ms-auto text-meta text-ap-muted">{row.crop}</span>
                ) : null}
              </span>

              <span className="flex h-1.5 overflow-hidden rounded-full bg-ap-line">
                {row.didNotRun ? (
                  <span
                    className="block w-full"
                    style={{
                      background:
                        "repeating-linear-gradient(45deg,#9aa0a6 0 3px,#d6d2c4 3px 7px)",
                    }}
                  />
                ) : (
                  STATUS_ORDER.filter((code) => row.counts[code] > 0).map((code) => (
                    <span
                      key={code}
                      className="block"
                      style={{
                        width: `${(100 * row.counts[code]) / Math.max(1, total)}%`,
                        background: lookup.get(code)?.color ?? "#9AA0A6",
                      }}
                    />
                  ))
                )}
              </span>

              <span className="flex items-center gap-2 text-meta text-ap-muted">
                {row.didNotRun ? (
                  <span className="inline-flex items-center rounded-full border border-dashed border-ap-line px-2 py-0.5 text-ap-muted">
                    {t("farmHealth:rail.didNotRun")}
                  </span>
                ) : (
                  <>
                    <Pill kind="neutral">{labelOf(row.worst)}</Pill>
                    <span className="tabular-nums">
                      {t("farmHealth:rail.verdictCount", { count: total })}
                    </span>
                  </>
                )}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
