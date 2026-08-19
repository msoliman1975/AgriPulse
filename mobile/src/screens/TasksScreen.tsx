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
import { dueIn, t, tCount, type Lang, type MessageKey } from "@/i18n";
import { dueAtMs } from "@/time";
import { WorkDetailScreen } from "@/screens/WorkDetailScreen";

/**
 * Everything this person owes, in the order a day is actually walked.
 *
 * The list used to be grouped by `origin` — `recommendation`, `ad_hoc`,
 * `self_initiated` — which is the name of the subsystem that raised the row.
 * Nobody plans a day around which subsystem asked. It is grouped by **when it
 * is due**, with the source demoted to one glyph on the row, and it can be
 * regrouped **by block**, because a scout walks a route and "while you are at
 * Block 12 there are three things" saves more walking than anything else here.
 */

type Segment = "mine" | "available" | "done";
type Bucket = "overdue" | "today" | "week" | "anytime";

const BUCKET_LABEL: Record<Bucket, MessageKey> = {
  overdue: "bucket.overdue",
  today: "bucket.today",
  week: "bucket.week",
  anytime: "bucket.anytime",
};

/** Which surface asked for this, as one character. */
const SOURCE_GLYPH: Record<string, string> = {
  recommendation: "\u{1F4A1}",
  alert: "\u{1F514}",
  ad_hoc: "\u{1F464}",
  routine: "\u{1F501}",
  self_initiated: "✓",
};

function bucketOf(item: WorkItem, now: number): Bucket {
  const due = dueAtMs(item.due_at);
  if (due === null) return "anytime";
  if (due < now) return "overdue";
  const endOfToday = new Date(now);
  endOfToday.setHours(23, 59, 59, 999);
  if (due <= endOfToday.getTime()) return "today";
  return due <= now + 7 * 86_400_000 ? "week" : "anytime";
}

/** Soonest first; undated last. Ordering inside a bucket, not across them. */
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
  farmId,
  onFullScreen,
}: {
  lang: Lang;
  farmId: string;
  onFullScreen: (full: boolean) => void;
}): ReactNode {
  const [segment, setSegment] = useState<Segment>("mine");
  const [byBlock, setByBlock] = useState(false);
  const [mine, setMine] = useState<WorkItem[]>([]);
  const [available, setAvailable] = useState<WorkItem[]>([]);
  const [done, setDone] = useState<WorkItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<WorkItem | null>(null);

  async function load(): Promise<void> {
    try {
      // Blocks come first and are cheap: without them every row and every
      // detail screen names a place by a UUID the scout cannot walk to.
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

  return (
    <div className="screen tasks">
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

      {/* Grouping by block only earns its place on work you still owe.
          Claimable and finished work is read, not walked. */}
      {segment === "mine" && shown.length > 1 ? (
        <button type="button" className={`grouper${byBlock ? " on" : ""}`} onClick={() => setByBlock((v) => !v)}>
          {t(lang, byBlock ? "group.byDue" : "group.byBlock")}
        </button>
      ) : null}

      {shown.length === 0 ? (
        <p className="empty">{t(lang, `empty.${segment}` as MessageKey)}</p>
      ) : segment === "done" ? (
        <ul>
          {[...shown].sort((a, b) => (dueAtMs(b.due_at) ?? 0) - (dueAtMs(a.due_at) ?? 0)).map((i) => (
            <Row key={`${i.kind}-${i.id}`} lang={lang} item={i} showDue={false} onOpen={() => setOpen(i)} />
          ))}
        </ul>
      ) : byBlock && segment === "mine" ? (
        <GroupedByBlock lang={lang} items={shown} onOpen={setOpen} />
      ) : (
        <GroupedByDue
          lang={lang}
          items={shown}
          onOpen={setOpen}
          onClaim={
            segment === "available"
              ? async (id) => {
                  // A 409 means somebody got there first; reloading shows the
                  // truth rather than arguing with it.
                  await claimVisit(id, farmId).catch(() => undefined);
                  await load();
                }
              : undefined
          }
        />
      )}
    </div>
  );
}

function GroupedByDue({
  lang,
  items,
  onOpen,
  onClaim,
}: {
  lang: Lang;
  items: WorkItem[];
  onOpen: (item: WorkItem) => void;
  onClaim?: (visitId: string) => void;
}): ReactNode {
  const now = Date.now();
  const buckets: Bucket[] = ["overdue", "today", "week", "anytime"];
  return (
    <>
      {buckets.map((b) => {
        const rows = items.filter((i) => bucketOf(i, now) === b).sort(bySoonest);
        if (rows.length === 0) return null;
        return (
          <section key={b}>
            <h2 className={`section${b === "overdue" ? " overdue" : ""}`}>
              {t(lang, BUCKET_LABEL[b])} <span className="count">{rows.length}</span>
            </h2>
            <ul>
              {rows.map((i) => (
                <Row
                  key={`${i.kind}-${i.id}`}
                  lang={lang}
                  item={i}
                  onOpen={() => onOpen(i)}
                  onClaim={onClaim ? () => onClaim(i.id) : undefined}
                />
              ))}
            </ul>
          </section>
        );
      })}
    </>
  );
}

/**
 * The same rows, grouped by where they are.
 *
 * Blocks with the most urgent work come first, so a route starts where it
 * matters. Work with no block sits at the end under its own heading rather
 * than being dropped, which is how a job goes missing.
 */
function GroupedByBlock({
  lang,
  items,
  onOpen,
}: {
  lang: Lang;
  items: WorkItem[];
  onOpen: (item: WorkItem) => void;
}): ReactNode {
  const groups = new Map<string, WorkItem[]>();
  for (const i of items) {
    const key = i.block_name ?? "";
    groups.set(key, [...(groups.get(key) ?? []), i]);
  }
  const soonest = (rows: WorkItem[]): number =>
    Math.min(...rows.map((r) => dueAtMs(r.due_at) ?? Number.MAX_SAFE_INTEGER));
  const ordered = [...groups.entries()].sort(([ka, a], [kb, b]) => {
    if (ka === "") return 1;
    if (kb === "") return -1;
    return soonest(a) - soonest(b);
  });

  return (
    <>
      {ordered.map(([name, rows]) => (
        <section key={name || "none"}>
          <h2 className="section">
            {name || t(lang, "group.noBlock")} <span className="count">{rows.length}</span>
          </h2>
          <ul>
            {rows.sort(bySoonest).map((i) => (
              <Row key={`${i.kind}-${i.id}`} lang={lang} item={i} onOpen={() => onOpen(i)} />
            ))}
          </ul>
        </section>
      ))}
    </>
  );
}
