/** Investor app v2, PR 8: the Activities tab, in Arabic (RTL) and English. */
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@capacitor/preferences", () => ({ Preferences: {} }));
vi.mock("@/auth/session", () => ({ validAccessToken: async () => "token" }));

import type { Activity } from "@/api/client";
import { activityDay, activitySummary, newestFirst } from "@/logic/activities";
import { ActivityList, ActivityRow, activityTitle } from "@/screens/ActivitiesTab";

const act = (over: Partial<Activity> = {}): Activity => ({
  id: "a1",
  activity_type: "spraying",
  title: null,
  title_ar: null,
  scheduled_date: "2026-03-10",
  status: "upcoming",
  completed_at: null,
  photos: [],
  ...over,
});

describe("activity helpers", () => {
  it("counts completed activities and rounds the percent", () => {
    expect(
      activitySummary([act({ status: "completed" }), act({ id: "a2" }), act({ id: "a3", status: "in_progress" })]),
    ).toEqual({ done: 1, total: 3, pct: 33 });
    expect(activitySummary([])).toEqual({ done: 0, total: 0, pct: 0 });
  });

  it("shows a done activity on the day it was done", () => {
    expect(activityDay(act({ status: "completed", completed_at: "2026-03-12T09:00:00Z" }))).toBe("2026-03-12");
    expect(activityDay(act({ status: "completed", completed_at: null }))).toBe("2026-03-10");
    expect(activityDay(act({ completed_at: "2026-03-12T09:00:00Z" }))).toBe("2026-03-10");
  });

  it("puts the newest first, ties broken by id", () => {
    const list = [
      act({ id: "b", scheduled_date: "2026-01-01" }),
      act({ id: "a", scheduled_date: "2026-05-01" }),
      act({ id: "c", scheduled_date: "2026-01-01" }),
      act({ id: "d", scheduled_date: "2026-01-01", status: "completed", completed_at: "2026-06-01T08:00:00Z" }),
    ];
    expect(newestFirst(list).map((a) => a.id)).toEqual(["d", "a", "b", "c"]);
    expect(list[0].id).toBe("b");
  });

  it("titles an activity by its own title, else its type, else the raw type", () => {
    expect(activityTitle("en", act({ title: "Mildew spray", title_ar: "رش البياض" }))).toBe("Mildew spray");
    expect(activityTitle("ar", act({ title: "Mildew spray", title_ar: "رش البياض" }))).toBe("رش البياض");
    expect(activityTitle("ar", act({ title: "Mildew spray" }))).toBe("Mildew spray");
    expect(activityTitle("en", act())).toBe("Spraying");
    expect(activityTitle("ar", act({ activity_type: "growth_regulator" }))).toBe("منظم نمو");
    expect(activityTitle("en", act({ activity_type: "new_kind" }))).toBe("new_kind");
  });
});

describe("Activities tab rendering", () => {
  const list = [
    act({
      id: "a1",
      status: "completed",
      completed_at: "2026-03-11T07:00:00Z",
      photos: [{ thumb_url: "https://s/t1.jpg", url: "https://s/1.jpg", taken_at: null }],
    }),
    act({ id: "a2", activity_type: "pruning", scheduled_date: "2026-04-02", status: "in_progress" }),
    act({ id: "a3", activity_type: "harvesting", scheduled_date: "2026-08-01" }),
  ];

  it("renders the list in Arabic with statuses, photo and summary", () => {
    const html = renderToStaticMarkup(createElement(ActivityList, { lang: "ar", list }));
    expect(html).toContain("رش");
    expect(html).toContain("تقليم");
    expect(html).toContain("حصاد");
    expect(html).toContain("مكتمل");
    expect(html).toContain("قيد التنفيذ");
    expect(html).toContain("مخطط");
    expect(html).toContain("نُفّذ في ⁦2026-03-11⁩");
    expect(html).toContain('src="https://s/t1.jpg"');
    expect(html).toContain("اكتمل 1 من 3 نشاطًا هذا الموسم");
    expect(html).toContain("width:33%");
    expect(html).not.toMatch(/[٠-٩]/);
    // Newest first: harvest (Aug) before pruning (Apr) before spraying (Mar).
    expect(html.indexOf("حصاد")).toBeLessThan(html.indexOf("تقليم"));
    expect(html.indexOf("تقليم")).toBeLessThan(html.indexOf("رش"));
  });

  it("renders an English row with its planned date and no photo strip", () => {
    const html = renderToStaticMarkup(
      createElement(ActivityRow, { lang: "en", a: list[2], onPhoto: () => undefined }),
    );
    expect(html).toContain("Harvesting");
    expect(html).toContain("Planned for ⁦2026-08-01⁩");
    expect(html).toContain("status-pill status-upcoming");
    expect(html).not.toContain("activity-photos");
  });

  it("says when there is nothing this season", () => {
    const html = renderToStaticMarkup(createElement(ActivityList, { lang: "en", list: [] }));
    expect(html).toContain("No activities on your holding this season yet.");
    expect(html).not.toContain("progress");
  });
});
