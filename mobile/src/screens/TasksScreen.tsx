import { useEffect, useMemo, useState, type ReactNode } from "react";

import { claimVisit, type WorkItem } from "@/api/client";
import type { FarmScope } from "@/api/me";
import { HomeHeader } from "@/components/HomeHeader";
import { dueIn, t, tCount, type Lang, type MessageKey } from "@/i18n";
import { WorkDetailScreen } from "@/screens/WorkDetailScreen";
import {
  BUCKETS,
  BUCKET_LABEL,
  DONE_BUCKETS,
  bucketOf,
  byLatestClosed,
  bySoonest,
  doneBucketOf,
  groupKeyOf,
  farmTone,
  soonestIn,
  tileTone,
  type Bucket,
  type DoneBucket,
  type GroupBy,
} from "@/work/grouping";
import { EMPTY_WORK, loadWork, type WorkSet } from "@/work/load";

/**
 * Everything this person owes, on every farm they hold.
 *
 * The landing is **tiles, not a list**, and the first tile is a **farm**. A
 * scout with thirty open jobs across two farms cannot plan a day from a
 * scroll; they need to see which farm the work is on, then where in it, then
 * what it is. Each level narrows and each one is one tap.
 *
 *   farm → block · time → the rows
 *
 * The farm level disappears when there is one farm, because a choice of one is
 * not a choice — the screen opens straight on the block and time tiles and the
 * farm is stated once in the header instead.
 *
 * All three segments — My work, Available, Done — use the same three levels.
 * They used to be a tiled landing and two flat lists, which taught a scout
 * that grouping was a property of the screen rather than of the work. The
 * piles differ only in what the time buckets mean: ahead of now for open work,
 * behind it for finished work.
 */

type Segment = "mine" | "available" | "done";

