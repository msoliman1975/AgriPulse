// GENERATED MIRROR of backend `app/shared/rbac/capabilities.yaml` +
// `role_capabilities.yaml`. Kept in lock-step by
// `backend/tests/unit/test_rbac_frontend_parity.py`, which fails CI on any
// divergence — so edit the YAML and regenerate, never this file alone.
//
// The frontend resolves capabilities locally from JWT claims, so a grant
// listed here that the backend does not grant renders a control that 403s
// on click; a grant missing here hides a control the user is entitled to.

export type Capability =
  | "alert.acknowledge"
  | "alert.read"
  | "alert.resolve"
  | "alert.snooze"
  | "alert_rule.manage"
  | "alert_rule.read"
  | "analytics.export"
  | "analytics.read"
  | "audit.read"
  | "block.attachment.read"
  | "block.attachment.write"
  | "block.create"
  | "block.delete"
  | "block.read"
  | "block.update_geometry"
  | "block.update_metadata"
  | "crop_assignment.create"
  | "crop_assignment.delete"
  | "crop_assignment.update"
  | "decision_tree.manage"
  | "decision_tree.read"
  | "farm.attachment.read"
  | "farm.attachment.write"
  | "farm.create"
  | "farm.delete"
  | "farm.manage_config"
  | "farm.member.read"
  | "farm.read"
  | "farm.update"
  | "fertilization.record"
  | "imagery.read"
  | "imagery.refresh"
  | "imagery.subscription.manage"
  | "index.compute_custom"
  | "index.read"
  | "irrigation.record"
  | "irrigation.schedule.manage"
  | "irrigation.schedule.read"
  | "notification.manage_templates"
  | "notification.read_inbox"
  | "notification.write_inbox"
  | "plan.manage"
  | "plan.read"
  | "plan_activity.complete"
  | "plan_template.apply"
  | "plan_template.manage"
  | "plan_template.read"
  | "platform.impersonate_tenant"
  | "platform.manage_countries"
  | "platform.manage_crops"
  | "platform.manage_defaults"
  | "platform.manage_platform_admins"
  | "platform.manage_rbac"
  | "platform.manage_tenant_admins"
  | "platform.manage_tenants"
  | "platform.observe_pipeline"
  | "platform.purge_data"
  | "platform.read"
  | "platform.run_backfill"
  | "platform.run_tasks"
  | "recommendation.act"
  | "recommendation.read"
  | "resource.manage"
  | "resource.read"
  | "role.assign_farm"
  | "role.assign_tenant"
  | "scouting.dispatch"
  | "scouting.record"
  | "scouting.rule.manage"
  | "scouting.visit.assign"
  | "scouting.visit.claim"
  | "scouting.visit.complete"
  | "scouting.visit.read"
  | "signal.define"
  | "signal.delete_observation"
  | "signal.platform.manage"
  | "signal.read"
  | "signal.record"
  | "subscription.manage"
  | "subscription.read"
  | "tenant.manage_integrations"
  | "tenant.manage_settings"
  | "tenant.read"
  | "tenant.read_integration_health"
  | "tenant.transfer_ownership"
  | "tenant.update"
  | "user.delete"
  | "user.field_enrol"
  | "user.invite"
  | "user.read"
  | "user.suspend"
  | "user.update"
  | "weather.read"
  | "weather.refresh"
  | "weather.subscription.manage"
  | "weather_risk.read";

export type PlatformRole = "PlatformAdmin" | "PlatformSupport";
export type TenantRole = "TenantOwner" | "TenantAdmin" | "BillingAdmin";
export type FarmRole = "FarmManager" | "Agronomist" | "FieldOperator" | "Scout" | "Viewer";

