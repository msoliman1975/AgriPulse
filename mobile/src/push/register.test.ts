import { beforeEach, describe, expect, it, vi } from "vitest";

const available = new Set<string>();
const pushConfig = { status: vi.fn() };
const push = {
  checkPermissions: vi.fn(async () => ({ receive: "granted" })),
  requestPermissions: vi.fn(),
  addListener: vi.fn(
    async (event: string, cb: (v: { value: string }) => void) => {
      if (event === "registration") queueMicrotask(() => cb({ value: "fcm-token" }));
      return { remove: vi.fn() };
    },
  ),
  register: vi.fn(async () => undefined),
};
const registerDevice = vi.fn(async () => undefined);

vi.mock("@capacitor/core", () => ({
  Capacitor: {
    isNativePlatform: () => true,
    isPluginAvailable: (name: string) => available.has(name),
  },
  registerPlugin: () => pushConfig,
}));
vi.mock("@capacitor/push-notifications", () => ({ PushNotifications: push }));
vi.mock("@/api/client", () => ({ registerDevice, revokeDevice: vi.fn() }));

/** A fresh module per test: the in-flight guard is module state. */
async function load() {
  vi.resetModules();
  return import("./register");
}

beforeEach(() => {
  vi.clearAllMocks();
  available.clear();
  available.add("PushNotifications");
});

describe("ensureDeviceRegistered", () => {
  // register() without Firebase throws natively and kills the app, so it must
  // never be reached on a build without google-services.json.
  it("never calls register() when the build has no Firebase config", async () => {
    available.add("PushConfig");
    pushConfig.status.mockResolvedValue({ firebaseConfigured: false });
    const { ensureDeviceRegistered } = await load();
    await ensureDeviceRegistered("farm-1");
    expect(push.register).not.toHaveBeenCalled();
    expect(push.requestPermissions).not.toHaveBeenCalled();
  });

  it("treats a missing PushConfig plugin as unconfigured", async () => {
    const { ensureDeviceRegistered } = await load();
    await ensureDeviceRegistered("farm-1");
    expect(pushConfig.status).not.toHaveBeenCalled();
    expect(push.register).not.toHaveBeenCalled();
  });

  it("registers the token when Firebase is configured", async () => {
    available.add("PushConfig");
    pushConfig.status.mockResolvedValue({ firebaseConfigured: true });
    const { ensureDeviceRegistered } = await load();
    await ensureDeviceRegistered("farm-1");
    expect(push.register).toHaveBeenCalledOnce();
    expect(registerDevice).toHaveBeenCalledWith("fcm-token", "farm-1");
  });
});
