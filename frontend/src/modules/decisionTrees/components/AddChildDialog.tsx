// Kind-picker for the "add child" flow (PR-D4).
//
// Author clicks a `+` port (canvas) or one of the Add Match / Add Miss
// buttons in NodeDetailsPanel; this dialog asks what kind of node to
// drop in. The viewer page handles the actual YAML mutation via
// `applyAddNode` so this stays a thin presentational layer.

import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Modal } from "@/components/Modal";

import type { NodeKind } from "../lib/treeStructure";

interface AddChildDialogProps {
  parentId: string;
  branch: "match" | "miss";
  /** Suggested id for the new node — the page derives this via
   *  `generateNodeId` so collisions are pre-avoided. */
  suggestedId: string;
  onSubmit: (kind: NodeKind, nodeId: string) => void;
  onCancel: () => void;
  /** Validation message from a failed submit (e.g. id collision).
   *  Cleared by the caller before the next attempt. */
  error?: string | null;
}

const KINDS: { value: NodeKind; labelKey: string; descKey: string }[] = [
  {
    value: "decision",
    labelKey: "editor.addChild.kindDecision",
    descKey: "editor.addChild.kindDecisionDesc",
  },
  {
    value: "leaf-recommendation",
    labelKey: "editor.addChild.kindRec",
    descKey: "editor.addChild.kindRecDesc",
  },
  {
    value: "leaf-alert",
    labelKey: "editor.addChild.kindAlert",
    descKey: "editor.addChild.kindAlertDesc",
  },
  {
    value: "leaf-noop",
    labelKey: "editor.addChild.kindNoop",
    descKey: "editor.addChild.kindNoopDesc",
  },
];

export function AddChildDialog({
  parentId,
  branch,
  suggestedId,
  onSubmit,
  onCancel,
  error,
}: AddChildDialogProps): ReactNode {
  const { t } = useTranslation("decisionTrees");
  const [kind, setKind] = useState<NodeKind>("decision");
  const [nodeId, setNodeId] = useState(suggestedId);

  // Rebase the suggested id when the kind changes so the prefix
  // matches — but only if the user hasn't typed their own override.
  useEffect(() => {
    // Detect "still the suggested id" by checking if the field still
    // starts with one of the known prefixes from generateNodeId. If the
    // author typed something custom, we leave it alone.
    const prefixes = ["decision_", "leaf_rec_", "leaf_alert_", "leaf_noop_"];
    const isStock = prefixes.some((p) => nodeId.startsWith(p));
    if (!isStock) return;
    // We can't re-call generateNodeId here without the doc; rely on the
    // caller to pass a fresh `suggestedId` when reopening. So just
    // swap the prefix portion locally.
    const newPrefix =
      kind === "decision"
        ? "decision_"
        : kind === "leaf-recommendation"
          ? "leaf_rec_"
          : kind === "leaf-alert"
            ? "leaf_alert_"
            : "leaf_noop_";
    const stockTail = nodeId.split("_").pop() ?? "1";
    setNodeId(`${newPrefix}${stockTail}`);
    // Intentionally omit `nodeId` from deps — we only want this to
    // fire on a kind change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  return (
    <Modal
      open
      onClose={onCancel}
      labelledBy="add-child-title"
      className="max-w-md"
    >
      <h2 id="add-child-title" className="text-base font-semibold text-ap-ink">
        {t("editor.addChild.title")}
      </h2>
      <p className="mt-1 text-xs text-ap-muted">
        {t("editor.addChild.scope", {
          parent: parentId,
          branch:
            branch === "match"
              ? t("editor.canvas.addMatch")
              : t("editor.canvas.addMiss"),
        })}
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit(kind, nodeId.trim());
        }}
        className="mt-4 flex flex-col gap-4"
      >
        <fieldset className="flex flex-col gap-2">
          <legend className="text-xs font-medium text-ap-muted">
            {t("editor.addChild.kind")}
          </legend>
          {KINDS.map((k) => (
            // eslint-disable-next-line jsx-a11y/label-has-associated-control -- wraps the radio input + i18n description text; jsx-a11y can't resolve t() as accessible text
            <label
              key={k.value}
              className="flex cursor-pointer items-start gap-2 rounded-md border border-ap-line bg-white p-2 hover:bg-ap-bg/40"
            >
              <input
                type="radio"
                name="kind"
                value={k.value}
                checked={kind === k.value}
                onChange={() => setKind(k.value)}
                className="mt-0.5"
              />
              <span className="flex-1 text-sm">
                <span className="block font-medium text-ap-ink">
                  {t(k.labelKey)}
                </span>
                <span className="block text-xs text-ap-muted">
                  {t(k.descKey)}
                </span>
              </span>
            </label>
          ))}
        </fieldset>

        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium text-ap-muted">
            {t("editor.addChild.nodeId")}
          </span>
          <input
            type="text"
            required
            pattern="^[A-Za-z0-9_][A-Za-z0-9_]*$"
            value={nodeId}
            onChange={(e) => setNodeId(e.target.value)}
            className="rounded-md border border-ap-line bg-white px-2 py-1.5 font-mono text-xs"
          />
          <span className="text-[11px] text-ap-muted">
            {t("editor.addChild.nodeIdHint")}
          </span>
        </label>

        {error ? <p className="text-xs text-ap-crit">{error}</p> : null}

        <div className="mt-2 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-sm text-ap-muted"
          >
            {t("editor.addChild.cancel")}
          </button>
          <button
            type="submit"
            disabled={!nodeId.trim()}
            className="rounded-md bg-ap-primary px-3 py-1.5 text-sm font-medium text-white hover:bg-ap-primary/90 disabled:opacity-60"
          >
            {t("editor.addChild.create")}
          </button>
        </div>
      </form>
    </Modal>
  );
}
