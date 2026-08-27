// Write orchestration for Farm Console v2 — create, reshape, inactivate.
//
// Transcribed from modules/labs/mapnext/FarmConsolePage.tsx @ 7b7f7ba0.
// Before touching this file, run:
//   git log --oneline 7b7f7ba0..HEAD -- src/modules/labs/mapnext/FarmConsolePage.tsx
// and port anything you find. Both copies die when v1 is deleted at cutover.
//
// This half has no v2-specific behaviour at all — it is pure duplication and
// therefore the half genuinely at risk of drifting. The panels it drives
// (createFlows, BulkAoiUploadPanel, InactivateConfirmModal) are imported from
// the live module unchanged, so a fix inside any of THEM reaches both
// consoles; only this wiring is doubled.
import { useCallback, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import type { FeatureCollection, Polygon } from "geojson";

import {
  autoGrid,
  createBlock,
  createPivot,
  getBlock,
  getBlockInactivationPreview,
  inactivateBlock,
  updateBlock,
  type AutoGridCandidate,
  type BlockDetail,
} from "@/api/blocks";
import { getFarmInactivationPreview, inactivateFarm, reactivateFarm } from "@/api/farms";
import type { BulkPreviewProps, DrawProgress } from "../map/MapCanvas";
import { CONSOLE_QK, isConsoleQueryKey } from "./constants";

interface Args {
  farmId: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDeselect: () => void;
  flash: (msg: string) => void;
}

export function useConsoleMutations({ farmId, selectedId, onSelect, onDeselect, flash }: Args) {
  const { t } = useTranslation("farmConsole");
  const qc = useQueryClient();

  // Invalidate everything this module owns. Blanket rather than surgical:
  // a write can touch the summary, the detail and the grid at once, and a
  // missed key reads to the user as "the save didn't work".
  const invalidateAll = useCallback(() => {
    void qc.invalidateQueries({ predicate: (q) => isConsoleQueryKey(q.queryKey) });
  }, [qc]);

  // ---- reshape -------------------------------------------------------------
  const [reshapeTarget, setReshapeTarget] = useState<BlockDetail | null>(null);
  const [reshapeCandidate, setReshapeCandidate] = useState<Polygon | null>(null);
  const [resetKey, setResetKey] = useState(0);

  const openReshape = useCallback(async () => {
    if (!selectedId) return;
    try {
      const block = await getBlock(selectedId);
      setReshapeTarget(block);
      setReshapeCandidate(null);
      flash(t("page.reshapeHint"));
    } catch {
      /* noop — the banner simply never opens */
    }
  }, [selectedId, flash, t]);

  const cancelReshape = useCallback(() => {
    setReshapeTarget(null);
    setReshapeCandidate(null);
  }, []);

  const reshapeMut = useMutation({
    mutationFn: ({ blockId, boundary }: { blockId: string; boundary: Polygon }) =>
      updateBlock(blockId, { boundary }),
    onSuccess: () => {
      invalidateAll();
      setReshapeTarget(null);
      setReshapeCandidate(null);
      setResetKey((k) => k + 1);
    },
  });

  // ---- inactivate block ----------------------------------------------------
  const [inactivateOpen, setInactivateOpen] = useState(false);
  const inactivatePreviewQ = useQuery({
    queryKey: CONSOLE_QK.inactivatePreview(selectedId),
    queryFn: () => getBlockInactivationPreview(selectedId as string),
    enabled: Boolean(inactivateOpen && selectedId),
  });
  const inactivateMut = useMutation({
    mutationFn: ({ blockId, reason }: { blockId: string; reason: string }) =>
      inactivateBlock(blockId, { reason }),
    onSuccess: () => {
      invalidateAll();
      setInactivateOpen(false);
      onDeselect();
    },
  });

  // ---- inactivate / reactivate farm ---------------------------------------
  const [inactivateFarmOpen, setInactivateFarmOpen] = useState(false);
  const farmInactivatePreviewQ = useQuery({
    queryKey: CONSOLE_QK.farmInactivatePreview(farmId),
    queryFn: () => getFarmInactivationPreview(farmId),
    enabled: inactivateFarmOpen,
  });
  const inactivateFarmMut = useMutation({
    mutationFn: (reason: string) => inactivateFarm(farmId, { reason }),
    onSuccess: () => {
      invalidateAll();
      setInactivateFarmOpen(false);
      onDeselect();
      flash(t("dangerZone.inactivated"));
    },
  });
  const reactivateFarmMut = useMutation({
    mutationFn: () => reactivateFarm(farmId, { restore_blocks: true }),
    onSuccess: () => {
      invalidateAll();
      flash(t("dangerZone.reactivated"));
    },
  });

  // ---- native create flows -------------------------------------------------
  const [drawTarget, setDrawTarget] = useState<"block" | "pivot" | null>(null);
  const [drawProgress, setDrawProgress] = useState<DrawProgress | null>(null);
  const [pendingBlock, setPendingBlock] = useState<{ polygon: Polygon; areaM2: number } | null>(
    null,
  );
  const [pendingPivot, setPendingPivot] = useState<{
    lat: number;
    lon: number;
    radiusM: number;
  } | null>(null);

  // Auto-block. The per-block area cap is held canonically in m²; the panel
  // renders it in the user's preferred unit.
  const [autoOpen, setAutoOpen] = useState(false);
  const [maxAreaM2, setMaxAreaM2] = useState(40_000); // ≈ a 200 m cell
  const [autoCellSizeM, setAutoCellSizeM] = useState<number | null>(null);
  const [candidates, setCandidates] = useState<AutoGridCandidate[] | null>(null);
  const [selectedCandidates, setSelectedCandidates] = useState<Set<string>>(new Set());
  const [autoComputing, setAutoComputing] = useState(false);
  const [autoCreating, setAutoCreating] = useState(false);
  const [autoCreatedCount, setAutoCreatedCount] = useState<number | null>(null);
  const [autoError, setAutoError] = useState<string | null>(null);

  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkPreviewFc, setBulkPreviewFc] = useState<FeatureCollection<
    Polygon,
    BulkPreviewProps
  > | null>(null);

  const resetCreate = useCallback(() => {
    setDrawTarget(null);
    setDrawProgress(null);
    setPendingBlock(null);
    setPendingPivot(null);
  }, []);
  const closeAuto = useCallback(() => {
    setAutoOpen(false);
    setCandidates(null);
    setSelectedCandidates(new Set());
    setAutoError(null);
    setAutoCreatedCount(null);
    setAutoCellSizeM(null);
  }, []);
  const closeBulk = useCallback(() => {
    setBulkOpen(false);
    setBulkPreviewFc(null);
  }, []);

  const startDrawBlock = useCallback(() => {
    closeAuto();
    closeBulk();
    setReshapeTarget(null);
    setPendingPivot(null);
    setPendingBlock(null);
    setDrawTarget("block");
  }, [closeAuto, closeBulk]);
  const startDrawPivot = useCallback(() => {
    closeAuto();
    closeBulk();
    setReshapeTarget(null);
    setPendingBlock(null);
    setPendingPivot(null);
    setDrawTarget("pivot");
  }, [closeAuto, closeBulk]);
  const startAutoBlock = useCallback(() => {
    resetCreate();
    setReshapeTarget(null);
    closeBulk();
    setAutoOpen(true);
  }, [resetCreate, closeBulk]);
  const startBulkUpload = useCallback(() => {
    resetCreate();
    setReshapeTarget(null);
    closeAuto();
    setBulkOpen(true);
  }, [resetCreate, closeAuto]);

  const createBlockMut = useMutation({
    mutationFn: ({
      polygon,
      code,
      name,
      name_ar,
    }: {
      polygon: Polygon;
      code: string;
      name: string;
      name_ar: string | null;
    }) =>
      createBlock(farmId, {
        code,
        name: name || null,
        name_ar,
        boundary: polygon,
        unit_type: "block",
      }),
    onSuccess: (newBlock) => {
      invalidateAll();
      resetCreate();
      onSelect(newBlock.id);
      flash(t("create.blockCreated"));
    },
  });

  const createPivotMut = useMutation({
    mutationFn: ({
      lat,
      lon,
      radiusM,
      code,
      name,
      name_ar,
      sectorCount,
    }: {
      lat: number;
      lon: number;
      radiusM: number;
      code: string;
      name: string;
      name_ar: string | null;
      sectorCount: number;
    }) =>
      createPivot(farmId, {
        code,
        name: name || null,
        name_ar,
        center: { lat, lon },
        radius_m: radiusM,
        sector_count: sectorCount,
      }),
    onSuccess: (result) => {
      invalidateAll();
      resetCreate();
      onSelect(result.pivot.id);
      flash(t("create.pivotCreated"));
    },
  });

  const computeAutoGrid = useCallback(async () => {
    setAutoComputing(true);
    setAutoError(null);
    setAutoCreatedCount(null);
    try {
      const res = await autoGrid(farmId, { maxAreaM2 });
      setAutoCellSizeM(res.cell_size_m);
      setCandidates(res.candidates);
      setSelectedCandidates(new Set(res.candidates.map((c) => c.code)));
    } catch (err) {
      setAutoError(err instanceof Error ? err.message : String(err));
    } finally {
      setAutoComputing(false);
    }
  }, [farmId, maxAreaM2]);

  const commitAutoBlock = useCallback(async () => {
    if (!candidates) return;
    const chosen = candidates.filter((c) => selectedCandidates.has(c.code));
    setAutoCreating(true);
    setAutoError(null);
    setAutoCreatedCount(0);
    try {
      let done = 0;
      for (const c of chosen) {
        await createBlock(farmId, {
          code: c.code,
          name: c.code,
          boundary: c.boundary,
          unit_type: "block",
        });
        done += 1;
        setAutoCreatedCount(done);
      }
      invalidateAll();
      closeAuto();
      flash(t("autoBlock.created", { n: chosen.length }));
    } catch (err) {
      setAutoError(err instanceof Error ? err.message : String(err));
    } finally {
      setAutoCreating(false);
    }
  }, [candidates, selectedCandidates, farmId, invalidateAll, closeAuto, flash, t]);

  const toggleCandidate = useCallback((code: string) => {
    setSelectedCandidates((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }, []);
  const toggleAllCandidates = useCallback(
    (all: boolean) => {
      setSelectedCandidates(all ? new Set((candidates ?? []).map((c) => c.code)) : new Set());
    },
    [candidates],
  );

  return {
    invalidateAll,
    // reshape
    reshapeTarget,
    reshapeCandidate,
    setReshapeCandidate,
    openReshape,
    cancelReshape,
    reshapeMut,
    resetKey,
    // inactivate
    inactivateOpen,
    setInactivateOpen,
    inactivatePreviewQ,
    inactivateMut,
    inactivateFarmOpen,
    setInactivateFarmOpen,
    farmInactivatePreviewQ,
    inactivateFarmMut,
    reactivateFarmMut,
    // create
    drawTarget,
    drawProgress,
    setDrawProgress,
    pendingBlock,
    setPendingBlock,
    pendingPivot,
    setPendingPivot,
    resetCreate,
    startDrawBlock,
    startDrawPivot,
    startAutoBlock,
    startBulkUpload,
    createBlockMut,
    createPivotMut,
    // auto-grid
    autoOpen,
    closeAuto,
    maxAreaM2,
    setMaxAreaM2,
    autoCellSizeM,
    candidates,
    selectedCandidates,
    toggleCandidate,
    toggleAllCandidates,
    autoComputing,
    autoCreating,
    autoCreatedCount,
    autoError,
    computeAutoGrid,
    commitAutoBlock,
    // bulk
    bulkOpen,
    closeBulk,
    bulkPreviewFc,
    setBulkPreviewFc,
  };
}
