/**
 * Every compiler rejection, named by node and linked to it.
 *
 * Section 8: "A publish check that lists every path that does not reach
 * `stop`, naming the node." The list is not a summary — one row per rejection,
 * each row a button that selects that node on the canvas, so the author moves
 * from the message to the thing that produced it in one click.
 *
 * The publish button lives here too and is disabled while any rejection
 * stands. Nothing in this panel is a warning: the engine refuses the version,
 * so offering a publish would be offering something the API will reject.
 */

import { useTranslation } from "react-i18next";

import { Button } from "@/components/Button";
import { Card } from "@/components/Card";
import { StatusBanner } from "@/components/StatusBanner";

import type { CompileRejection } from "../lib/betaCompile";

interface PublishChecksPanelProps {
  rejections: readonly CompileRejection[];
  /** True while the authoritative check is in flight. */
  checking?: boolean;
  publishing?: boolean;
  canPublish: boolean;
  onCheck: () => void;
  onPublish: () => void;
  onSelectNode: (nodeId: string) => void;
  /** Set when a check or a publish failed for a reason that is not a
   *  rejection — a network error, a 403. */
  error?: string | null;
}

export function PublishChecksPanel({
  rejections,
  checking = false,
  publishing = false,
  canPublish,
  onCheck,
  onPublish,
  onSelectNode,
  error,
}: PublishChecksPanelProps): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  const blocked = rejections.length > 0;

  return (
    <Card
      title={t("publish.title")}
      actions={
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={onCheck} disabled={checking}>
            {checking ? t("publish.checking") : t("publish.run")}
          </Button>
          <Button
            size="sm"
            onClick={onPublish}
            // Blocked by a rejection, or by the caller's own rule (read-only
            // scope, unsaved draft). Either way the button cannot be pressed.
            disabled={blocked || publishing || !canPublish}
          >
            {publishing ? t("designer.publishing") : t("designer.publish")}
          </Button>
        </div>
      }
      bodyClassName="flex flex-col gap-3"
    >
      {error ? <StatusBanner kind="crit">{error}</StatusBanner> : null}
      {blocked ? (
        <p className="text-sm font-medium text-ap-crit" role="status">
          {t("publish.blocked", { count: rejections.length })}
        </p>
      ) : (
        <p className="text-sm text-ap-primary" role="status">
          {t("publish.clean")}
        </p>
      )}
      {blocked ? (
        <ul className="divide-y divide-ap-line rounded-lg border border-ap-line">
          {rejections.map((rejection, index) => (
            <li key={`${rejection.rule}-${rejection.node_id ?? "doc"}-${index}`}>
              <RejectionRow rejection={rejection} onSelectNode={onSelectNode} />
            </li>
          ))}
        </ul>
      ) : null}
    </Card>
  );
}

function RejectionRow({
  rejection,
  onSelectNode,
}: {
  rejection: CompileRejection;
  onSelectNode: (nodeId: string) => void;
}): JSX.Element {
  const { t } = useTranslation("decisionTreesBeta");
  // A rule this frontend has no copy for falls back to the backend's own
  // English detail rather than rendering the key.
  const message = t(`publish.rule.${rejection.rule}`, {
    ...(rejection.params ?? {}),
    defaultValue: rejection.detail,
  });

  const body = (
    <span className="flex flex-col items-start gap-0.5 text-start">
      <span className="text-sm text-ap-ink">{message}</span>
      <span dir="ltr" className="font-mono text-meta text-ap-muted">
        {rejection.node_id ?? t("publish.documentLevel")} · {rejection.rule}
      </span>
    </span>
  );

  if (!rejection.node_id) {
    return <div className="px-3 py-2">{body}</div>;
  }
  return (
    <button
      type="button"
      onClick={() => onSelectNode(rejection.node_id!)}
      aria-label={t("publish.goToNode", { node: rejection.node_id })}
      className="w-full px-3 py-2 hover:bg-ap-line/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ap-primary"
    >
      {body}
    </button>
  );
}
