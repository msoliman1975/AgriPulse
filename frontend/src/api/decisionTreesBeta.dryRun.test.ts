// What the Beta designer's dry run asks the server for.
//
// Left without a version, the server walks the PUBLISHED version whenever a
// tree has one. The designer edits and saves the newest version, so a tree
// published once and changed since was dry-run (and its blocks judged for
// targeting) against the old body while the panel said "the draft". These
// pin the version onto both requests.

import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "./client";
import { betaDryRun, listDryRunBlocks } from "./decisionTreesBeta";

const get = vi.spyOn(apiClient, "get");
const post = vi.spyOn(apiClient, "post");

describe("beta dry run requests", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    get.mockResolvedValue({ data: [] });
    post.mockResolvedValue({ data: { cells: [] } });
  });

  it("walks the version it is handed", async () => {
    await betaDryRun("t1", "b1", "v7");
    expect(post).toHaveBeenCalledWith("/v1/platform/decision-trees/beta/t1/dry-run", {
      block_id: "b1",
      version_id: "v7",
    });
  });

  it("sends a null version when there is none, leaving the choice to the server", async () => {
    await betaDryRun("t1", "b1");
    expect(post.mock.calls[0][1]).toEqual({ block_id: "b1", version_id: null });
  });

  it("judges the picker's blocks against the same version", async () => {
    await listDryRunBlocks("t1", "v7");
    expect(get).toHaveBeenCalledWith("/v1/platform/decision-trees/beta/t1/dry-run/blocks", {
      params: { version_id: "v7" },
    });
  });
});
