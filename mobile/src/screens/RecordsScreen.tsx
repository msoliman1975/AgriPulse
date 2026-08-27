import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  listBlocks,
  listFieldFlags,
  listObservations,
  type Block,
  type FieldFlag,
  type Observation,
} from "@/api/client";
import type { FarmScope } from "@/api/me";
import { ALL_FARMS, FarmRail, type FarmCount } from "@/components/FarmRail";
import { HomeHeader } from "@/components/HomeHeader";
import { PullToRefresh } from "@/components/PullToRefresh";
import { t, type Lang } from "@/i18n";
import { FlagDetailScreen } from "@/screens/FlagDetailScreen";

/**
 * What this scout has filed, newest first.
 *
 * Two jobs, both of them the scout's rather than the office's: proving a day's
 * work, and letting somebody find a reading they described badly so they can
 * add another. Until the flag screen arrived, nothing a scout recorded was ever
 * visible to them again — it went into a hypertable and that was the last they
 * saw of it.
 *
 * The observations endpoint has no `recorded_by` filter, so this asks for the
 * farm's recent rows and keeps its own. When the signed-in user id is unknown
 * the screen says so instead of showing the whole farm's readings as if they
 * were yours.
 *
 * Every granted farm is loaded, and the **rail** decides which are shown — the
 * same control, in the same place, as on Tasks. This screen used to show
 * whichever farm was selected in a settings tab, which meant a scout who worked
 * two farms in a day could only ever prove half of it, with nothing on screen
 * saying the other half had been left out. A farm that fails is skipped rather
 * than emptying the list; the rows that did arrive are still a real day's work.
 */
