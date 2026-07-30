import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { deleteImportBatch, listImportBatches, type ImportBatch } from "@/api/signals";
import { useCapability } from "@/rbac/useCapability";
import { Card } from "@/components/Card";
import { Table, Tbody, Td, Th, Thead, Tr } from "@/components/Table";

interface Props {
  farmId: string;
}

/**
 * CS-7 import history — lists past CSV uploads for the active farm and
 * lets a user with signal.delete_observation undo any of them (delete
 * every observation the upload created).
 *
 * Sits under the CSV-import widget on the Signals Log page. Hidden when
 * the farm has no uploads yet (the empty list renders nothing) so it
 * doesn't add noise for farms that have never imported.
 */
export function ImportHistory({ farmId }: Props): ReactNode {
  const { t } = useTranslation("signals");
  const queryClient = useQueryClient();
  const canDelete = useCapability("signal.delete_observation", { farmId });

  const { data: batches, isLoading } = useQuery({
    queryKey: ["signals", "import-batches", farmId],
    queryFn: () => listImportBatches(farmId),
  });

  const deleteMutation = useMutation({
    mutationFn: (batchId: string) => deleteImportBatch(batchId, farmId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["signal_observations"] });
      void queryClient.invalidateQueries({ queryKey: ["labs/map/signalObservations"] });
      void queryClient.invalidateQueries({ queryKey: ["signals", "import-batches", farmId] });
    },
  });

  // Nothing to show until at least one upload exists.
  if (isLoading || !batches || batches.length === 0) {
    return null;
  }

  return (
    <Card noPadding className="p-4">
      <header className="mb-2">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-ap-muted">
          {t("importHistory.title", { defaultValue: "Import history" })}
        </h2>
        <p className="mt-1 text-xs text-ap-muted">
          {t("importHistory.subtitle", {
            defaultValue:
              "Past CSV uploads for this farm. Deleting one removes every record it created.",
          })}
        </p>
      </header>

      <Table>
        <Thead>
          <Tr>
            <Th scope="col" className="px-2 py-1">
              {t("importHistory.col.importedAt", { defaultValue: "Imported" })}
            </Th>
            <Th scope="col" className="px-2 py-1">
              {t("importHistory.col.rowCount", { defaultValue: "Records" })}
            </Th>
            <Th scope="col" className="px-2 py-1">
              {t("importHistory.col.signals", { defaultValue: "Signals" })}
            </Th>
            {canDelete ? <Th scope="col" className="px-2 py-1" /> : null}
          </Tr>
        </Thead>
        <Tbody>
          {batches.map((batch: ImportBatch) => (
            <Tr key={batch.import_batch_id} className="border-ap-line/60 align-top">
              <Td className="px-2 py-1 text-ap-ink">{formatImportedAt(batch.imported_at)}</Td>
              <Td className="px-2 py-1 tabular-nums text-ap-ink">{batch.row_count}</Td>
              <Td className="px-2 py-1">{batch.signal_codes.join(", ")}</Td>
              {canDelete ? (
                <Td className="px-2 py-1 text-end">
                  <button
                    type="button"
                    disabled={deleteMutation.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          t("importHistory.deleteConfirm", {
                            count: batch.row_count,
                            defaultValue:
                              "Delete all {{count}} records from this import? This cannot be undone.",
                          }),
                        )
                      ) {
                        deleteMutation.mutate(batch.import_batch_id);
                      }
                    }}
                    className="rounded border border-ap-crit/40 px-2 py-1 font-medium text-ap-crit hover:bg-ap-crit-soft disabled:opacity-50"
                  >
                    {t("importHistory.delete", { defaultValue: "Delete" })}
                  </button>
                </Td>
              ) : null}
            </Tr>
          ))}
        </Tbody>
      </Table>

      {deleteMutation.isError ? (
        <p
          role="alert"
          className="mt-2 rounded-md border border-ap-crit/30 bg-ap-crit-soft p-2 text-xs text-ap-crit"
        >
          {t("importHistory.deleteError", { defaultValue: "Could not delete this import." })}
        </p>
      ) : null}
    </Card>
  );
}

function formatImportedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}
