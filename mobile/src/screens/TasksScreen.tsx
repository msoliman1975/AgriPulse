import { useEffect, useState, type ReactNode } from "react";

import {
  claimVisit,
  listBlocks,
  listMyWork,
  listVisits,
  type Block,
  type Visit,
  type WorkItem,
} from "@/api/client";
import { HomeHeader } from "@/components/HomeHeader";
import { dueIn, t, tCount, type Lang, type MessageKey } from "@/i18n";
import { dueAtMs } from "@/time";
import { WorkDetailScreen } from "@/screens/WorkDetailScreen";

/**
 * Everything this person owes.
 *
 * The landing is **tiles, not a list**. A scout with thirty open jobs cannot
 * plan a day from a scroll; they need to see *where* the work is before they
 * see what it is. Each tile is a place — a block — carrying its own count,
 * plus one tile for work that belongs to no block at all. Tapping a tile opens
 * that group's list.
 *
 * The same landing regroups **by time**, and then the tiles are Overdue /
 * Today / This week / Next week / Later. Both answer "where do I start"; one
 * answers by geography and the other by deadline, and which is right depends
 * on whether the scout is planning a route or a day.
 *
 * Origin — `recommendation`, `alert`, `ad_hoc` — groups nothing. It is the
 * name of the subsystem that raised the row, and nobody plans a day around
 * that. It stays one glyph on the row.
 */

type Segment = "mine" | "available" | "done";
type GroupBy = "block" | "time";
type Bucket = "overdue" | "today" | "week" | "next" | "later";

/** Fixed, ordered and small — unlike blocks, which a farm has dozens of. */
const BUCKETS: Bucket[] = ["overdue", "today", "week", "next", "later"];

const BUCKET_LABEL: Record<Bucket, MessageKey> = {
  overdue: "bucket.overdue",
  today: "bucket.today",
  week: "bucket.week",
  next: "bucket.next",
  later: "bucket.later",
};

/** Which surface asked for this, as one character. */
const SOURCE_GLYPH: Record<string, string> = {
  recommendation: "\u{1F4A1}",
  alert: "\u{1F514}",
  ad_hoc: "\u{1F464}",
  routine: "\u{1F501}",
  self_initiated: "✓",
};

/** Local end of today, so "today" means the whole day and not this instant. */
function endOfToday(now: number): number {
  const d = new Date(now);
  d.setHours(23, 59, 59, 999);
  return d.getTime();
}

function bucketOf(item: WorkItem, now: number): Bucket {
  const due = dueAtMs(item.due_at);
  // No deadline is neither late nor today: it is work with no clock on it,
  // which is what `later` is for.
  if (due === null) return "later";
  if (due < now) return "overdue";
  const today = endOfToday(now);
  if (due <= today) return "today";
  if (due <= today + 7 * 86_400_000) return "week";
  if (due <= today + 14 * 86_400_000) return "next";
  return "later";
}

/** Soonest first; undated last. Ordering inside a group, not across them. */
function bySoonest(a: WorkItem, b: WorkItem): number {
  const x = dueAtMs(a.due_at);
  const y = dueAtMs(b.due_at);
  if (x === null) return y === null ? 0 : 1;
  if (y === null) return -1;
  return x - y;
}

/** A visit rendered as a work item, so one detail screen serves both kinds. */
function asWorkItem(v: Visit, farmId: string, blockName: string | null): WorkItem {
  return {
    kind: "scouting_visit",
    id: v.id,
    farm_id: farmId,
    block_id: v.block_id,
    block_name: blockName,
    title: v.title,
    detail: v.instruction,
    status: v.status,
    category: v.origin,
    severity: v.severity,
    priority: v.priority,
    due_at: v.due_by,
    template_id: v.template_id,
    source: v.source,
  };
}

/** Worst thing inside, so a tile carries the urgency of what it hides. */
function tileTone(items: WorkItem[], now: number): string {
  if (items.some((i) => bucketOf(i, now) === "overdue")) return "crit";
  if (items.some((i) => i.severity === "critical")) return "crit";
  if (items.some((i) => i.severity === "warning")) return "warn";
  return "";
}

function Tile({
  label,
  count,
  tone,
  onOpen,
}: {
  label: string;
  count: number;
  tone: string;
  onOpen: () => void;
}): ReactNode {
  return (
    <button type="button" className={`tile ${tone}`} disabled={count === 0} onClick={onOpen}>
      <span className="n">{count}</span>
      <span className="lbl">{label}</span>
    </button>
  );
}

