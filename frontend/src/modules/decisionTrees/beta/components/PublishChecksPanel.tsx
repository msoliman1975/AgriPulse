/**
 * What the server said, and what this screen noticed.
 *
 * Two lists, and they are not the same kind of thing:
 *
 *   * **Errors** come from the server's compiler, as the `errors` array of a
 *     422 on the save or the publish that asked for them. They are the
 *     authority. While any of them stands the publish button is dead, because
 *     the API would refuse the version anyway.
 *   * **Hints** come from `beta/lib/betaCompile.ts`, running in the browser on
 *     every edit. They are advisory. They never disable anything: a hint that
 *     was wrong would otherwise lock an author out of a version the compiler
 *     would have taken.
 *
 * Section 8 asks the publish check to name the node. Every row that carries a
 * node id is a button that selects it on the canvas, so an author goes from
 * the sentence to the thing that produced it in one click.
 *
 * A server error carries its own English and Arabic text — the compiler writes
 * both, because this panel renders in either — so those rows are not
 * translated here. A hint is local copy and is.
 */

import { useTranslation } from "react-i18next";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { Pill } from "@/components/Pill";
import { StatusBanner } from "@/components/StatusBanner";
import type { BetaValidationError } from "@/api/decisionTreesBeta";

import type { EditorHint } from "../lib/betaCompile";

/** Whether the server has had a look at the body now on screen. */
export type ServerCheckState = "unchecked" | "accepted" | "refused";

interface PublishChecksPanelProps {
  /** The compiler's answer. Authoritative; blocks the publish. */
  errors: readonly BetaValidationError[];
  /** Whether the server has seen this exact body yet. */
  serverState: ServerCheckState;
  /** The browser's own reading. Advisory; blocks nothing. */
  hints: readonly EditorHint[];
  publishing?: boolean;
  /** The caller's own rule — read-only scope, unsaved draft, no version. */
  canPublish: boolean;
  onPublish: () => void;
  onSelectNode: (nodeId: string) => void;
  /** A failure that was not a compiler rejection — a network error, a 403. */
  error?: string | null;
}

export function PublishChecksPanel({
  errors,
  serverState,
  hints,
  publishing = false,
  canPublish,
  onPublish,
  onSelectNode,
  error,
}: PublishChecksPanelProps): JSX.Element {
  const { t, i18n } = useTranslation("decisionTreesBeta");
  const blocked = errors.length > 0;

  return (
    <Card
      title={t("publish.title")}
      actions={
        <Button size="sm" onClick={onPublish} disabled={blocked || publishing || !canPublish}>
          {publishing ? t("designer.publishing") : t("designer.publish")}
        </Button>
      }
      bodyClassName="flex flex-col gap-4"
    >
      {error ? <StatusBanner kind="crit">{error}</StatusBanner> : null}

      <section className="flex flex-col gap-2">
        {blocked ? (
          <>
            <p className="text-sm font-medium text-ap-crit" role="status">
              {t("publish.errorsTitle")} — {t("publish.errorsCount", { count: errors.length })}
            </p>
            <ul className="divide-y divide-ap-line rounded-lg border border-ap-crit/40">
              {errors.map((entry, index) => (
                <li key={`${entry.rule}-${entry.node_id ?? "doc"}-${index}`}>
                  <CheckRow
                    message={
                      i18n.language === "ar" && entry.message_ar
                        ? entry.message_ar
                        : entry.message_en
                    }
                    rule={entry.rule}
                    nodeId={entry.node_id}
                    otherNodeIds={entry.node_ids.slice(1)}
                    onSelectNode={onSelectNode}
                  />
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p
            className={
              serverState === "accepted" ? "text-sm text-ap-primary" : "text-sm text-ap-muted"
            }
            role="status"
          >
            {serverState === "accepted" ? t("publish.accepted") : t("publish.notChecked")}
          </p>
        )}
      </section>

      <section className="flex flex-col gap-2 border-t border-ap-line pt-3">
        <p className="flex items-center gap-2 text-sm font-medium text-ap-ink">
          {t("publish.hintsTitle")}
          {hints.length > 0 ? (
            <Pill kind="warn">{t("publish.hintsCount", { count: hints.length })}</Pill>
          ) : (
            <Pill kind="ok">{t("publish.hintsClean")}</Pill>
          )}
        </p>
        <p className="text-meta text-ap-muted">{t("publish.hintsHelp")}</p>
        {hints.length > 0 ? (
          <ul className="divide-y divide-ap-line rounded-lg border border-ap-line">
            {hints.map((hint, index) => (
              <li key={`${hint.messageKey}-${hint.node_id ?? "doc"}-${index}`}>
                <CheckRow
                  message={t(`publish.rule.${hint.messageKey}`, {
                    ...(hint.params ?? {}),
                    defaultValue: hint.detail,
                  })}
                  rule={hint.rule}
                  nodeId={hint.node_id}
                  otherNodeIds={[]}
                  onSelectNode={onSelectNode}
                />
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </Card>
  );
}

function CheckRow({
  message,
  rule,
  nodeId,
  otherNodeIds,
  onSelectNode,
}: {
  message: string;
  rule: string;
  nodeId: string | null;
  /** The rest of the nodes one error named. "A path ends without stop" can
   *  name several; the row links the first and lists the others. */
  otherNodeIds: readonly string[];
  onSelectNode: (nodeId: string) => void;
}): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");

  const body = (
    <span className="flex flex-col items-start gap-0.5 text-start">
      <span className="text-sm text-ap-ink">{message}</span>
      {/* Node ids and rule names are ASCII identifiers. Left to right in
          either interface language, or an id reads back to front. */}
      <span dir="ltr" className="font-mono text-meta text-ap-muted">
        {nodeId ?? t("publish.documentLevel")} · {rule}
        {otherNodeIds.length > 0 ? ` · +${otherNodeIds.join(", ")}` : ""}
      </span>
    </span>
  );

  if (!nodeId) {
    return <div className="px-3 py-2">{body}</div>;
  }
  return (
    <button
      type="button"
      onClick={() => onSelectNode(nodeId)}
      aria-label={t("publish.goToNode", { node: nodeId })}
      className="w-full px-3 py-2 hover:bg-ap-line/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ap-primary"
    >
      {body}
    </button>
  );
}
