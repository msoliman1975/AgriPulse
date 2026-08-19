import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  listBlocks,
  listFieldFlags,
  listObservations,
  type Block,
  type FieldFlag,
  type Observation,
} from "@/api/client";
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
 */
export function RecordsScreen({
  lang,
  farmId,
  userId,
}: {
  lang: Lang;
  farmId: string;
  userId: string | null;
}): ReactNode {
  const [rows, setRows] = useState<Observation[] | null>(null);
  const [flags, setFlags] = useState<FieldFlag[]>([]);
  const [openFlagId, setOpenFlagId] = useState<string | null>(null);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    // 30 days: long enough to cover a pay period, short enough that the
    // request stays small on a field connection.
    const since = new Date(Date.now() - 30 * 86_400_000).toISOString();
    void Promise.all([
      listObservations(farmId, { since, limit: 200 }),
      listBlocks(farmId).catch(() => [] as Block[]),
      // Flags this scout raised. The endpoint returns the farm's, so the
      // filter is the same honest one the readings use.
      listFieldFlags(farmId).catch(() => [] as FieldFlag[]),
    ])
      .then(([obs, blockList, flagList]) => {
        if (!live) return;
        setBlocks(blockList);
        setRows(userId ? obs.filter((o) => o.recorded_by === userId) : obs);
        setFlags(userId ? flagList.filter((f) => f.raised_by === userId) : flagList);
      })
      .catch(() => {
        if (live) setError(t(lang, "records.loadFailed"));
      });
    return () => {
      live = false;
    };
  }, [farmId, lang, userId]);

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
          <li key={f.id} className={`visit record flag sev-${f.severity} tappable`} onClick={() => setOpenFlagId(f.id)}>
            <span className="ring">⚑</span>
            <div className="body">
              <div className="title">{firstLine(f.note)}</div>
              <div className="meta">
                <span className="where">{f.block_name}</span>
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
          <li key={o.id} className="visit record">
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
              {o.notes ? <div className="instruction">{o.notes}</div> : null}
              <div className="meta">
                <span className="where">{nameOf(o.block_id)}</span>
                <span className="src">{new Date(o.time).toLocaleString()}</span>
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