function Row({
  lang,
  item,
  onOpen,
  onClaim,
  showDue = true,
}: {
  lang: Lang;
  item: WorkItem;
  onOpen: () => void;
  onClaim?: () => void;
  /** Off for finished work: a closed job has no deadline left to miss. */
  showDue?: boolean;
}): ReactNode {
  const glyph = item.kind === "plan_activity" ? "\u{1F4CB}" : SOURCE_GLYPH[item.category ?? ""] ?? "";
  return (
    <li className={`visit sev-${item.severity ?? "info"} tappable`} onClick={onOpen}>
      <span className="ring">{showDue ? dueIn(lang, item.due_at) : "✓"}</span>
      <div className="body">
        <div className="title">{item.title}</div>
        {item.detail ? <div className="instruction">{item.detail}</div> : null}
        <div className="meta">
          {glyph ? <span className="src">{glyph}</span> : null}
          {item.block_name ? <span className="where">{item.block_name}</span> : null}
          {/* One finding, several zones. Without this the scout knows only that
              "something" fired, not whether it is one corner or half the field. */}
          {item.source?.is_group && item.source.member_count > 0 ? (
            <span className="zones">
              {item.source.member_count === 1
                ? t(lang, "visits.zonesOne")
                : tCount(lang, "visits.zones", item.source.member_count)}
            </span>
          ) : null}
          {/* Direction, when there is a yesterday to compare against. Nine zones
              holding steady and nine up from four are different walks. */}
          {item.source?.trend === "spreading" || item.source?.trend === "receding" ? (
            <span className={`trend trend-${item.source.trend}`}>
              {item.source.trend === "spreading"
                ? `▲ ${t(lang, "visits.spreading")}`
                : `▼ ${t(lang, "visits.receding")}`}
            </span>
          ) : null}
          {/* How long it has been true. A six-day-old problem presented as this
              morning's news is how a scout learns to distrust the queue. */}
          {item.source && item.source.day_streak > 1 ? (
            <span className="streak">
              {item.source.day_streak === 2
                ? t(lang, "visits.sinceYesterday")
                : tCount(lang, "visits.daysRunning", item.source.day_streak)}
            </span>
          ) : null}
        </div>
      </div>
      {onClaim ? (
        <button
          type="button"
          onClick={(e) => {
            // The row opens the detail; the button claims. Without this the
            // one tap would do both.
            e.stopPropagation();
            onClaim();
          }}
        >
          {t(lang, "visits.claim")}
        </button>
      ) : null}
    </li>
  );
}

export function TasksScreen({
  lang,
  onLangChange,
  name,
  farmId,
  onFullScreen,
}: {
  lang: Lang;
  onLangChange: (lang: Lang) => void;
  name: string | null;
  farmId: string;
  onFullScreen: (full: boolean) => void;
}): ReactNode {
  const [segment, setSegment] = useState<Segment>("mine");
  const [groupBy, setGroupBy] = useState<GroupBy>("block");
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [mine, setMine] = useState<WorkItem[]>([]);
  const [available, setAvailable] = useState<WorkItem[]>([]);
  const [done, setDone] = useState<WorkItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<WorkItem | null>(null);

  async function load(): Promise<void> {
    try {
      const [work, mineVisits, claimable, closed, blockList] = await Promise.all([
        listMyWork(farmId),
        listVisits(farmId, { mine: true }),
        listVisits(farmId, { claimable: true }),
        listVisits(farmId, { mine: true, status: ["completed"] }),
        listBlocks(farmId).catch(() => [] as Block[]),
      ]);
      const name = (id: string | null): string | null => {
        const found = blockList.find((b) => b.id === id);
        return found ? found.name || found.code : null;
      };
      // `/me/work` merges visits and board work but does not carry the group
      // counters, and the visit list carries them but not board work. Joining
      // by id keeps both rather than choosing which half to lose.
      const sourceById = new Map(mineVisits.map((v) => [v.id, v.source]));
      setMine(
        work.map((w) => ({
          ...w,
          block_name: name(w.block_id),
          source: sourceById.get(w.id) ?? null,
        })),
      );
      setAvailable(claimable.map((v) => asWorkItem(v, farmId, name(v.block_id))));
      setDone(closed.map((v) => asWorkItem(v, farmId, name(v.block_id))));
      setError(null);
    } catch {
      setError(t(lang, "visits.loadFailed"));
    }
  }

  // The list is the source of truth, not the push: a dropped notification must
  // never mean lost work, so every open reconciles.
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [farmId]);

  useEffect(() => {
    onFullScreen(open !== null);
  }, [open, onFullScreen]);

  // Changing how work is grouped invalidates which group is open.
  useEffect(() => {
    setOpenGroup(null);
  }, [groupBy, segment]);

  if (open) {
    return (
      <WorkDetailScreen
        lang={lang}
        farmId={farmId}
        item={open}
        onClose={() => {
          setOpen(null);
          void load();
        }}
        onChanged={() => void load()}
      />
    );
  }

  const shown = segment === "mine" ? mine : segment === "available" ? available : done;
  const now = Date.now();

  const groupKey = (i: WorkItem): string =>
    groupBy === "block" ? (i.block_name ?? "") : bucketOf(i, now);
  const inGroup = openGroup === null ? [] : shown.filter((i) => groupKey(i) === openGroup);
  const groupLabel = (key: string): string =>
    groupBy === "time" ? t(lang, BUCKET_LABEL[key as Bucket]) : key || t(lang, "group.noBlock");

  return (
    <div className="screen tasks">
      <HomeHeader lang={lang} onLangChange={onLangChange} name={name} />
      <div className="seg">
        {(["mine", "available", "done"] as Segment[]).map((s) => (
          <button
            key={s}
            type="button"
            className={s === segment ? "on" : ""}
            onClick={() => setSegment(s)}
          >
            {t(lang, `seg.${s}` as MessageKey)}
          </button>
        ))}
      </div>

      {error ? <p className="error">{error}</p> : null}

      {/* Tiles are the landing for work you still owe. Claimable work is short
          and finished work is history — both are read, not planned from. */}
      {segment === "mine" ? (
        openGroup === null ? (
          <>
            <div className="groupby">
              {(["block", "time"] as GroupBy[]).map((g) => (
                <button
                  key={g}
                  type="button"
                  className={g === groupBy ? "on" : ""}
                  onClick={() => setGroupBy(g)}
                >
                  {t(lang, g === "block" ? "group.byBlock" : "group.byDue")}
                </button>
              ))}
            </div>
            {shown.length === 0 ? (
              <p className="empty">{t(lang, "empty.mine")}</p>
            ) : (
              <TileGrid lang={lang} items={shown} groupBy={groupBy} now={now} onOpenGroup={setOpenGroup} />
            )}
          </>
        ) : (
          <>
            <button type="button" className="crumb" onClick={() => setOpenGroup(null)}>
              <span className="back">‹</span>
              {groupLabel(openGroup)}
              <span className="count">{inGroup.length}</span>
            </button>
            <ul>
              {[...inGroup].sort(bySoonest).map((i) => (
                <Row key={`${i.kind}-${i.id}`} lang={lang} item={i} onOpen={() => setOpen(i)} />
              ))}
            </ul>
          </>
        )
      ) : shown.length === 0 ? (
        <p className="empty">{t(lang, `empty.${segment}` as MessageKey)}</p>
      ) : (
        <ul>
          {[...shown]
            .sort(
              segment === "done"
                ? (a, b) => (dueAtMs(b.due_at) ?? 0) - (dueAtMs(a.due_at) ?? 0)
                : bySoonest,
            )
            .map((i) => (
              <Row
                key={`${i.kind}-${i.id}`}
                lang={lang}
                item={i}
                showDue={segment !== "done"}
                onOpen={() => setOpen(i)}
                onClaim={
                  segment === "available"
                    ? async () => {
                        // A 409 means somebody got there first; reloading shows
                        // the truth rather than arguing with it.
                        await claimVisit(i.id, farmId).catch(() => undefined);
                        await load();
                      }
                    : undefined
                }
              />
            ))}
        </ul>
      )}
    </div>
  );
}