export function RecordsScreen({
  lang,
  onLangChange,
  name,
  farms,
  farmName,
  farm,
  onFarmChange,
  onOpenAccount,
  userId,
}: {
  lang: Lang;
  onLangChange: (lang: Lang) => void;
  name: string | null;
  /** Every farm this scout is granted. Never empty — the caller handles that. */
  farms: FarmScope[];
  farmName: (farmId: string) => string;
  /** The rail's position: a farm id, or `ALL_FARMS`. */
  farm: string;
  onFarmChange: (farmId: string) => void;
  onOpenAccount: () => void;
  userId: string | null;
}): ReactNode {
  const [rows, setRows] = useState<Observation[] | null>(null);
  const [flags, setFlags] = useState<FieldFlag[]>([]);
  const [failed, setFailed] = useState<string[]>([]);
  const [openFlagId, setOpenFlagId] = useState<string | null>(null);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [error, setError] = useState<string | null>(null);
  // Mounted, and which fetch is the current one. Both are refs: neither is
  // rendered, and putting either in state would re-render the list to record
  // a fact about the fetch rather than about the data.
  const alive = useRef(true);
  const seq = useRef(0);

  const single = farms.length === 1 ? farms[0].farm_id : null;
  const current = single ?? farm;
  const farmIds = farms.map((f) => f.farm_id).join(",");

  /**
   * Fetch everything, once per farm.
   *
   * A named function rather than a body inside the effect, because the pull
   * gesture needs to run the same fetch and must be able to await it — the
   * spinner has to stop when the data lands, not on a timer.
   *
   * `seq` is what makes a stale response harmless. Two fetches can be in
   * flight at once now (a pull, and a farm gained mid-session), and the older
   * one finishing last would otherwise paint yesterday's rows over today's.
   */
  const load = useCallback(async (): Promise<void> => {
    const mine = ++seq.current;
    const fresh = (): boolean => alive.current && seq.current === mine;
    // 30 days: long enough to cover a pay period, short enough that the
    // request stays small on a field connection.
    const since = new Date(Date.now() - 30 * 86_400_000).toISOString();
    await Promise.all(
      farms.map((f) =>
        Promise.all([
          // Tagged here because the response does not carry it — see the
          // `farm_id` note on `Observation`.
          listObservations(f.farm_id, { since, limit: 200 }).then((rows) =>
            rows.map((o) => ({ ...o, farm_id: f.farm_id })),
          ),
          listBlocks(f.farm_id).catch(() => [] as Block[]),
          // Flags this scout raised. The endpoint returns the farm's, so the
          // filter is the same honest one the readings use.
          listFieldFlags(f.farm_id).catch(() => [] as FieldFlag[]),
        ])
          .then((r) => ({ farmId: f.farm_id, r }))
          .catch(() => ({ farmId: f.farm_id, r: null })),
      ),
    )
      .then((perFarm) => {
        if (!fresh()) return;
        const ok = perFarm.filter((p): p is { farmId: string; r: NonNullable<typeof p.r> } => p.r !== null);
        setFailed(perFarm.filter((p) => p.r === null).map((p) => p.farmId));
        if (ok.length === 0) {
          setError(t(lang, "records.loadFailed"));
          setRows([]);
          return;
        }
        // A pull that succeeds has to clear the last failure's message, or
        // the screen shows fresh rows under "could not load your records".
        setError(null);
        const obs = ok.flatMap(({ r }) => r[0]);
        const blockList = ok.flatMap(({ r }) => r[1]);
        const flagList = ok.flatMap(({ r }) => r[2]);
        setBlocks(blockList);
        // Newest first across farms — a day's work is one sequence to the
        // person who did it, whichever farm each row came from.
        setRows(
          (userId ? obs.filter((o) => o.recorded_by === userId) : obs).sort(
            (a, b) => new Date(b.time).getTime() - new Date(a.time).getTime(),
          ),
        );
        setFlags(userId ? flagList.filter((f) => f.raised_by === userId) : flagList);
      })
      .catch(() => {
        if (fresh()) setError(t(lang, "records.loadFailed"));
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [farmIds, lang, userId]);

  useEffect(() => {
    alive.current = true;
    void load();
    return () => {
      alive.current = false;
    };
  }, [load]);

  const nameOf = useMemo(() => {
    const byId = new Map(blocks.map((b) => [b.id, b.name || b.code]));
    return (id: string | null): string => (id ? (byId.get(id) ?? "") : "");
  }, [blocks]);

  /**
   * What each pill says here: how much this scout filed on that farm in the
   * window, which is what the list below is showing.
   *
   * **No tone.** The rail's colours mean work that is late or urgent, and
   * nothing in this list is owed to anybody — it is a receipt. Painting a pill
   * amber because a filed reading happened to carry a warning severity would
   * send a scout to a farm that needs nothing from them.
   */
  const counts = useMemo(() => {
    const out: Record<string, FarmCount> = {};
    for (const f of farms) {
      if (failed.includes(f.farm_id)) {
        out[f.farm_id] = { count: null, tone: "", failed: true };
      } else if (rows === null) {
        out[f.farm_id] = { count: null, tone: "" };
      } else {
        out[f.farm_id] = {
          count:
            rows.filter((o) => o.farm_id === f.farm_id).length +
            flags.filter((fl) => fl.farm_id === f.farm_id).length,
          tone: "",
        };
      }
    }
    return out;
  }, [farms, failed, rows, flags]);

  const shownFlags = current === ALL_FARMS ? flags : flags.filter((f) => f.farm_id === current);
  const shownRows = (rows ?? []).filter((o) => current === ALL_FARMS || o.farm_id === current);
  /** Only under "All farms" — otherwise the rail already said it, on every row. */
  const showFarm = current === ALL_FARMS;

  if (openFlagId) {
    return (
      <FlagDetailScreen
        lang={lang}
        flagId={openFlagId}
        meId={userId}
        onClose={() => setOpenFlagId(null)}
      />
    );
  }

  return (
    <PullToRefresh lang={lang} className="screen records" onRefresh={load}>
      {/* The same header as Tasks, so the name is the door to the account
          sheet in the same place on every screen. The old "My records" title
          said what the tab bar already said. */}
      <HomeHeader
        lang={lang}
        onLangChange={onLangChange}
        name={name}
        farmName={single ? farmName(single) : null}
        onOpenAccount={onOpenAccount}
      />

      <FarmRail
        lang={lang}
        farms={farms}
        farmName={farmName}
        value={current}
        counts={counts}
        onChange={onFarmChange}
      />

      {error ? <p className="error">{error}</p> : null}
      {failed.length > 0 ? (
        <p className="warnline">
          {t(lang, "tasks.someFarmsFailed")}
          <span className="which">{failed.map(farmName).join(" · ")}</span>
        </p>
      ) : null}

      {rows === null && !error ? <p className="empty">{t(lang, "farms.loading")}</p> : null}
      {rows !== null && shownRows.length === 0 && shownFlags.length === 0 ? (
        <p className="empty">{t(lang, "records.empty")}</p>
      ) : null}

      {/* Flags first: they are the only records that can still be waiting on
          somebody, so they are the ones a scout opens this tab to check. */}
      <ul>
        {shownFlags.map((f) => (
          <li
            key={`${f.farm_id}-${f.id}`}
            className={`visit record flag sev-${f.severity} tappable`}
            onClick={() => setOpenFlagId(f.id)}
          >
            <span className="ring">⚑</span>
            <div className="body">
              <div className="title" dir="auto">
                {firstLine(f.note)}
              </div>
              <div className="meta">
                {showFarm && f.farm_id ? (
                  <span className="atfarm" dir="auto">
                    {farmName(f.farm_id)}
                  </span>
                ) : null}
                <span className="where" dir="auto">
                  {f.block_name}
                </span>
                <span className="src">
                  {t(lang, f.status === "open" ? "flag.open" : "flag.closed")}
                  {f.comment_count > 0 ? ` · ${f.comment_count}` : ""}
                </span>
              </div>
            </div>
          </li>
        ))}
      </ul>

      <ul>
        {shownRows.map((o) => (
          <li key={`${o.farm_id}-${o.id}`} className="visit record">
            {o.attachment_download_url ? (
              <img className="thumb" src={o.attachment_download_url} alt="" />
            ) : (
              <span className="ring">{dayLabel(o.time)}</span>
            )}
            <div className="body">
              <div className="title">
                {o.signal_code}
                {readableValue(o) ? `: ${readableValue(o)}` : ""}
              </div>
              {o.notes ? (
                <div className="instruction" dir="auto">
                  {o.notes}
                </div>
              ) : null}
              <div className="meta">
                {/* Which farm, only when the list holds more than one. Two
                    farms can both have a "North 3", so the block name alone is
                    ambiguous — but with the rail on one farm the chip repeats
                    the same word on every row. */}
                {showFarm && o.farm_id ? (
                  <span className="atfarm" dir="auto">
                    {farmName(o.farm_id)}
                  </span>
                ) : null}
                <span className="where" dir="auto">
                  {nameOf(o.block_id)}
                </span>
                {/* The app's language, not the handset's. A phone set to
                    English rendering an Arabic screen's timestamps in Latin
                    digits and month names is the same two-typefaces problem
                    one layer up. */}
                <span className="src">{new Date(o.time).toLocaleString(lang)}</span>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </PullToRefresh>
  );
}

/** A flag's first line is its title everywhere it is listed. */
function firstLine(note: string): string {
  return note.split("\n")[0];
}

/** Day of the month, as a stand-in when a reading carries no photograph. */
function dayLabel(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : String(d.getDate());
}

function readableValue(o: Observation): string {
  if (o.value_numeric !== null) return String(o.value_numeric);
  return o.value_categorical ?? "";
}
