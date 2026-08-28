import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { QueueTab } from "./QueueTab";

const listQueue = vi.hoisted(() => vi.fn());
const readQueueConfig = vi.hoisted(() => vi.fn());

vi.mock("@/api/integrationsHealth", async () => {
  const actual = await vi.importActual<typeof import("@/api/integrationsHealth")>(
    "@/api/integrationsHealth",
  );
  return {
    ...actual,
    listQueue: (...a: unknown[]) => listQueue(...a),
    readQueueConfig: (...a: unknown[]) => readQueueConfig(...a),
  };
});

function wrap(node: ReactNode): ReactNode {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe("QueueTab", () => {
  beforeEach(async () => {
    await setupTestI18n();
    listQueue.mockReset().mockResolvedValue([]);
    readQueueConfig.mockReset().mockResolvedValue({
      stuck_minutes: 45,
      weather_default_cadence_hours: 3,
      imagery_default_cadence_hours: 24,
    });
  });

  it("names the threshold the server used, not a number of its own", async () => {
    // The caption used to print a literal 30 while the server used its own
    // literal 30. A settings change would have left the caption naming a
    // threshold nothing ran with, so the test sets 45 to prove it is read.
    render(wrap(<QueueTab basePath="/v1" />));

    expect(await screen.findByText(/stuck after 45 minutes/i)).toBeInTheDocument();
    expect(screen.queryByText(/stuck after 30 minutes/i)).toBeNull();
  });
});
