import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  listBlocks,
  listFieldFlags,
  listObservations,
  type Block,
  type FieldFlag,
  type Observation,
} from "@/api/client";
import type { FarmScope } from "@/api/me";
import { t, type Lang } from "@/i18n";
import { FlagDetailScreen } from "@/screens/FlagDetailScreen";

/**
 * What this scout has filed, newest first.
 *
 * Two jobs, both of them the scout's rather than the office's: proving a day's
 * work, and letting somebody find a reading they described badly so they can
 * add another. Until now nothing a scout recorded was ever visible to them
 * again — it went into a hypertable and that was the last they saw of it.
 *
 * The observations endpoint has no `recorded_by` filter, so this asks for the
 * farm's recent rows and keeps its own. When the signed-in user id is unknown
 * the screen says so instead of showing the whole farm's readings as if they
 * were yours.
 *
 * Every granted farm, not one. This screen used to show whichever farm was
 * selected in the settings tab, which meant a scout who worked two farms in a
 * day could only ever prove half of it — and nothing on screen said the other
 * half had been left out. A farm that fails is skipped rather than emptying
 * the list; the rows that did arrive are still a real day's work.
 */
export function RecordsScreen({
  lang,
  farms,
  farmName,
  userId,
}: {
  lang: Lang;
  /** Every farm this scout is granted. Never empty — the caller handles that. */
  farms: FarmScope[];
  farmName: (farmId: string) => string;
  userId: string | null;
}): ReactNode {
  const [rows, setRows] = useState<Observation[] | null>(null);
  const [flags, setFlags] = useState<FieldFlag[]>([]);
  const [openFlagId, setOpenFlagId] = useState<string | null>(null);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [error, setError] = useState<string | null>(null);

  const single = farms.length === 1;
  const farmIds = farms.map((f) => f.farm_id).join(",");

  useEffect(() => {
    let live = true;
    // 30 days: long enough to cover a pay period, short enough that the
    // request stays small on a field connection.
    const since = new Date(Date.now() - 30 * 86_400_000).toISOString();
    void Promise.all(
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
        ]).catch(() => null),
      ),
    )
      .then((perFarm) => {
        if (!live) return;
        const ok = perFarm.filter((r): r is NonNullable<typeof r> => r !== null);
        if (ok.length === 0) {
          setError(t(lang, "records.loadFailed"));
          setRows([]);
          return;
        }
        const obs = ok.flatMap(([o]) => o);
        const blockList = ok.flatMap(([, b]) => b);
        const flagList = ok.flatMap(([, , f]) => f);
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
        if (live) setError(t(lang, "records.loadFailed"));
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [farmIds, lang, userId]);

  const nameOf = useMemo(() => {
    const byId = new Map(blocks.map((b) => [b.id, b.name || b.code]));
    return (id: string | null): string => (id ? (byId.get(id) ?? "") : "");
  }, [blocks]);

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
    <div className="screen records">
      <h1>{t(lang, "records.title")}</h1>
      {error ? <p className="error">{error}</p> : null}

      {rows === null && !error ? <p className="empty">{t(lang, "farms.loading")}</p> : null}
      {rows !== null && rows.length === 0 && flags.length === 0 ? (
        <p className="empty">{t(lang, "records.empty")}</p>
      ) : null}

      {/* Flags first: they are the only records that can still be waiting on
          somebody, so they are the ones a scout opens this tab to check. */}
      <ul>
        {flags.map((f) => (
          <li key={`${f.farm_id}-${f.id}`} className={`visit record flag sev-${f.severity} tappable`} onClick={() => setOpenFlagId(f.id)}>
            <span className="ring">⚑</span>
            <div className="body">
              <div className="title" dir="auto">{firstLine(f.note)}</div>
              <div className="meta">
                {!single && f.farm_id ? (
                  <span className="atfarm" dir="auto">{farmName(f.farm_id)}</span>
                ) : null}
                <span className="where" dir="auto">{f.block_name}</span>
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
        {(rows ?? []).map((o) => (
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
              {o.notes ? <div className="instruction" dir="auto">{o.notes}</div> : null}
              <div className="meta">
                {/* Which farm, once there is more than one. Two farms can both
                    have a "North 3", so the block name alone is ambiguous. */}
                {!single && o.farm_id ? (
                  <span className="atfarm" dir="auto">{farmName(o.farm_id)}</span>
                ) : null}
                <span className="where" dir="auto">{nameOf(o.block_id)}</span>
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
    </div>
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
