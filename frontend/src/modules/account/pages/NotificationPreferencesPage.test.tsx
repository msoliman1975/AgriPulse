import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setupTestI18n } from "@/i18n/testing";

import { NotificationPreferencesPage } from "./NotificationPreferencesPage";

const fetchMyNotificationPreferences = vi.fn();
const patchMyNotificationPreferences = vi.fn();

vi.mock("@/api/notificationPreferences", async () => {
  const actual = await vi.importActual<typeof import("@/api/notificationPreferences")>(
    "@/api/notificationPreferences",
  );
  return {
    ...actual,
    fetchMyNotificationPreferences: () => fetchMyNotificationPreferences(),
    patchMyNotificationPreferences: (p: unknown) => patchMyNotificationPreferences(p),
  };
});

const ALL_DELIVERABLE = [
  { channel: "in_app", deliverable: true, reason: null },
  { channel: "email", deliverable: true, reason: null },
  { channel: "push", deliverable: true, reason: null },
];

function prefs(over: Record<string, unknown> = {}) {
  return {
    channels: ["in_app", "email"],
    language: "en",
    email_address: "mohamed@example.com",
    registered_device_count: 1,
    tenant_channels: ["in_app", "email", "push"],
    availability: ALL_DELIVERABLE,
    ...over,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NotificationPreferencesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NotificationPreferencesPage", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await setupTestI18n();
    fetchMyNotificationPreferences.mockResolvedValue(prefs());
    patchMyNotificationPreferences.mockImplementation((p: { channels?: string[] }) =>
      Promise.resolve(prefs({ channels: p.channels ?? ["in_app", "email"] })),
    );
  });

  it("shows the stored choice, ticked", async () => {
    renderPage();
    const inApp = await screen.findByRole("checkbox", { name: /in the app/i });
    expect(inApp).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /email/i })).toBeChecked();
    // Not chosen, so not ticked — even though the tenant allows it.
    expect(screen.getByRole("checkbox", { name: /phone notification/i })).not.toBeChecked();
  });

  it("shows the address email will go to", async () => {
    renderPage();
    expect(await screen.findByText(/mohamed@example\.com/)).toBeInTheDocument();
  });

  it("keeps Save disabled until something changes", async () => {
    renderPage();
    const save = await screen.findByRole("button", { name: /save changes/i });
    expect(save).toBeDisabled();

    await userEvent.click(screen.getByRole("checkbox", { name: /phone notification/i }));
    expect(save).toBeEnabled();
  });

  it("sends the whole channel list on save", async () => {
    renderPage();
    await screen.findByRole("checkbox", { name: /in the app/i });
    await userEvent.click(screen.getByRole("checkbox", { name: /phone notification/i }));
    await userEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(patchMyNotificationPreferences).toHaveBeenCalledTimes(1));
    expect(patchMyNotificationPreferences).toHaveBeenCalledWith({
      channels: ["in_app", "email", "push"],
      language: "en",
    });
  });

  it("lets a person turn everything off, and says what that means", async () => {
    renderPage();
    await userEvent.click(await screen.findByRole("checkbox", { name: /in the app/i }));
    await userEvent.click(screen.getByRole("checkbox", { name: /email/i }));

    // Not an error — a real choice. But the consequence is stated.
    expect(screen.getByText(/will not be notified at all/i)).toBeInTheDocument();
    expect(screen.getByText(/still open in the action center/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save changes/i })).toBeEnabled();
  });

  it("explains a ticked channel the organisation has switched off", async () => {
    fetchMyNotificationPreferences.mockResolvedValue(
      prefs({
        tenant_channels: ["in_app"],
        availability: [
          { channel: "in_app", deliverable: true, reason: null },
          { channel: "email", deliverable: false, reason: "tenant_disabled" },
          { channel: "push", deliverable: false, reason: "tenant_disabled" },
        ],
      }),
    );
    renderPage();
    // Email is ticked but cannot deliver: the row has to say so, or the page
    // is lying about what will arrive.
    expect(await screen.findByText(/organisation has this channel switched off/i)).toBeVisible();
  });

  it("does not nag about a channel that is off anyway", async () => {
    fetchMyNotificationPreferences.mockResolvedValue(
      prefs({
        channels: ["in_app"],
        availability: [
          { channel: "in_app", deliverable: true, reason: null },
          { channel: "email", deliverable: false, reason: "tenant_disabled" },
          { channel: "push", deliverable: false, reason: "no_registered_device" },
        ],
      }),
    );
    renderPage();
    await screen.findByRole("checkbox", { name: /in the app/i });
    expect(screen.queryByText(/organisation has this channel switched off/i)).toBeNull();
  });

  it("says no phone is signed in rather than promising a push", async () => {
    fetchMyNotificationPreferences.mockResolvedValue(
      prefs({
        channels: ["in_app", "push"],
        registered_device_count: 0,
        availability: [
          { channel: "in_app", deliverable: true, reason: null },
          { channel: "email", deliverable: true, reason: null },
          { channel: "push", deliverable: false, reason: "no_registered_device" },
        ],
      }),
    );
    renderPage();
    expect(await screen.findByText(/no phone is signed in/i)).toBeVisible();
  });

  it("sends the notification language when it changes", async () => {
    renderPage();
    const select = await screen.findByLabelText(/language of your notifications/i);
    await userEvent.selectOptions(select, "ar");
    await userEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(patchMyNotificationPreferences).toHaveBeenCalledTimes(1));
    expect(patchMyNotificationPreferences).toHaveBeenCalledWith({
      channels: ["in_app", "email"],
      language: "ar",
    });
  });

  it("surfaces a failed save instead of pretending it worked", async () => {
    patchMyNotificationPreferences.mockRejectedValue(new Error("boom"));
    renderPage();
    await userEvent.click(await screen.findByRole("checkbox", { name: /phone notification/i }));
    await userEvent.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByText(/could not save/i)).toBeVisible();
  });

  it("offers a retry when the load fails", async () => {
    fetchMyNotificationPreferences.mockRejectedValue(new Error("nope"));
    renderPage();
    expect(await screen.findByText(/could not load your notification settings/i)).toBeVisible();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