/** Role -> the capabilities it grants. `*` is PlatformAdmin only. */
export const ROLE_CAPABILITIES: Record<string, ReadonlySet<Capability | "*">> = {
  /** AgriPulse staff with full cross-tenant control. */
  PlatformAdmin: new Set<Capability | "*">(["*"]),
  /** Read-only platform-wide access for support staff. */
  PlatformSupport: new Set<Capability>([
    "alert.read",
    "alert_rule.read",
    "analytics.read",
    "audit.read",
    "block.attachment.read",
    "block.read",
    "decision_tree.read",
    "farm.attachment.read",
    "farm.member.read",
    "farm.read",
    "imagery.read",
    "index.read",
    "plan.read",
    "plan_template.read",
    "platform.observe_pipeline",
    "platform.read",
    "recommendation.read",
    "signal.read",
    "subscription.read",
    "tenant.read",
    "tenant.read_integration_health",
    "user.read",
    "weather.read",
    "weather_risk.read",
  ]),
  /** Tenant super-admin; exactly one per tenant. */
  TenantOwner: new Set<Capability>([
    "alert.acknowledge",
    "alert.read",
    "alert.resolve",
    "alert.snooze",
    "alert_rule.manage",
    "alert_rule.read",
    "analytics.export",
    "analytics.read",
    "audit.read",
    "block.attachment.read",
    "block.attachment.write",
    "block.create",
    "block.delete",
    "block.read",
    "block.update_geometry",
    "block.update_metadata",
    "crop_assignment.create",
    "crop_assignment.delete",
    "crop_assignment.update",
    "decision_tree.manage",
    "decision_tree.read",
    "farm.attachment.read",
    "farm.attachment.write",
    "farm.create",
    "farm.delete",
    "farm.manage_config",
    "farm.member.read",
    "farm.read",
    "farm.update",
    "fertilization.record",
    "imagery.read",
    "imagery.refresh",
    "imagery.subscription.manage",
    "index.compute_custom",
    "index.read",
    "irrigation.record",
    "irrigation.schedule.manage",
    "irrigation.schedule.read",
    "notification.manage_templates",
    "notification.read_inbox",
    "notification.write_inbox",
    "plan.manage",
    "plan.read",
    "plan_activity.complete",
    "plan_template.apply",
    "plan_template.read",
    "recommendation.act",
    "recommendation.read",
    "resource.manage",
    "resource.read",
    "role.assign_farm",
    "role.assign_tenant",
    "scouting.dispatch",
    "scouting.record",
    "scouting.rule.manage",
    "scouting.visit.assign",
    "scouting.visit.claim",
    "scouting.visit.complete",
    "scouting.visit.read",
    "signal.define",
    "signal.delete_observation",
    "signal.read",
    "signal.record",
    "subscription.manage",
    "subscription.read",
    "tenant.manage_integrations",
    "tenant.manage_settings",
    "tenant.read",
    "tenant.read_integration_health",
    "tenant.transfer_ownership",
    "tenant.update",
    "user.delete",
    "user.field_enrol",
    "user.invite",
    "user.read",
    "user.suspend",
    "user.update",
    "weather.read",
    "weather.refresh",
    "weather.subscription.manage",
    "weather_risk.read",
  ]),
  /** Tenant admin; everything in the tenant except billing changes and ownership transfer. */
  TenantAdmin: new Set<Capability>([
    "alert.acknowledge",
    "alert.read",
    "alert.resolve",
    "alert.snooze",
    "alert_rule.manage",
    "alert_rule.read",
    "analytics.export",
    "analytics.read",
    "audit.read",
    "block.attachment.read",
    "block.attachment.write",
    "block.create",
    "block.delete",
    "block.read",
    "block.update_geometry",
    "block.update_metadata",
    "crop_assignment.create",
    "crop_assignment.delete",
    "crop_assignment.update",
    "decision_tree.manage",
    "decision_tree.read",
    "farm.attachment.read",
    "farm.attachment.write",
    "farm.create",
    "farm.delete",
    "farm.manage_config",
    "farm.member.read",
    "farm.read",
    "farm.update",
    "fertilization.record",
    "imagery.read",
    "imagery.refresh",
    "imagery.subscription.manage",
    "index.compute_custom",
    "index.read",
    "irrigation.record",
    "irrigation.schedule.manage",
    "irrigation.schedule.read",
    "notification.manage_templates",
    "notification.read_inbox",
    "notification.write_inbox",
    "plan.manage",
    "plan.read",
    "plan_activity.complete",
    "plan_template.apply",
    "plan_template.read",
    "recommendation.act",
    "recommendation.read",
    "resource.manage",
    "resource.read",
    "role.assign_farm",
    "role.assign_tenant",
    "scouting.dispatch",
    "scouting.record",
    "scouting.rule.manage",
    "scouting.visit.assign",
    "scouting.visit.claim",
    "scouting.visit.complete",
    "scouting.visit.read",
    "signal.define",
    "signal.delete_observation",
    "signal.read",
    "signal.record",
    "subscription.read",
    "tenant.manage_integrations",
    "tenant.manage_settings",
    "tenant.read",
    "tenant.read_integration_health",
    "tenant.update",
    "user.delete",
    "user.field_enrol",
    "user.invite",
    "user.read",
    "user.suspend",
    "user.update",
    "weather.read",
    "weather.refresh",
    "weather.subscription.manage",
    "weather_risk.read",
  ]),
  /** Subscription and billing only. */
  BillingAdmin: new Set<Capability>([
    "notification.read_inbox",
    "notification.write_inbox",
    "subscription.manage",
    "subscription.read",
    "tenant.read",
  ]),
  /** Full management of an assigned farm (granted per farm). */
  FarmManager: new Set<Capability>([
    "alert.acknowledge",
    "alert.read",
    "alert.resolve",
    "alert.snooze",
    "alert_rule.read",
    "analytics.export",
    "analytics.read",
    "block.attachment.read",
    "block.attachment.write",
    "block.create",
    "block.delete",
    "block.read",
    "block.update_geometry",
    "block.update_metadata",
    "crop_assignment.create",
    "crop_assignment.delete",
    "crop_assignment.update",
    "farm.attachment.read",
    "farm.attachment.write",
    "farm.manage_config",
    "farm.member.read",
    "farm.read",
    "farm.update",
    "fertilization.record",
    "imagery.read",
    "imagery.refresh",
    "imagery.subscription.manage",
    "index.compute_custom",
    "index.read",
    "irrigation.record",
    "irrigation.schedule.manage",
    "irrigation.schedule.read",
    "notification.read_inbox",
    "notification.write_inbox",
    "plan.manage",
    "plan.read",
    "plan_activity.complete",
    "plan_template.apply",
    "plan_template.read",
    "recommendation.act",
    "recommendation.read",
    "resource.manage",
    "resource.read",
    "role.assign_farm",
    "scouting.dispatch",
    "scouting.record",
    "scouting.rule.manage",
    "scouting.visit.assign",
    "scouting.visit.read",
    "signal.read",
    "signal.record",
    "user.field_enrol",
    "weather.read",
    "weather.refresh",
    "weather.subscription.manage",
    "weather_risk.read",
  ]),
  /** Agronomic decisions on an assigned farm; no geometry edits. */
  Agronomist: new Set<Capability>([
    "alert.acknowledge",
    "alert.read",
    "alert.resolve",
    "alert.snooze",
    "alert_rule.read",
    "analytics.export",
    "analytics.read",
    "block.attachment.read",
    "block.read",
    "crop_assignment.update",
    "farm.attachment.read",
    "farm.read",
    "fertilization.record",
    "imagery.read",
    "imagery.refresh",
    "index.compute_custom",
    "index.read",
    "irrigation.record",
    "irrigation.schedule.manage",
    "irrigation.schedule.read",
    "notification.read_inbox",
    "notification.write_inbox",
    "plan.read",
    "plan_activity.complete",
    "plan_template.read",
    "recommendation.act",
    "recommendation.read",
    "resource.read",
    "scouting.dispatch",
    "scouting.record",
    "scouting.visit.assign",
    "scouting.visit.claim",
    "scouting.visit.complete",
    "scouting.visit.read",
    "signal.read",
    "signal.record",
    "weather.read",
    "weather.refresh",
    "weather_risk.read",
  ]),
  /** Field operations and observation logging on an assigned farm. */
  FieldOperator: new Set<Capability>([
    "alert.acknowledge",
    "alert.read",
    "analytics.read",
    "block.attachment.read",
    "block.attachment.write",
    "block.read",
    "farm.attachment.read",
    "farm.attachment.write",
    "farm.read",
    "fertilization.record",
    "imagery.read",
    "index.read",
    "irrigation.record",
    "irrigation.schedule.read",
    "notification.read_inbox",
    "notification.write_inbox",
    "plan.read",
    "plan_activity.complete",
    "plan_template.read",
    "recommendation.read",
    "resource.read",
    "scouting.record",
    "scouting.visit.claim",
    "scouting.visit.complete",
    "scouting.visit.read",
    "signal.read",
    "signal.record",
    "weather.read",
    "weather_risk.read",
  ]),
  /** Observation logging only on an assigned farm. */
  Scout: new Set<Capability>([
    "alert.read",
    "block.attachment.read",
    "block.read",
    "farm.attachment.read",
    "farm.read",
    "imagery.read",
    "index.read",
    "irrigation.schedule.read",
    "notification.read_inbox",
    "notification.write_inbox",
    "plan.read",
    "plan_activity.complete",
    "plan_template.read",
    "recommendation.read",
    "resource.read",
    "scouting.record",
    "scouting.visit.claim",
    "scouting.visit.complete",
    "scouting.visit.read",
    "signal.read",
    "signal.record",
    "weather.read",
    "weather_risk.read",
  ]),
  /** Read-only view of an assigned farm. */
  Viewer: new Set<Capability>([
    "alert.read",
    "analytics.read",
    "block.attachment.read",
    "block.read",
    "farm.attachment.read",
    "farm.read",
    "imagery.read",
    "index.read",
    "irrigation.schedule.read",
    "notification.read_inbox",
    "notification.write_inbox",
    "plan.read",
    "plan_template.read",
    "recommendation.read",
    "resource.read",
    "scouting.visit.read",
    "signal.read",
    "weather.read",
    "weather_risk.read",
  ]),
};

export function roleGrants(role: string, cap: Capability): boolean {
  const set = ROLE_CAPABILITIES[role];
  if (!set) return false;
  if (set.has("*")) return true;
  return set.has(cap);
}
