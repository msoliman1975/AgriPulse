import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { BulkCropCandidate } from "@/api/bulkCropAssignment";
import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { EmptyState } from "@/components/EmptyState";
import { Pill } from "@/components/Pill";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";

export interface BlockOverride {
  season_label?: string;
  planting_date?: string;
}

interface Props {
  candidates: BulkCropCandidate[];
  selected: Set<string>;
  onSelectedChange: (next: Set<string>) => void;
  overrides: Record<string, BlockOverride>;
  onOverridesChange: (next: Record<string, BlockOverride>) => void;
  /** Placeholder for the season override — the run's shared value. */
  sharedSeason: string;
  /** Drives the per-row "will skip" / "will replace" hint. */
  conflictMode: "skip" | "replace";
}

type SortKey = "code" | "area" | "crop" | "season" | "planted";

const INPUT =
  "w-full rounded border px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-ap-primary";

/**
 * The "where does this land" step of a bulk run.
 *
 * Search + sortable columns rather than filter chips: the question a user
 * actually arrives with is "which blocks are already on mango", and sorting
 * the current-crop column answers it without a filter vocabulary to learn.
 * `Select all matching` operates on the *filtered* rows, so a search becomes
 * a selection in one click — the reason the search box exists at all.
 */
export function BulkBlockPicker({
  candidates,
  selected,
  onSelectedChange,
  overrides,
  onOverridesChange,
  sharedSeason,
  conflictMode,
}: Props): ReactNode {
  const { t } = useTranslation("bulkUpdates");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "code", dir: 1 });

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = candidates.filter(
      (c) =>
        !q ||
        c.code.toLowerCase().includes(q) ||
        (c.name ?? "").toLowerCase().includes(q) ||
        (c.current?.crop_path ?? "").toLowerCase().includes(q),
    );
    // Unassigned blocks sort last on the crop-ish columns rather than first:
    // "￿" is above every real value, so a descending sort still leads
    // with real crops instead of a wall of blanks.
    const value = (c: BulkCropCandidate): string | number => {
      switch (sort.key) {
        case "area":
          return Number(c.area_value);
        case "crop":
          return c.current?.crop_path ?? "￿";
        case "season":
          return c.current?.season_label ?? "￿";
        case "planted":
          return c.current?.planting_date ?? "￿";
        default:
          return c.code;
      }
    };
    return [...filtered].sort((a, b) => {
      const x = value(a);
      const y = value(b);
      if (x === y) return a.code.localeCompare(b.code);
      return (x > y ? 1 : -1) * sort.dir;
    });
  }, [candidates, query, sort]);

  const shownSelected = rows.filter((r) => selected.has(r.block_id)).length;

  const toggle = (blockId: string, on: boolean): void => {
    const next = new Set(selected);
    if (on) {
      next.add(blockId);
    } else {
      next.delete(blockId);
      // Dropping a block drops its overrides too — a stale override that
      // reappears when the block is re-picked is a silent wrong write.
      const nextOverrides = { ...overrides };
      delete nextOverrides[blockId];
      onOverridesChange(nextOverrides);
    }
    onSelectedChange(next);
  };

  const setOverride = (blockId: string, field: keyof BlockOverride, value: string): void => {
    const next = { ...overrides, [blockId]: { ...overrides[blockId] } };
    if (value) {
      next[blockId][field] = value;
    } else {
      delete next[blockId][field];
    }
    if (Object.keys(next[blockId]).length === 0) delete next[blockId];
    onOverridesChange(next);
  };

  const sortHeader = (key: SortKey, label: string, align?: "end"): ReactNode => {
    const active = sort.key === key;
    return (
      <Th
        aria-sort={active ? (sort.dir === 1 ? "ascending" : "descending") : undefined}
        className={align === "end" ? "text-end" : undefined}
      >
        <button
          type="button"
          className="inline-flex items-center gap-1 hover:text-ap-primary"
          onClick={() =>
            setSort((prev) => ({ key, dir: prev.key === key && prev.dir === 1 ? -1 : 1 }))
          }
        >
          {label}
          <span aria-hidden className={active ? "text-ap-primary" : "text-ap-muted/50"}>
            {active ? (sort.dir === 1 ? "↑" : "↓") : "↕"}
          </span>
        </button>
      </Th>
    );
  };

  if (candidates.length === 0) {
    return (
      <Card>
        <EmptyState message={t("blocks.none")} />
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          className="min-w-[220px] flex-1 rounded-md border border-ap-line bg-ap-panel px-3 py-1.5 text-sm"
          placeholder={t("blocks.searchPlaceholder")}
          aria-label={t("blocks.searchLabel")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Button
          variant="secondary"
          size="sm"
          onClick={() => onSelectedChange(new Set([...selected, ...rows.map((r) => r.block_id)]))}
        >
          {t("blocks.selectAllMatching", { count: rows.length })}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            onSelectedChange(new Set());
            onOverridesChange({});
          }}
        >
          {t("blocks.clear")}
        </Button>
        <span className="text-sm text-ap-muted">
          {t("blocks.countLabel", { selected: shownSelected, shown: rows.length })}
        </span>
      </div>

      <Table>
        <Thead>
          <Tr>
            <Th className="w-10">
              <input
                type="checkbox"
                aria-label={t("blocks.selectAllShown")}
                checked={rows.length > 0 && shownSelected === rows.length}
                ref={(el) => {
                  if (el) el.indeterminate = shownSelected > 0 && shownSelected < rows.length;
                }}
                onChange={(e) => {
                  const next = new Set(selected);
                  const nextOverrides = { ...overrides };
                  rows.forEach((r) => {
                    if (e.target.checked) {
                      next.add(r.block_id);
                    } else {
                      next.delete(r.block_id);
                      delete nextOverrides[r.block_id];
                    }
                  });
                  onSelectedChange(next);
                  onOverridesChange(nextOverrides);
                }}
              />
            </Th>
            {sortHeader("code", t("blocks.col.block"))}
            {sortHeader("area", t("blocks.col.area"), "end")}
            {sortHeader("crop", t("blocks.col.currentCrop"))}
            {sortHeader("season", t("blocks.col.season"))}
            {sortHeader("planted", t("blocks.col.planted"))}
            <Th>{t("blocks.col.overrideSeason")}</Th>
            <Th>{t("blocks.col.overridePlanting")}</Th>
          </Tr>
        </Thead>
        <Tbody>
          {rows.map((row) => {
            const isSelected = selected.has(row.block_id);
            const override = overrides[row.block_id] ?? {};
            return (
              <Tr
                key={row.block_id}
                className={isSelected ? "bg-ap-primary-soft/40" : undefined}
                data-testid={`block-row-${row.code}`}
              >
                <Td>
                  <input
                    type="checkbox"
                    aria-label={t("blocks.selectOne", { code: row.code })}
                    checked={isSelected}
                    onChange={(e) => toggle(row.block_id, e.target.checked)}
                  />
                </Td>
                <Td>
                  <span className="font-medium text-ap-ink">{row.code}</span>
                  {row.name ? <div className="text-xs text-ap-muted">{row.name}</div> : null}
                </Td>
                <Td className="text-end tabular-nums">{Number(row.area_value).toFixed(1)}</Td>
                <Td>
                  {row.current ? (
                    <span className="flex flex-wrap items-center gap-1.5">
                      {row.current.crop_path}
                      {isSelected ? (
                        <Pill kind={conflictMode === "skip" ? "warn" : "info"}>
                          {conflictMode === "skip" ? t("blocks.willSkip") : t("blocks.willReplace")}
                        </Pill>
                      ) : null}
                    </span>
                  ) : (
                    <span className="text-ap-muted">{t("blocks.unassigned")}</span>
                  )}
                </Td>
                <Td className="text-ap-muted">{row.current?.season_label ?? "—"}</Td>
                <Td className="tabular-nums text-ap-muted">{row.current?.planting_date ?? "—"}</Td>
                <Td>
                  {isSelected ? (
                    <input
                      className={`${INPUT} ${
                        override.season_label
                          ? "border-ap-accent font-medium text-ap-accent"
                          : "border-dashed border-ap-line"
                      }`}
                      aria-label={t("blocks.overrideSeasonFor", { code: row.code })}
                      placeholder={sharedSeason || t("blocks.shared")}
                      value={override.season_label ?? ""}
                      onChange={(e) => setOverride(row.block_id, "season_label", e.target.value)}
                    />
                  ) : (
                    <span className="text-ap-muted">—</span>
                  )}
                </Td>
                <Td>
                  {isSelected ? (
                    <input
                      type="date"
                      className={`${INPUT} ${
                        override.planting_date
                          ? "border-ap-accent font-medium text-ap-accent"
                          : "border-dashed border-ap-line"
                      }`}
                      aria-label={t("blocks.overridePlantingFor", { code: row.code })}
                      value={override.planting_date ?? ""}
                      onChange={(e) => setOverride(row.block_id, "planting_date", e.target.value)}
                    />
                  ) : (
                    <span className="text-ap-muted">—</span>
                  )}
                </Td>
              </Tr>
            );
          })}
        </Tbody>
      </Table>
      <p className="text-xs text-ap-muted">{t("blocks.overrideHelp")}</p>
    </div>
  );
}