/** Which surface asked for this, as one character. */
const SOURCE_GLYPH: Record<string, string> = {
  recommendation: "\u{1F4A1}",
  alert: "\u{1F514}",
  ad_hoc: "\u{1F464}",
  routine: "\u{1F501}",
  self_initiated: "✓",
};

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
      {/* A block or farm name is tenant-written and may be in either script.
          `auto` lets each label find its own direction, so an Arabic block name
          on an English screen is not laid out backwards. */}
      <span className="lbl" dir="auto">{label}</span>
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
        {/* Titles come from the decision engine and instructions from a
            supervisor, in whichever language they wrote. Without `auto` a
            Latin sentence on an Arabic screen has its full stop dragged to the
            far end of the line, which reads as a rendering fault. */}
        <div className="title" dir="auto">{item.title}</div>
        {item.detail ? (
          <div className="instruction" dir="auto">{item.detail}</div>
        ) : null}
        <div className="meta">
          {glyph ? <span className="src">{glyph}</span> : null}
          {item.block_name ? (
            <span className="where" dir="auto">{item.block_name}</span>
          ) : null}
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
  farms,
  farmName,
  onFullScreen,
}: {
  lang: Lang;
  onLangChange: (lang: Lang) => void;
  name: string | null;
  /** Every farm this scout is granted. Never empty — the caller handles that. */
  farms: FarmScope[];
  /** Id -> the name people call it, falling back to the id when unknown. */
  farmName: (farmId: string) => string;
  onFullScreen: (full: boolean) => void;
}): ReactNode {
  const single = farms.length === 1 ? farms[0].farm_id : null;

  const [segment, setSegment] = useState<Segment>("mine");
  const [groupBy, setGroupBy] = useState<GroupBy>("block");
  /** Null means "show the farm tiles". A one-farm scout is never there. */
  const [openFarm, setOpenFarm] = useState<string | null>(single);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const [work, setWork] = useState<WorkSet>(EMPTY_WORK);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<WorkItem | null>(null);

  const farmIds = farms.map((f) => f.farm_id).join(",");

  async function load(): Promise<void> {
    try {
      setWork(await loadWork(farms, farmName));
      setError(null);
    } catch {
      setError(t(lang, "visits.loadFailed"));
    }
  }

  // The list is the source of truth, not the push: a dropped notification must
  // never mean lost work, so every open reconciles. Keyed on the set of farms
  // rather than one id, because gaining or losing a farm changes the whole
  // screen and not just which slice of it is shown.
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [farmIds]);

  // A scout granted exactly one farm never sees the farm level, so the open
  // farm has to follow the grant rather than waiting for a tap that cannot
  // happen. Losing a second farm mid-session lands here too.
  useEffect(() => {
    if (single) setOpenFarm(single);
  }, [single]);

  useEffect(() => {
    onFullScreen(open !== null);
  }, [open, onFullScreen]);

  // Changing how work is grouped, or which pile is shown, invalidates which
  // group is open. The farm survives both: it is the outer question, and
  // re-answering it on every segment tap would be the old settings screen with
  // extra steps.
  useEffect(() => {
    setOpenGroup(null);
  }, [groupBy, segment]);

  const shown = segment === "mine" ? work.mine : segment === "available" ? work.available : work.done;
  const done = segment === "done";
  const now = Date.now();

  const inFarm = useMemo(
    () => (openFarm === null ? [] : shown.filter((i) => i.farm_id === openFarm)),
    [shown, openFarm],
  );
  const inGroup =
    openGroup === null ? [] : inFarm.filter((i) => groupKeyOf(i, groupBy, now, done) === openGroup);

  const groupLabel = (key: string): string => {
    if (groupBy === "block") return key || t(lang, "group.noBlock");
    return t(lang, BUCKET_LABEL[key as Bucket | DoneBucket]);
  };

  if (open) {
    return (
      <WorkDetailScreen
        lang={lang}
        farmId={open.farm_id}
        item={open}
        onClose={() => {
          setOpen(null);
          void load();
        }}
        onChanged={() => void load()}
      />
    );
  }

  /** One step back up the farm → group → rows ladder. */
  const up = (): void => {
    if (openGroup !== null) setOpenGroup(null);
    else setOpenFarm(null);
  };

  /** What the crumb says, deepest level last. Never shown at the top level. */
  const crumb =
    openGroup !== null
      ? single
        ? groupLabel(openGroup)
        : `${farmName(openFarm ?? "")} › ${groupLabel(openGroup)}`
      : openFarm !== null && !single
        ? farmName(openFarm)
        : null;

  return (
    <div className="screen tasks">
      <HomeHeader
        lang={lang}
        onLangChange={onLangChange}
        name={name}
        // One farm is a fact about this scout and belongs in the header. Several
        // is a question the tiles below are already asking, and answering it up
        // here too would name a farm the list is not limited to.
        farmName={single ? farmName(single) : tCount(lang, "group.farmsCount", farms.length)}
      />
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
      {/* A short list that looks complete is worse than an error. Naming the
          farms that did not answer is the difference between "nothing to do"
          and "we could not ask". */}
      {work.failed.length > 0 ? (
        <p className="warnline">
          {t(lang, "tasks.someFarmsFailed")}
          <span className="which">{work.failed.map(farmName).join(" · ")}</span>
        </p>
      ) : null}

      {crumb ? (
        <button type="button" className="crumb" onClick={up}>
          <span className="back">‹</span>
          <span className="lbl" dir="auto">{crumb}</span>
          <span className="count">{openGroup !== null ? inGroup.length : inFarm.length}</span>
        </button>
      ) : null}

      {openFarm === null ? (
        <FarmTiles
          lang={lang}
          farms={farms}
          farmName={farmName}
          items={shown}
          done={done}
          now={now}
          emptyKey={`empty.${segment}` as MessageKey}
          onOpen={setOpenFarm}
        />
      ) : openGroup === null ? (
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
          {inFarm.length === 0 ? (
            <p className="empty">{t(lang, `empty.${segment}` as MessageKey)}</p>
          ) : (
            <GroupTiles
              lang={lang}
              items={inFarm}
              groupBy={groupBy}
              done={done}
              now={now}
              onOpen={setOpenGroup}
            />
          )}
        </>
      ) : (
        <ul>
          {[...inGroup].sort(done ? byLatestClosed : bySoonest).map((i) => (
            <Row
              key={`${i.kind}-${i.id}`}
              lang={lang}
              item={i}
              showDue={!done}
              onOpen={() => setOpen(i)}
              onClaim={
                segment === "available"
                  ? async () => {
                      // A 409 means somebody got there first; reloading shows
                      // the truth rather than arguing with it.
                      await claimVisit(i.id, i.farm_id).catch(() => undefined);
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
 * The farm level.
 *
 * Every granted farm is shown, including the ones with nothing in this pile.
 * That is the opposite of the rule one level down, and deliberately: a block
 * with no work is noise, but a *farm* with no work is an answer. "Nothing on
 * the north farm" is what stops a scout driving there.
 */
function FarmTiles({
  lang,
  farms,
  farmName,
  items,
  done,
  now,
  emptyKey,
  onOpen,
}: {
  lang: Lang;
  farms: FarmScope[];
  farmName: (farmId: string) => string;
  items: WorkItem[];
  done: boolean;
  now: number;
  emptyKey: MessageKey;
  onOpen: (farmId: string) => void;
}): ReactNode {
  const byFarm = farms.map((f) => ({
    id: f.farm_id,
    rows: items.filter((i) => i.farm_id === f.farm_id),
  }));
  // Most urgent farm first — the same rule the block tiles use, for the same
  // reason: the top-left tile should be where the day starts.
  const ordered = done
    ? byFarm
    : [...byFarm].sort((a, b) => soonestIn(a.rows) - soonestIn(b.rows));

  return (
    <>
      <h2 className="section">{t(lang, "group.farms")}</h2>
      {items.length === 0 ? <p className="empty">{t(lang, emptyKey)}</p> : null}
      <div className="tiles">
        {ordered.map(({ id, rows }) => (
          <Tile
            key={id}
            label={farmName(id)}
            count={rows.length}
            tone={farmTone(rows, now, done)}
            onOpen={() => onOpen(id)}
          />
        ))}
      </div>
    </>
  );
}

/**
 * Inside one farm: by block, or by time.
 *
 * Blocks appear only where there is work — a farm has dozens, and thirty empty
 * tiles would bury the four that matter. The time buckets are always all of
 * them, because they are a fixed vocabulary and "Today 0" is information a
 * scout wants: it is the difference between a clear day and a failed fetch.
 */
function GroupTiles({
  lang,
  items,
  groupBy,
  done,
  now,
  onOpen,
}: {
  lang: Lang;
  items: WorkItem[];
  groupBy: GroupBy;
  done: boolean;
  now: number;
  onOpen: (key: string) => void;
}): ReactNode {
  if (groupBy === "time") {
    const keys: (Bucket | DoneBucket)[] = done ? [...DONE_BUCKETS] : [...BUCKETS];
    const rowsIn = (k: Bucket | DoneBucket): WorkItem[] =>
      items.filter((i) => (done ? doneBucketOf(i, now) : bucketOf(i, now)) === k);
    // Board work carries no closure time and would otherwise vanish from the
    // Done list entirely. Its bucket is shown only when it holds something,
    // because on most farms it never will.
    const undated = done ? rowsIn("doneUnknown") : [];
    return (
      <div className="tiles">
        {keys.map((k) => {
          const rows = rowsIn(k);
          return (
            <Tile
              key={k}
              label={t(lang, BUCKET_LABEL[k])}
              count={rows.length}
              tone={k === "overdue" && rows.length > 0 ? "crit" : tileTone(rows, now, done)}
              onOpen={() => onOpen(k)}
            />
          );
        })}
        {undated.length > 0 ? (
          <Tile
            label={t(lang, BUCKET_LABEL.doneUnknown)}
            count={undated.length}
            tone=""
            onOpen={() => onOpen("doneUnknown")}
          />
        ) : null}
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
  const ordered = [...groups.entries()].sort(([ka, a], [kb, b]) => {
    if (ka === "") return 1;
    if (kb === "") return -1;
    return soonestIn(a) - soonestIn(b);
  });

  return (
    <div className="tiles">
      {ordered.map(([key, rows]) => (
        <Tile
          key={key || "none"}
          label={key || t(lang, "group.noBlock")}
          count={rows.length}
          tone={tileTone(rows, now, done)}
          onOpen={() => onOpen(key)}
        />
      ))}
    </div>
  );
}