/**
 * The tiles themselves.
 *
 * Blocks appear only where there is work: a farm has dozens, and thirty empty
 * tiles would bury the four that matter. The time buckets are always all five,
 * because they are a fixed vocabulary and "Today 0" is information a scout
 * wants — it is the difference between a clear day and a failed fetch.
 */
function TileGrid({
  lang,
  items,
  groupBy,
  now,
  onOpenGroup,
}: {
  lang: Lang;
  items: WorkItem[];
  groupBy: GroupBy;
  now: number;
  onOpenGroup: (key: string) => void;
}): ReactNode {
  if (groupBy === "time") {
    return (
      <div className="tiles">
        {BUCKETS.map((b) => {
          const rows = items.filter((i) => bucketOf(i, now) === b);
          return (
            <Tile
              key={b}
              label={t(lang, BUCKET_LABEL[b])}
              count={rows.length}
              tone={b === "overdue" && rows.length > 0 ? "crit" : tileTone(rows, now)}
              onOpen={() => onOpenGroup(b)}
            />
          );
        })}
      </div>
    );
  }

  const groups = new Map<string, WorkItem[]>();
  for (const i of items) {
    const key = i.block_name ?? "";
    groups.set(key, [...(groups.get(key) ?? []), i]);
  }
  // Most urgent block first, so a route starts where it matters. Work with no
  // block sits last under its own tile rather than being dropped, which is how
  // a job goes missing.
  const soonest = (rows: WorkItem[]): number =>
    Math.min(...rows.map((r) => dueAtMs(r.due_at) ?? Number.MAX_SAFE_INTEGER));
  const ordered = [...groups.entries()].sort(([ka, a], [kb, b]) => {
    if (ka === "") return 1;
    if (kb === "") return -1;
    return soonest(a) - soonest(b);
  });

  return (
    <div className="tiles">
      {ordered.map(([key, rows]) => (
        <Tile
          key={key || "none"}
          label={key || t(lang, "group.noBlock")}
          count={rows.length}
          tone={tileTone(rows, now)}
          onOpen={() => onOpenGroup(key)}
        />
      ))}
    </div>
  );
}
