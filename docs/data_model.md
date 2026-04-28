# Farm Management Platform — Domain Data Model

**Version:** MVP (v1.0)
**Last updated:** 2026-04-27
**Status:** Draft for engineering review

---

## 1. Conventions

### 1.1 Schema layout

The platform uses **schema-per-tenant** within a single PostgreSQL instance. Tables live in one of two places:

| Schema | Purpose | Examples |
|---|---|---|
| `public` | Platform-wide data shared across all tenants | Crop catalog, decision-tree templates, pgstac, Keycloak tables (separate DB), platform config |
| `tenant_<uuid>` | Per-tenant data, isolated by schema | Farms, blocks, indices, alerts, recommendations, signals, audit |

Every authenticated request runs `SET LOCAL search_path TO tenant_<id>, public` before any query. Cross-tenant access is structurally impossible — there is no SQL path that joins across tenant schemas.

**Defense in depth:** Row-Level Security (RLS) policies are enabled on every shared table that contains tenant-scoped FKs (e.g., crop catalog usage stats), as a backstop against `search_path` mistakes.

### 1.2 Naming conventions

- Tables: `snake_case_plural` (e.g., `farms`, `block_crops`, `alert_rules`)
- Columns: `snake_case_singular` (e.g., `farm_id`, `created_at`)
- Primary keys: `id` (always UUID v7 — see § 1.3)
- Foreign keys: `<referenced_table_singular>_id` (e.g., `farm_id`, `tenant_id`)
- Booleans: `is_<adjective>` or `has_<noun>` (`is_active`, `has_imagery`)
- Timestamps: `<verb>_at` (`created_at`, `updated_at`, `deleted_at`)
- Enums: stored as PostgreSQL `TEXT` with a `CHECK` constraint listing allowed values, not native `ENUM` (easier to evolve)
- All geometry columns: PostGIS `geometry(<type>, 4326)` for WGS84 lat/lon storage; computed UTM 36N geometries stored separately as `geometry_utm`

### 1.3 Primary keys

- **UUID v7** as the universal PK type (chronologically sortable, supports time-range queries on PK without an extra index)
- Generated server-side with `uuid_generate_v7()` (provided by an extension or a small SQL function until Postgres 17 adds it natively)
- Never expose internal sequence-based IDs in public APIs

### 1.4 Audit columns

Every table that represents domain state (not pure log/history) carries:

```sql
created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
created_by  UUID        REFERENCES public.users(id)        -- nullable for system-created rows
updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
updated_by  UUID        REFERENCES public.users(id)
deleted_at  TIMESTAMPTZ  -- soft delete; NULL = active
```

A trigger maintains `updated_at`. Soft delete is the default; hard delete only via admin script and only for compliance reasons (e.g., GDPR-equivalent data subject deletion).

### 1.5 Areas and units

All area columns store **square meters (m²)** as `NUMERIC(14, 2)`. Display conversion to feddan / acre / hectare happens in the API/frontend layer. No exceptions — do not store `area_feddan` columns.

All distances store **meters** as `NUMERIC(10, 2)`. All elevations store **meters** as `NUMERIC(7, 2)`.

### 1.6 Time-series tables (TimescaleDB hypertables)

Time-series data lives in TimescaleDB hypertables. Each hypertable specifies:
- **Time column**: always `time TIMESTAMPTZ NOT NULL`
- **Partitioning column** (optional): typically `block_id` or `farm_id` for space partitioning
- **Chunk interval**: 7 days for high-volume (indices, weather), 30 days for low-volume (alerts, recommendations history)
- **Compression policy**: enable after 30 days, segment by space-partition column
- **Retention policy**: per-table, see specs below

### 1.7 Indexes — defaults

- Every FK gets an index automatically.
- All `*_at` columns used in WHERE clauses get a btree index.
- Spatial geometry columns get a GiST index.
- Soft-deleted rows are excluded via partial indexes: `WHERE deleted_at IS NULL`.

### 1.8 Reference enums

Stored as English string keys in the database. UI translation lives in i18n files. Examples:

```
irrigation_system: 'drip' | 'micro_sprinkler' | 'pivot' | 'furrow' | 'flood' | 'surface' | 'none'
soil_texture: 'sandy' | 'sandy_loam' | 'loam' | 'clay_loam' | 'clay' | 'silty_loam' | 'silty_clay'
salinity_class: 'non_saline' | 'slightly_saline' | 'moderately_saline' | 'strongly_saline'
crop_status: 'active' | 'fallow' | 'abandoned' | 'under_preparation'
```

A `public.reference_enums` table documents allowed values and is the source of truth for backend validation and frontend dropdowns.

---

## 2. Module overview & ERD index

| § | Module | Schema location | Tables | Hypertables | Notable extensions |
|---|---|---|---|---|---|
| 3 | `tenancy` | `public` | 3 | 0 | — |
| 4 | `iam` | `public` | 6 | 0 | — |
| 5 | `farms` | `tenant_<id>` | 7 | 0 | PostGIS |
| 6 | `imagery` | mixed | 4 | 0 | pgstac |
| 7 | `indices` | `tenant_<id>` | 2 | 1 | TimescaleDB |
| 8 | `weather` | `tenant_<id>` | 3 | 2 | TimescaleDB |
| 9 | `signals` | `tenant_<id>` | 3 | 1 | TimescaleDB |
| 10 | `alerts` | `tenant_<id>` | 5 | 1 | — |
| 11 | `recommendations` | mixed | 4 | 1 | — |
| 12 | `notifications` | `tenant_<id>` | 3 | 0 | — |
| 13 | `audit` | `tenant_<id>` | 2 | 1 | TimescaleDB, pgaudit |
| 14 | `analytics` | `tenant_<id>` | 0 (views only) | 0 | TimescaleDB continuous aggregates |

**Total: ~40 tables + 7 hypertables + ~10 views/continuous aggregates + pgstac.**

---

## 3. `tenancy` module

Identifies and segments customer organizations. One row per customer organization.

### 3.1 ERD

```
public.tenants 1 ──< public.tenant_subscriptions
public.tenants 1 ──< public.tenant_settings
```

### 3.2 `public.tenants`

The customer organization. One per Egyptian agribusiness, cooperative, or research institute.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | UUID v7 |
| `slug` | TEXT | NOT NULL, UNIQUE, CHECK (`slug ~ '^[a-z0-9-]{3,32}$'`) | URL-safe identifier, e.g. `acme-farms` |
| `name` | TEXT | NOT NULL | Display name |
| `legal_name` | TEXT | | Registered business name |
| `tax_id` | TEXT | | Egyptian tax registration number |
| `country_code` | CHAR(2) | NOT NULL, DEFAULT `'EG'` | ISO 3166-1 alpha-2 |
| `default_locale` | TEXT | NOT NULL, DEFAULT `'en'`, CHECK (`default_locale IN ('en', 'ar')`) | |
| `default_timezone` | TEXT | NOT NULL, DEFAULT `'Africa/Cairo'` | IANA tz |
| `default_currency` | CHAR(3) | NOT NULL, DEFAULT `'EGP'` | |
| `default_unit_system` | TEXT | NOT NULL, DEFAULT `'feddan'`, CHECK (`default_unit_system IN ('feddan','acre','hectare')`) | |
| `contact_email` | TEXT | NOT NULL | |
| `contact_phone` | TEXT | | E.164 format |
| `billing_address` | JSONB | | Structured address |
| `logo_url` | TEXT | | S3 URL, P2 |
| `branding_color` | TEXT | CHECK (`branding_color ~ '^#[0-9A-Fa-f]{6}$'`) | P2 |
| `schema_name` | TEXT | NOT NULL, UNIQUE | The actual schema, e.g. `tenant_a3f...` |
| `status` | TEXT | NOT NULL, DEFAULT `'active'`, CHECK (`status IN ('active','suspended','archived')`) | |
| audit cols | | | |

**Indexes:**
- `UNIQUE (slug) WHERE deleted_at IS NULL`
- `INDEX (status) WHERE deleted_at IS NULL`

**Notes:**
- Schema provisioning is idempotent via Alembic + a custom `tenants/migrations/` runner that loops every active tenant.
- A `tenant_admin_user_id` is intentionally absent here — ownership lives in `iam.tenant_memberships`, see § 4.

### 3.3 `public.tenant_subscriptions`

Tracks the active and historical subscription state per tenant. MVP supports manual invoicing only; rows are inserted manually by platform admins.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `tenant_id` | UUID | NOT NULL, FK → `tenants.id` ON DELETE RESTRICT | |
| `tier` | TEXT | NOT NULL, CHECK (`tier IN ('free','standard','premium','enterprise')`) | |
| `started_at` | TIMESTAMPTZ | NOT NULL | |
| `expires_at` | TIMESTAMPTZ | | NULL = open-ended |
| `is_current` | BOOLEAN | NOT NULL, DEFAULT FALSE | Exactly one current per tenant; enforced by partial unique index |
| `notes` | TEXT | | Manual annotations from platform admin |
| `feature_flags` | JSONB | NOT NULL, DEFAULT `'{}'` | Per-subscription overrides (`{"max_farms": 5, "imagery_provider_premium": false}`) |
| audit cols | | | |

**Indexes:**
- `UNIQUE (tenant_id) WHERE is_current = TRUE`
- `INDEX (tenant_id, started_at DESC)`

### 3.4 `public.tenant_settings`

Tenant-level configuration distinct from immutable tenant identity. Frequently changed; separate from `tenants` to avoid frequent updates of the parent row.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `tenant_id` | UUID | PK, FK → `tenants.id` ON DELETE CASCADE | |
| `cloud_cover_threshold_visualization_pct` | INT | NOT NULL, DEFAULT 60, CHECK (between 0 and 100) | |
| `cloud_cover_threshold_analysis_pct` | INT | NOT NULL, DEFAULT 20, CHECK (between 0 and 100) | |
| `imagery_refresh_cadence_hours` | INT | NOT NULL, DEFAULT 24 | |
| `alert_notification_channels` | TEXT[] | NOT NULL, DEFAULT `ARRAY['in_app','email']` | Whitelist for tenant-level dispatch |
| `webhook_endpoint_url` | TEXT | | Tenant default; per-rule overrides allowed |
| `webhook_signing_secret_kms_key` | TEXT | | KMS key reference, not the secret itself |
| `dashboard_default_indices` | TEXT[] | NOT NULL, DEFAULT `ARRAY['ndvi','ndwi']` | |
| audit cols | | | |

---

## 4. `iam` module

Users, roles, and authorization scopes. Lives in `public` schema because users may belong to multiple tenants (deferred to P2 but the model supports it now).

### 4.1 ERD

```
public.users 1 ──< public.tenant_memberships >── 1 public.tenants
public.users 1 ──< public.farm_scopes >── 1 (tenant.farms)
public.users 1 ── 1 public.user_preferences
public.tenant_memberships 1 ──< public.tenant_role_assignments
                                   (role: TenantOwner, TenantAdmin)
public.users 1 ──< public.platform_role_assignments
                     (role: PlatformAdmin, PlatformSupport)
```

### 4.2 `public.users`

The identity record. Authoritative source for `email`/`name`/`phone`; Keycloak holds credentials.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | Mirrors Keycloak user ID |
| `keycloak_subject` | TEXT | NOT NULL, UNIQUE | The `sub` claim from Keycloak JWTs |
| `email` | CITEXT | NOT NULL, UNIQUE | Case-insensitive |
| `email_verified` | BOOLEAN | NOT NULL, DEFAULT FALSE | Synced from Keycloak |
| `full_name` | TEXT | NOT NULL | |
| `phone` | TEXT | | E.164 |
| `avatar_url` | TEXT | | S3 URL |
| `status` | TEXT | NOT NULL, DEFAULT `'active'`, CHECK (`status IN ('active','suspended','archived')`) | |
| `last_login_at` | TIMESTAMPTZ | | Updated by login event handler |
| audit cols | | | |

**Indexes:**
- `UNIQUE (keycloak_subject)`
- `UNIQUE (LOWER(email))`
- `INDEX (status) WHERE deleted_at IS NULL`

### 4.3 `public.user_preferences`

Personal preferences attached to a user. One row per user, lazily created on first login.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `user_id` | UUID | PK, FK → `users.id` ON DELETE CASCADE | |
| `language` | TEXT | NOT NULL, DEFAULT `'en'`, CHECK (`language IN ('en','ar')`) | |
| `numerals` | TEXT | NOT NULL, DEFAULT `'western'`, CHECK (`numerals IN ('western','arabic_eastern')`) | |
| `unit_system` | TEXT | NOT NULL, DEFAULT `'feddan'`, CHECK (in `('feddan','acre','hectare')`) | |
| `timezone` | TEXT | NOT NULL, DEFAULT `'Africa/Cairo'` | |
| `date_format` | TEXT | NOT NULL, DEFAULT `'YYYY-MM-DD'` | |
| `notification_channels` | TEXT[] | NOT NULL, DEFAULT `ARRAY['in_app','email']` | |
| `dashboard_layout` | JSONB | NOT NULL, DEFAULT `'{}'` | Frontend-controlled |
| `updated_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

### 4.4 `public.tenant_memberships`

Links users to tenants. A user can belong to multiple tenants (consultant agronomists, P2). Each membership has its own status independent of the user's global status.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `user_id` | UUID | NOT NULL, FK → `users.id` ON DELETE CASCADE | |
| `tenant_id` | UUID | NOT NULL, FK → `tenants.id` ON DELETE CASCADE | |
| `status` | TEXT | NOT NULL, DEFAULT `'active'`, CHECK (`status IN ('invited','active','suspended','archived')`) | |
| `invited_by` | UUID | FK → `users.id` | |
| `joined_at` | TIMESTAMPTZ | | NULL until invite accepted |
| audit cols | | | |

**Indexes:**
- `UNIQUE (user_id, tenant_id)`
- `INDEX (tenant_id, status)`

### 4.5 `public.tenant_role_assignments`

Tenant-wide roles (`TenantOwner`, `TenantAdmin`). These are distinct from per-farm scopes. A tenant role grants access to *every* farm in the tenant.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `membership_id` | UUID | NOT NULL, FK → `tenant_memberships.id` ON DELETE CASCADE | |
| `role` | TEXT | NOT NULL, CHECK (`role IN ('TenantOwner','TenantAdmin','BillingAdmin')`) | |
| `granted_by` | UUID | FK → `users.id` | |
| `granted_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `revoked_at` | TIMESTAMPTZ | | NULL = active |

**Indexes:**
- `UNIQUE (membership_id, role) WHERE revoked_at IS NULL`
- Constraint trigger: at most one `TenantOwner` per tenant at any time.

### 4.6 `public.farm_scopes`

Per-farm role assignments. The vast majority of users land here — a user is granted a role on a specific farm.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `membership_id` | UUID | NOT NULL, FK → `tenant_memberships.id` ON DELETE CASCADE | |
| `farm_id` | UUID | NOT NULL | References `tenant_<id>.farms.id`; cross-schema FK is logical, not declarative |
| `role` | TEXT | NOT NULL, CHECK (`role IN ('FarmManager','Agronomist','FieldOperator','Scout','Viewer')`) | |
| `granted_by` | UUID | FK → `users.id` | |
| `granted_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `revoked_at` | TIMESTAMPTZ | | |

**Indexes:**
- `UNIQUE (membership_id, farm_id, role) WHERE revoked_at IS NULL`
- `INDEX (membership_id) WHERE revoked_at IS NULL`
- `INDEX (farm_id) WHERE revoked_at IS NULL`

**Note on cross-schema FK:** Since `farms` lives in `tenant_<id>` schema, this FK is *logical* — enforced by application code, not by SQL constraint. A periodic consistency-check job logs orphans.

### 4.7 `public.platform_role_assignments`

Roles for your own staff. Cross-tenant access.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `user_id` | UUID | NOT NULL, FK → `users.id` ON DELETE CASCADE | |
| `role` | TEXT | NOT NULL, CHECK (`role IN ('PlatformAdmin','PlatformSupport')`) | |
| `granted_by` | UUID | FK → `users.id` | |
| `granted_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `revoked_at` | TIMESTAMPTZ | | |

**Indexes:**
- `UNIQUE (user_id, role) WHERE revoked_at IS NULL`

---

## 5. `farms` module

The agronomic core: farms, their geometric breakdown into blocks, and current/historical crop assignments. Lives entirely in `tenant_<id>` schema.

### 5.1 ERD

```
farms 1 ──< blocks
farms 1 ──< farm_attachments
blocks 1 ──< block_crops              -- current and historical crop seasons
blocks 1 ──< block_attachments
public.crops (shared) 1 ──< block_crops
public.crop_varieties (shared) 1 ──< block_crops
```

### 5.2 `public.crops` (shared catalog)

The crop catalog. Curated by platform admins. About 20 entries seeded for Egypt at launch.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `code` | TEXT | NOT NULL, UNIQUE | Stable key, e.g. `citrus_orange` |
| `name_en` | TEXT | NOT NULL | "Orange" |
| `name_ar` | TEXT | NOT NULL | "برتقال" |
| `scientific_name` | TEXT | | "Citrus sinensis" |
| `category` | TEXT | NOT NULL, CHECK (`category IN ('cereal','fruit_tree','vegetable','fiber','fodder','sugar','oilseed','legume','other')`) | |
| `is_perennial` | BOOLEAN | NOT NULL | |
| `default_growing_season_days` | INT | | NULL for perennials |
| `gdd_base_temp_c` | NUMERIC(4,1) | | Base temperature for GDD (e.g. 10°C for citrus) |
| `gdd_upper_temp_c` | NUMERIC(4,1) | | Upper cap |
| `relevant_indices` | TEXT[] | NOT NULL, DEFAULT `ARRAY['ndvi']` | `['ndvi','ndre','ndwi']` etc. — used to pre-compute indices |
| `phenology_stages` | JSONB | | Array of `{stage, start_gdd, end_gdd, ...}` for P2 phenology models |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | |
| audit cols | | | |

**Indexes:**
- `UNIQUE (code)`
- `INDEX (category) WHERE is_active = TRUE`

### 5.3 `public.crop_varieties` (shared catalog)

Variety-level detail under a crop. Optional — most crops will have only their generic entry plus a few common varieties. Tenants can request additions via support.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `crop_id` | UUID | NOT NULL, FK → `crops.id` ON DELETE RESTRICT | |
| `code` | TEXT | NOT NULL | e.g. `valencia` |
| `name_en` | TEXT | NOT NULL | "Valencia" |
| `name_ar` | TEXT | | |
| `attributes` | JSONB | NOT NULL, DEFAULT `'{}'` | `{maturity_days: 240, market: 'export'}` |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | |
| audit cols | | | |

**Indexes:**
- `UNIQUE (crop_id, code)`

### 5.4 `farms` (tenant schema)

The top-level operational unit owned by a tenant.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `code` | TEXT | NOT NULL | Short reference, e.g. `FARM-NW-01` — unique within tenant |
| `name` | TEXT | NOT NULL | |
| `description` | TEXT | | |
| `boundary` | geometry(MultiPolygon, 4326) | NOT NULL | WGS84 |
| `boundary_utm` | geometry(MultiPolygon, 32636) | NOT NULL | UTM 36N for accurate area math; computed by trigger from `boundary` |
| `centroid` | geometry(Point, 4326) | NOT NULL | Computed from boundary |
| `area_m2` | NUMERIC(14,2) | NOT NULL | Computed from `boundary_utm` (`ST_Area(boundary_utm)`) |
| `elevation_m` | NUMERIC(7,2) | | Sampled from DEM at centroid |
| `governorate` | TEXT | | Egyptian governorate name (e.g. "Beheira") |
| `district` | TEXT | | |
| `nearest_city` | TEXT | | |
| `address_line` | TEXT | | |
| `farm_type` | TEXT | NOT NULL, DEFAULT `'commercial'`, CHECK (`farm_type IN ('commercial','research','contract')`) | |
| `ownership_type` | TEXT | CHECK (`ownership_type IN ('owned','leased','partnership','other')`) | |
| `primary_water_source` | TEXT | CHECK (`primary_water_source IN ('well','canal','nile','desalinated','rainfed','mixed')`) | |
| `established_date` | DATE | | |
| `tags` | TEXT[] | NOT NULL, DEFAULT `'{}'` | |
| `status` | TEXT | NOT NULL, DEFAULT `'active'`, CHECK (`status IN ('active','archived')`) | |
| audit cols | | | |

**Indexes:**
- `UNIQUE (code) WHERE deleted_at IS NULL`
- `GiST (boundary)`
- `GiST (centroid)`
- `INDEX (status) WHERE deleted_at IS NULL`
- `INDEX (governorate) WHERE deleted_at IS NULL`

**Triggers:**
- Before insert/update of `boundary`: auto-populate `boundary_utm`, `centroid`, `area_m2`.
- Before insert/update of `boundary` (async event): publish `FarmBoundaryChanged` event so imagery module can recompute AOI hash and reschedule ingestion.

### 5.5 `blocks` (tenant schema)

The operational subdivision of a farm — what gets monitored, alerted, and forecast.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `farm_id` | UUID | NOT NULL, FK → `farms.id` ON DELETE RESTRICT | |
| `code` | TEXT | NOT NULL | Unique within farm, e.g. `B-12` |
| `name` | TEXT | | Display name; falls back to `code` |
| `boundary` | geometry(Polygon, 4326) | NOT NULL | |
| `boundary_utm` | geometry(Polygon, 32636) | NOT NULL | |
| `centroid` | geometry(Point, 4326) | NOT NULL | |
| `area_m2` | NUMERIC(14,2) | NOT NULL | |
| `elevation_m` | NUMERIC(7,2) | | Mean elevation from DEM |
| `slope_pct` | NUMERIC(5,2) | | P2 — derived from DEM |
| `aspect_deg` | NUMERIC(5,2) | | P2 |
| `irrigation_system` | TEXT | CHECK (`irrigation_system IN ('drip','micro_sprinkler','pivot','furrow','flood','surface','none')`) | |
| `irrigation_source` | TEXT | CHECK (`irrigation_source IN ('well','canal','nile','mixed')`) | |
| `flow_rate_m3_per_hour` | NUMERIC(8,2) | | P2 |
| `soil_texture` | TEXT | CHECK (`soil_texture IN ('sandy','sandy_loam','loam','clay_loam','clay','silty_loam','silty_clay')`) | |
| `salinity_class` | TEXT | CHECK (`salinity_class IN ('non_saline','slightly_saline','moderately_saline','strongly_saline')`) | |
| `soil_ph` | NUMERIC(3,1) | CHECK (between 0 and 14) | P2 |
| `soil_ec_ds_per_m` | NUMERIC(5,2) | | P2 |
| `soil_organic_matter_pct` | NUMERIC(5,2) | | P2 |
| `last_soil_test_date` | DATE | | P2 |
| `responsible_user_id` | UUID | | Cross-schema FK to `public.users.id` (logical) |
| `status` | TEXT | NOT NULL, DEFAULT `'active'`, CHECK (`status IN ('active','fallow','abandoned','under_preparation','archived')`) | |
| `tags` | TEXT[] | NOT NULL, DEFAULT `'{}'` | |
| `notes` | TEXT | | |
| `aoi_hash` | TEXT | NOT NULL | SHA-256 of `boundary_utm` WKT; used for idempotent imagery asset IDs |
| audit cols | | | |

**Indexes:**
- `UNIQUE (farm_id, code) WHERE deleted_at IS NULL`
- `GiST (boundary)`
- `GiST (centroid)`
- `INDEX (status) WHERE deleted_at IS NULL`
- `INDEX (irrigation_system) WHERE deleted_at IS NULL`

**Triggers:** same boundary triggers as `farms`. Plus: re-compute `aoi_hash` whenever `boundary` changes.

### 5.6 `block_crops` (tenant schema)

The current and historical crop assignments for a block. One row per season-on-block — including the active season.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `block_id` | UUID | NOT NULL, FK → `blocks.id` ON DELETE CASCADE | |
| `crop_id` | UUID | NOT NULL | FK → `public.crops.id` (logical cross-schema) |
| `crop_variety_id` | UUID | | FK → `public.crop_varieties.id` |
| `season_label` | TEXT | NOT NULL | e.g. `2026-summer`, `2025-2026`, or `Y3` for perennials |
| `planting_date` | DATE | | |
| `expected_harvest_start` | DATE | | |
| `expected_harvest_end` | DATE | | |
| `actual_harvest_date` | DATE | | |
| `plant_density_per_ha` | NUMERIC(8,2) | | |
| `row_spacing_m` | NUMERIC(5,2) | | Orchards |
| `plant_spacing_m` | NUMERIC(5,2) | | Orchards |
| `growth_stage` | TEXT | | Phenology stage; auto-derived where models exist |
| `growth_stage_updated_at` | TIMESTAMPTZ | | |
| `is_current` | BOOLEAN | NOT NULL, DEFAULT FALSE | Exactly one current per block |
| `status` | TEXT | NOT NULL, DEFAULT `'planned'`, CHECK (`status IN ('planned','growing','harvesting','completed','aborted')`) | |
| `notes` | TEXT | | |
| audit cols | | | |

**Indexes:**
- `UNIQUE (block_id) WHERE is_current = TRUE`
- `INDEX (block_id, planting_date DESC)`
- `INDEX (crop_id)`

### 5.7 `farm_attachments` and `block_attachments` (tenant schema)

Photos, documents, deeds. Both have identical shape; shown as one spec.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `farm_id` / `block_id` | UUID | NOT NULL, FK | |
| `kind` | TEXT | NOT NULL, CHECK (`kind IN ('photo','deed','soil_test_report','map','other')`) | |
| `s3_key` | TEXT | NOT NULL | Object storage key |
| `original_filename` | TEXT | NOT NULL | |
| `content_type` | TEXT | NOT NULL | MIME |
| `size_bytes` | BIGINT | NOT NULL | |
| `caption` | TEXT | | |
| `taken_at` | TIMESTAMPTZ | | For photos with EXIF |
| `geo_point` | geometry(Point, 4326) | | For photos with GPS |
| audit cols | | | |

**Indexes:** `INDEX (farm_id / block_id)`, `INDEX (kind)`

---

## 6. `imagery` module

Imagery providers, scenes, and assets. Built around pgstac for STAC compliance. Lives partly in `public` (provider registry) and partly in `tenant_<id>` (ingestion jobs).

### 6.1 ERD

```
public.imagery_providers 1 ──< tenant.imagery_ingestion_jobs
public.imagery_products  ── (many-to-one) ── public.imagery_providers
tenant.imagery_ingestion_jobs 1 ──< (logical) pgstac.items
tenant.imagery_aoi_subscriptions  -- per-AOI which products to ingest
```

pgstac itself contributes its standard schema (`pgstac.collections`, `pgstac.items`, etc.) which we treat as managed by the extension.

### 6.2 `public.imagery_providers`

The catalog of supported providers. Curated by platform admins.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `code` | TEXT | NOT NULL, UNIQUE | `sentinel_hub`, `planet_scope`, `airbus_pleiades_neo`, `self_managed_s2` |
| `name` | TEXT | NOT NULL | Display name |
| `kind` | TEXT | NOT NULL, CHECK (`kind IN ('commercial_api','open_self_managed','premium_imagery')`) | |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | Disable to stop new ingestions globally |
| `config_schema` | JSONB | NOT NULL | JSON schema for `config` field |
| audit cols | | | |

### 6.3 `public.imagery_products`

A specific product offered by a provider (e.g. Sentinel-2 L2A from Sentinel Hub vs from self-managed pipeline).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `provider_id` | UUID | NOT NULL, FK → `imagery_providers.id` | |
| `code` | TEXT | NOT NULL | `s2_l2a`, `planetscope_4band` |
| `name` | TEXT | NOT NULL | |
| `resolution_m` | NUMERIC(5,2) | NOT NULL | e.g. 10.00, 3.00 |
| `revisit_days_avg` | NUMERIC(4,2) | NOT NULL | e.g. 5.00 for S2 single-orbit, 2.5 for combined |
| `bands` | TEXT[] | NOT NULL | `ARRAY['blue','green','red','red_edge_1','nir','swir1','swir2']` |
| `supported_indices` | TEXT[] | NOT NULL | `ARRAY['ndvi','ndwi','evi','savi','ndre','gndvi']` |
| `cost_tier` | TEXT | NOT NULL, CHECK (`cost_tier IN ('free','low','medium','high','premium')`) | Drives subscription gating |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | |
| audit cols | | | |

**Indexes:** `UNIQUE (provider_id, code)`

### 6.4 `imagery_aoi_subscriptions` (tenant schema)

Which products are ingested for which AOIs (typically per-block) at which cadence. The "what to fetch" registry.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `block_id` | UUID | NOT NULL, FK → `blocks.id` ON DELETE CASCADE | |
| `product_id` | UUID | NOT NULL | FK → `public.imagery_products.id` |
| `cadence_hours` | INT | NOT NULL | Override default; null uses tenant default |
| `cloud_cover_max_pct` | INT | | Override; null uses tenant default |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | |
| `last_successful_ingest_at` | TIMESTAMPTZ | | Updated by ingestion job |
| `last_attempted_at` | TIMESTAMPTZ | | Includes failures |
| audit cols | | | |

**Indexes:** `UNIQUE (block_id, product_id) WHERE is_active = TRUE`

### 6.5 `imagery_ingestion_jobs` (tenant schema)

A run of the imagery pipeline for a specific scene/AOI/product combination. Useful for debugging, retries, idempotency.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `subscription_id` | UUID | NOT NULL, FK → `imagery_aoi_subscriptions.id` ON DELETE CASCADE | |
| `block_id` | UUID | NOT NULL | Denormalized for fast queries |
| `product_id` | UUID | NOT NULL | Denormalized |
| `scene_id` | TEXT | NOT NULL | Provider's scene identifier |
| `scene_datetime` | TIMESTAMPTZ | NOT NULL | When the satellite captured it |
| `requested_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | When the job was created |
| `started_at` | TIMESTAMPTZ | | |
| `completed_at` | TIMESTAMPTZ | | |
| `status` | TEXT | NOT NULL, DEFAULT `'pending'`, CHECK (`status IN ('pending','running','succeeded','failed','skipped_cloud','skipped_duplicate')`) | |
| `cloud_cover_pct` | NUMERIC(5,2) | | |
| `valid_pixel_pct` | NUMERIC(5,2) | | |
| `error_message` | TEXT | | |
| `stac_item_id` | TEXT | | Set on success; PK in pgstac.items |
| `assets_written` | JSONB | | Array of S3 keys for raw + indices |

**Indexes:**
- `UNIQUE (subscription_id, scene_id)` — idempotency key
- `INDEX (block_id, scene_datetime DESC)`
- `INDEX (status, requested_at)` — for worker pickup

### 6.6 pgstac integration

We use the pgstac extension's standard schema for STAC catalog management. Notable interactions:

- `pgstac.collections` — one collection per `(tenant_id, product_id)` combination, ID format `tenant_<uuid>__<product_code>`. Created automatically when first ingestion succeeds for that combo.
- `pgstac.items` — one item per ingestion job that succeeds. Item ID is the deterministic asset ID: `{provider_code}/{product_code}/{scene_id}/{aoi_hash}`.
- Assets within an item: `raw_bands`, `ndvi`, `ndwi`, `evi`, `savi`, `ndre`, `gndvi`, `cloud_mask` — each pointing to an S3 COG URL.
- All STAC metadata uses the WGS84 geometry (`boundary` from the block).

**Tenant scoping in pgstac:** pgstac itself does not understand tenants. We enforce isolation by:
1. Always filtering by `collection LIKE 'tenant_<id>__%'` in queries.
2. RLS policy on `pgstac.items` (custom — not part of pgstac extension): `USING (collection LIKE current_setting('app.tenant_collection_prefix'))`.
3. Application-layer enforcement as the primary defense.

---

## 7. `indices` module

Computed vegetation/water indices, both as raster assets (referenced via STAC) and as time-series aggregates per block. The aggregate table is the workhorse for dashboards and alerting.

### 7.1 ERD

```
blocks 1 ──< block_index_aggregates  (TimescaleDB hypertable)
public.indices_catalog ──< block_index_aggregates  (logical)
```

### 7.2 `public.indices_catalog`

Definitions of all supported indices, including the formula for documentation and the physical interpretation.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `code` | TEXT | NOT NULL, UNIQUE | `ndvi`, `ndwi`, `evi`, `savi`, `ndre`, `gndvi` |
| `name_en` | TEXT | NOT NULL | |
| `name_ar` | TEXT | | |
| `formula_text` | TEXT | NOT NULL | "(NIR - Red) / (NIR + Red)" |
| `value_min` | NUMERIC(6,3) | NOT NULL | Typically -1 |
| `value_max` | NUMERIC(6,3) | NOT NULL | Typically 1 |
| `physical_meaning` | TEXT | | Used in tooltips |
| `is_standard` | BOOLEAN | NOT NULL, DEFAULT TRUE | Pre-computed for every scene; non-standard = on-demand |
| audit cols | | | |

### 7.3 `block_index_aggregates` (tenant schema, hypertable)

Per-block, per-date, per-index summary statistics. **The most-queried table in the system.** Drives dashboards, alert evaluation, recommendation evaluation.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `time` | TIMESTAMPTZ | NOT NULL | Hypertable time column; equal to `scene_datetime` |
| `block_id` | UUID | NOT NULL | Hypertable space-partition column |
| `index_code` | TEXT | NOT NULL | FK to `public.indices_catalog.code` (logical) |
| `product_id` | UUID | NOT NULL | Which product produced this aggregate |
| `mean` | NUMERIC(7,4) | | NULL if all pixels masked |
| `min` | NUMERIC(7,4) | | |
| `max` | NUMERIC(7,4) | | |
| `p10` | NUMERIC(7,4) | | 10th percentile |
| `p50` | NUMERIC(7,4) | | Median |
| `p90` | NUMERIC(7,4) | | 90th percentile |
| `std_dev` | NUMERIC(7,4) | | |
| `valid_pixel_count` | INT | NOT NULL | After cloud + AOI mask |
| `total_pixel_count` | INT | NOT NULL | |
| `valid_pixel_pct` | NUMERIC(5,2) | GENERATED ALWAYS AS (`100.0 * valid_pixel_count / NULLIF(total_pixel_count, 0)`) STORED | |
| `cloud_cover_pct` | NUMERIC(5,2) | | |
| `stac_item_id` | TEXT | NOT NULL | Trace back to the source scene |
| `inserted_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Hypertable config:**
- Time column: `time`
- Space partition: `block_id` (4 partitions)
- Chunk interval: 7 days
- Compression: enable after 30 days, segment by `(block_id, index_code)`
- Retention: keep indefinitely (cheap; a single block with 6 indices × 73 scenes/year × ~50 bytes ≈ 22KB/year)

**Indexes:**
- Primary key (logical): `(block_id, time DESC, index_code)`
- `INDEX (index_code, time DESC)` for cross-block queries
- `INDEX (stac_item_id)` for trace-back

**Continuous aggregates** (TimescaleDB views, defined in § 14):
- Daily mean per block per index (used by trend charts)
- Weekly mean per block per index (used by recommendation evaluation)

---

## 8. `weather` module

Weather observations and forecasts for each farm. Hourly observations are kept for ~2 years; forecasts are kept point-in-time for ~90 days then retained as monthly aggregates for forecast-accuracy analysis (P2).

### 8.1 ERD

```
farms 1 ──< weather_observations         (hypertable)
farms 1 ──< weather_forecasts            (hypertable)
farms 1 ──< weather_derived_daily        (regular table or continuous aggregate)
```

### 8.2 `weather_observations` (tenant schema, hypertable)

Hourly current/recent observations from Open-Meteo or other providers, sampled at the farm centroid.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `time` | TIMESTAMPTZ | NOT NULL | Observation time |
| `farm_id` | UUID | NOT NULL | Hypertable space partition |
| `provider_code` | TEXT | NOT NULL | `open_meteo`, future `noaa_gfs`, etc. |
| `air_temp_c` | NUMERIC(5,2) | | |
| `humidity_pct` | NUMERIC(5,2) | | |
| `precipitation_mm` | NUMERIC(6,2) | | Past hour |
| `wind_speed_m_s` | NUMERIC(5,2) | | |
| `wind_direction_deg` | NUMERIC(5,1) | | |
| `pressure_hpa` | NUMERIC(6,2) | | |
| `solar_radiation_w_m2` | NUMERIC(7,2) | | |
| `cloud_cover_pct` | NUMERIC(5,2) | | |
| `et0_mm` | NUMERIC(5,2) | | Reference ET from provider, if available |
| `inserted_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Hypertable:**
- Chunk: 7 days
- Compression: after 30 days, segment by `farm_id`
- Retention: 2 years hot

**Indexes:** `(farm_id, time DESC)`

### 8.3 `weather_forecasts` (tenant schema, hypertable)

Point-in-time forecast snapshots. Each fetch creates one row per forecast-hour in the horizon.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `time` | TIMESTAMPTZ | NOT NULL | The forecast's *target* time |
| `forecast_issued_at` | TIMESTAMPTZ | NOT NULL | When this forecast was generated |
| `farm_id` | UUID | NOT NULL | |
| `provider_code` | TEXT | NOT NULL | |
| `air_temp_c` | NUMERIC(5,2) | | |
| `humidity_pct` | NUMERIC(5,2) | | |
| `precipitation_mm` | NUMERIC(6,2) | | |
| `precipitation_probability_pct` | NUMERIC(5,2) | | |
| `wind_speed_m_s` | NUMERIC(5,2) | | |
| `solar_radiation_w_m2` | NUMERIC(7,2) | | |
| `et0_mm` | NUMERIC(5,2) | | |

**Hypertable:**
- Chunk: 7 days on `time`
- Compression: after 14 days
- Retention: 90 days hot, then monthly aggregates retained 5 years (P2)

**Indexes:**
- `(farm_id, time DESC, forecast_issued_at DESC)` — "what was the latest forecast for tomorrow?"
- `INDEX (forecast_issued_at)` — for monitoring fetch jobs

### 8.4 `weather_derived_daily` (tenant schema, regular table)

Per-day derived signals: GDD, daily ET₀ sum, cumulative rainfall (7d, 30d). Computed nightly per farm. Could be a continuous aggregate, but is a regular table because the formulas (esp. GDD with crop-specific base temp) need application-side logic.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `farm_id` | UUID | NOT NULL | |
| `date` | DATE | NOT NULL | |
| `gdd_base10` | NUMERIC(8,2) | | Daily growing degree days, base 10°C |
| `gdd_base15` | NUMERIC(8,2) | | Base 15°C |
| `gdd_cumulative_base10_season` | NUMERIC(10,2) | | Season cumulative, reset by event |
| `et0_mm_daily` | NUMERIC(5,2) | | |
| `precip_mm_daily` | NUMERIC(6,2) | | |
| `precip_mm_7d` | NUMERIC(7,2) | | |
| `precip_mm_30d` | NUMERIC(8,2) | | |
| `temp_min_c` | NUMERIC(5,2) | | |
| `temp_max_c` | NUMERIC(5,2) | | |
| `temp_mean_c` | NUMERIC(5,2) | | |
| `computed_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Primary key:** `(farm_id, date)`
**Indexes:** `INDEX (date)`

---

## 9. `signals` module

User-defined custom data streams. Manual entry in MVP, IoT-ready interface in P2.

### 9.1 ERD

```
public.signal_types_catalog       -- (optional shared catalog, P2)
tenant.signal_definitions 1 ──< tenant.signal_observations  (hypertable)
tenant.signal_definitions 1 ──< tenant.signal_assignments
                                 (which signal definitions apply to which farm/block)
```

### 9.2 `signal_definitions` (tenant schema)

What kind of signal exists. Defined by the tenant, scoped to their data. Examples: "soil moisture sensor reading", "scout pest count", "irrigation event volume".

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `code` | TEXT | NOT NULL | Unique within tenant; stable identifier |
| `name` | TEXT | NOT NULL | Display name (user-provided, not translated) |
| `description` | TEXT | | |
| `value_kind` | TEXT | NOT NULL, CHECK (`value_kind IN ('numeric','categorical','event','boolean','geopoint')`) | |
| `unit` | TEXT | | For numeric: "mm", "ppm", "count", "m3" |
| `categorical_values` | TEXT[] | | For categorical only |
| `value_min` | NUMERIC(12,4) | | Validation bound for numeric |
| `value_max` | NUMERIC(12,4) | | |
| `attachment_allowed` | BOOLEAN | NOT NULL, DEFAULT FALSE | Whether observations can attach photos |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | |
| audit cols | | | |

**Indexes:** `UNIQUE (code) WHERE deleted_at IS NULL`

### 9.3 `signal_assignments` (tenant schema)

Which farms/blocks a given signal definition applies to. A signal can apply to a whole farm, specific blocks, or all blocks of a tenant.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `signal_definition_id` | UUID | NOT NULL, FK | |
| `farm_id` | UUID | | NULL = applies to all farms |
| `block_id` | UUID | | NULL = applies to all blocks of farm |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | |
| audit cols | | | |

**Constraint:** at least one of `farm_id` or `block_id` is set, OR both NULL (= tenant-wide).

### 9.4 `signal_observations` (tenant schema, hypertable)

Actual recorded values. Hot path for both data entry and alert/recommendation evaluation.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `time` | TIMESTAMPTZ | NOT NULL | When the observation was made |
| `signal_definition_id` | UUID | NOT NULL | |
| `block_id` | UUID | | NULL if signal is farm-level |
| `farm_id` | UUID | NOT NULL | Always set for partition pruning |
| `value_numeric` | NUMERIC(14,4) | | |
| `value_categorical` | TEXT | | |
| `value_event` | TEXT | | Free-form event description |
| `value_boolean` | BOOLEAN | | |
| `value_geopoint` | geometry(Point, 4326) | | |
| `attachment_s3_key` | TEXT | | Photo or document |
| `notes` | TEXT | | |
| `recorded_by` | UUID | NOT NULL | User who logged it |
| `inserted_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Hypertable:**
- Time column: `time`
- Space partition: `farm_id`
- Chunk: 30 days
- Compression: after 90 days
- Retention: indefinite (low volume)

**Constraints:** at least one of `value_*` columns is non-null (CHECK).

**Indexes:**
- `(farm_id, time DESC)`
- `(signal_definition_id, time DESC)`
- `(block_id, time DESC) WHERE block_id IS NOT NULL`

---

## 10. `alerts` module

Tier-2 compound rule engine. Rules evaluate every 15 minutes against indices, weather, and signals.

### 10.1 ERD

```
alert_rules 1 ──< alert_rule_conditions
alert_rules 1 ──< alert_rule_scopes        -- which farms/blocks this rule covers
alert_rules 1 ──< alerts                   -- alert lifecycle records
alerts 1 ──< alerts_history                -- (hypertable, all transitions)
```

### 10.2 `alert_rules` (tenant schema)

The user-defined rule. Tier 2: compound conditions with AND/OR groups, aggregations, time windows.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `name` | TEXT | NOT NULL | |
| `description` | TEXT | | |
| `severity` | TEXT | NOT NULL, CHECK (`severity IN ('info','warning','critical')`) | |
| `condition_tree` | JSONB | NOT NULL | Full condition tree (Pydantic-modelled in app); see § 10.3 |
| `cooldown_seconds` | INT | NOT NULL, DEFAULT 21600 | Minimum gap between firings of the same rule on the same scope (default 6h) |
| `auto_resolve_after_seconds` | INT | | NULL = manual resolve only |
| `notification_channels` | TEXT[] | NOT NULL, DEFAULT `ARRAY['in_app','email']` | |
| `webhook_url` | TEXT | | Override tenant default |
| `is_enabled` | BOOLEAN | NOT NULL, DEFAULT TRUE | |
| `version` | INT | NOT NULL, DEFAULT 1 | Bumped on edit; old versions kept in `alert_rule_versions` (P2) |
| `last_evaluated_at` | TIMESTAMPTZ | | Updated by evaluator |
| audit cols | | | |

**Indexes:**
- `INDEX (is_enabled, last_evaluated_at)` — for evaluator pickup
- `INDEX (severity)`

### 10.3 Condition tree shape (JSONB, documented)

```json
{
  "type": "group",
  "operator": "AND",
  "conditions": [
    {
      "type": "atomic",
      "metric": {"kind": "index", "code": "ndvi", "aggregation": "mean", "window_days": 7},
      "operator": "lt",
      "threshold": 0.4
    },
    {
      "type": "atomic",
      "metric": {"kind": "index", "code": "ndvi", "aggregation": "delta_pct", "window_days": 14},
      "operator": "lt",
      "threshold": -15
    },
    {
      "type": "group",
      "operator": "OR",
      "conditions": [
        {"type": "atomic", "metric": {"kind": "weather_forecast", "code": "precipitation_mm", "aggregation": "sum", "window_days": 5}, "operator": "lt", "threshold": 5},
        {"type": "atomic", "metric": {"kind": "signal", "definition_code": "soil_moisture", "aggregation": "mean", "window_days": 1}, "operator": "lt", "threshold": 0.25}
      ]
    }
  ]
}
```

This is validated against a Pydantic schema before insert.

### 10.4 `alert_rule_scopes` (tenant schema)

Which farms/blocks a rule applies to. Same shape as `signal_assignments`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `rule_id` | UUID | NOT NULL, FK ON DELETE CASCADE | |
| `farm_id` | UUID | | |
| `block_id` | UUID | | |
| `crop_filter_id` | UUID | | If set, only blocks currently growing this crop |
| audit cols | | | |

**Indexes:** `INDEX (rule_id)`, `INDEX (farm_id)`, `INDEX (block_id)`

### 10.5 `alerts` (tenant schema)

Active alert lifecycle records. One row per fired alert. State transitions emit rows in `alerts_history`.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `rule_id` | UUID | NOT NULL, FK | |
| `rule_version` | INT | NOT NULL | Snapshot for traceability |
| `farm_id` | UUID | NOT NULL | |
| `block_id` | UUID | | NULL for farm-level alerts |
| `severity` | TEXT | NOT NULL | Snapshot from rule |
| `state` | TEXT | NOT NULL, DEFAULT `'open'`, CHECK (`state IN ('open','acknowledged','snoozed','resolved','auto_resolved')`) | |
| `fired_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `acknowledged_at` | TIMESTAMPTZ | | |
| `acknowledged_by` | UUID | | |
| `resolved_at` | TIMESTAMPTZ | | |
| `resolved_by` | UUID | | NULL if `auto_resolved` |
| `snoozed_until` | TIMESTAMPTZ | | |
| `evaluation_snapshot` | JSONB | NOT NULL | The values that triggered the firing — for explainability |
| `notification_dispatch_log` | JSONB | | What was sent where, when |
| audit cols | | | |

**Indexes:**
- `INDEX (state, severity, fired_at DESC) WHERE state IN ('open', 'acknowledged')`
- `INDEX (farm_id, state, fired_at DESC)`
- `INDEX (block_id, state, fired_at DESC) WHERE block_id IS NOT NULL`
- `INDEX (rule_id, fired_at DESC)`
- `UNIQUE (rule_id, farm_id, block_id) WHERE state IN ('open','acknowledged','snoozed')` — at most one open alert per rule per scope at a time (cooldown enforcement)

### 10.6 `alerts_history` (tenant schema, hypertable)

Every state transition for compliance and analytics.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `time` | TIMESTAMPTZ | NOT NULL | Transition time |
| `alert_id` | UUID | NOT NULL | |
| `rule_id` | UUID | NOT NULL | |
| `farm_id` | UUID | NOT NULL | |
| `from_state` | TEXT | | NULL on initial fire |
| `to_state` | TEXT | NOT NULL | |
| `actor_user_id` | UUID | | NULL for system transitions |
| `details` | JSONB | | Snooze duration, resolution note, etc. |

**Hypertable:**
- Chunk: 30 days
- Compression: after 90 days
- Retention: 2 years hot, then archive

**Indexes:** `(farm_id, time DESC)`, `(alert_id, time)`

---

## 11. `recommendations` module

Decision-tree-driven recommendations. Trees are authored as YAML by your agronomy team and stored centrally. Recommendation outputs land in tenant schemas.

### 11.1 ERD

```
public.decision_trees 1 ──< public.decision_tree_versions
public.decision_tree_versions ──< (logical) tenant.recommendations
tenant.recommendations 1 ──< tenant.recommendations_history  (hypertable)
```

### 11.2 `public.decision_trees`

The catalog of decision trees, one per crop type (or one per crop+region pairing in P2).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `code` | TEXT | NOT NULL, UNIQUE | `citrus_irrigation_v1`, `mango_general_v1` |
| `name` | TEXT | NOT NULL | |
| `description` | TEXT | | |
| `crop_id` | UUID | NOT NULL, FK → `public.crops.id` | |
| `applicable_regions` | TEXT[] | | Egyptian governorates this tree was tuned for; null = all |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | |
| `current_version_id` | UUID | | FK → `decision_tree_versions.id` (deferred) |
| audit cols | | | |

### 11.3 `public.decision_tree_versions`

Version history of trees. Trees are immutable once published; new edits create new versions. Tenant recommendations reference a specific version for explainability.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `tree_id` | UUID | NOT NULL, FK | |
| `version` | INT | NOT NULL | |
| `tree_yaml` | TEXT | NOT NULL | Source YAML, for human review |
| `tree_compiled` | JSONB | NOT NULL | Compiled JSON form used by evaluator |
| `published_at` | TIMESTAMPTZ | | NULL = draft |
| `published_by` | UUID | | |
| `notes` | TEXT | | Changelog |
| audit cols | | | |

**Indexes:** `UNIQUE (tree_id, version)`, `INDEX (tree_id) WHERE published_at IS NOT NULL`

### 11.4 `recommendations` (tenant schema)

Active recommendation lifecycle records.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `block_id` | UUID | NOT NULL | |
| `farm_id` | UUID | NOT NULL | Denormalized |
| `tree_id` | UUID | NOT NULL | FK to `public.decision_trees.id` (logical) |
| `tree_version` | INT | NOT NULL | Snapshot |
| `block_crop_id` | UUID | | The active crop assignment when generated |
| `action_type` | TEXT | NOT NULL, CHECK (`action_type IN ('irrigate','fertilize','spray','scout','harvest_window','prune','no_action','other')`) | |
| `parameters` | JSONB | NOT NULL | `{water_mm: 25, fertilizer_kg_per_ha: 40, ...}` |
| `confidence` | NUMERIC(4,3) | NOT NULL, CHECK (between 0 and 1) | Derived from input data quality |
| `tree_path` | JSONB | NOT NULL | Array of node IDs traversed — explainability |
| `text_en` | TEXT | NOT NULL | Human-readable explanation |
| `text_ar` | TEXT | | |
| `valid_until` | TIMESTAMPTZ | | When the recommendation expires |
| `state` | TEXT | NOT NULL, DEFAULT `'open'`, CHECK (`state IN ('open','applied','dismissed','deferred','expired')`) | |
| `applied_at` | TIMESTAMPTZ | | |
| `applied_by` | UUID | | |
| `dismissed_at` | TIMESTAMPTZ | | |
| `dismissed_by` | UUID | | |
| `dismissal_reason` | TEXT | | Used to improve trees |
| `deferred_until` | TIMESTAMPTZ | | |
| `outcome_notes` | TEXT | | Field-team feedback after applying |
| `evaluation_snapshot` | JSONB | NOT NULL | Input values that drove the recommendation |
| audit cols | | | |

**Indexes:**
- `INDEX (block_id, state, created_at DESC)`
- `INDEX (farm_id, state)`
- `INDEX (tree_id, tree_version, created_at DESC)`
- `INDEX (action_type, state)`

### 11.5 `recommendations_history` (tenant schema, hypertable)

State transitions and outcome tracking. Feeds future ML training.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `time` | TIMESTAMPTZ | NOT NULL | |
| `recommendation_id` | UUID | NOT NULL | |
| `block_id` | UUID | NOT NULL | |
| `farm_id` | UUID | NOT NULL | |
| `from_state` | TEXT | | |
| `to_state` | TEXT | NOT NULL | |
| `actor_user_id` | UUID | | |
| `details` | JSONB | | |

**Hypertable:** chunk 30d, compression after 90d, retention indefinite (training data).

---

## 12. `notifications` module

Channel dispatch and template rendering. Messages flow: alerts/recommendations modules emit events → notifications module renders templates → dispatches via SMTP / SSE / webhook → logs result.

### 12.1 ERD

```
public.notification_templates ──< (logical) tenant.notification_dispatches
tenant.notification_dispatches
tenant.in_app_inbox       -- pre-rendered messages for SSE / inbox UI
```

### 12.2 `public.notification_templates`

Templates for emails, in-app messages, webhooks. Maintained by platform team.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `code` | TEXT | NOT NULL, UNIQUE | `alert_fired_email`, `recommendation_created_in_app`, `webhook_alert_payload` |
| `channel` | TEXT | NOT NULL, CHECK (`channel IN ('email','in_app','webhook','sms')`) | sms is P2 |
| `subject_en` | TEXT | | Email only |
| `subject_ar` | TEXT | | |
| `body_en` | TEXT | NOT NULL | Jinja2 template |
| `body_ar` | TEXT | | |
| `variables_schema` | JSONB | NOT NULL | JSON schema for template variables |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT TRUE | |
| audit cols | | | |

### 12.3 `notification_dispatches` (tenant schema)

The dispatch log. One row per attempted send. Useful for support, debugging, and rate limiting.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `template_code` | TEXT | NOT NULL | |
| `channel` | TEXT | NOT NULL | |
| `recipient_user_id` | UUID | | NULL for webhook |
| `recipient_address` | TEXT | NOT NULL | Email, webhook URL, etc. |
| `source_kind` | TEXT | NOT NULL, CHECK (`source_kind IN ('alert','recommendation','system')`) | |
| `source_id` | UUID | NOT NULL | The alert.id or recommendation.id that triggered it |
| `payload` | JSONB | NOT NULL | Rendered content snapshot |
| `status` | TEXT | NOT NULL, DEFAULT `'pending'`, CHECK (`status IN ('pending','sent','failed','bounced')`) | |
| `attempt_count` | INT | NOT NULL, DEFAULT 0 | |
| `last_attempted_at` | TIMESTAMPTZ | | |
| `delivered_at` | TIMESTAMPTZ | | |
| `error_message` | TEXT | | |
| `external_id` | TEXT | | SMTP message-id, webhook response-id |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |

**Indexes:**
- `INDEX (status, last_attempted_at) WHERE status IN ('pending', 'failed')`
- `INDEX (source_kind, source_id)`
- `INDEX (recipient_user_id, created_at DESC) WHERE recipient_user_id IS NOT NULL`

### 12.4 `in_app_inbox` (tenant schema)

Pre-rendered in-app messages, what users see in the bell-icon inbox.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `recipient_user_id` | UUID | NOT NULL | |
| `source_kind` | TEXT | NOT NULL | `alert`, `recommendation`, `system` |
| `source_id` | UUID | NOT NULL | |
| `severity` | TEXT | | Mirrors source severity |
| `subject_rendered` | TEXT | NOT NULL | |
| `body_rendered_html` | TEXT | NOT NULL | |
| `link_url` | TEXT | NOT NULL | Deep link to relevant UI |
| `is_read` | BOOLEAN | NOT NULL, DEFAULT FALSE | |
| `read_at` | TIMESTAMPTZ | | |
| `created_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `expires_at` | TIMESTAMPTZ | | Auto-purge after this |

**Indexes:**
- `INDEX (recipient_user_id, is_read, created_at DESC)`
- `INDEX (source_kind, source_id)`
- `INDEX (expires_at) WHERE expires_at IS NOT NULL` — for purge job

---

## 13. `audit` module

Immutable record of significant domain events and sensitive data changes.

### 13.1 ERD

```
audit_events                    -- (hypertable) domain-level events
audit_data_changes              -- (regular) row-level changes on sensitive tables (pgaudit-fed)
```

### 13.2 `audit_events` (tenant schema, hypertable)

Domain-meaningful events written by the `audit` module's `record(event)` interface, called from every other module.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `time` | TIMESTAMPTZ | NOT NULL | When the event happened |
| `id` | UUID | NOT NULL | Event UUID |
| `event_type` | TEXT | NOT NULL | `farm.created`, `block.boundary_updated`, `alert.acknowledged`, `user.role_changed`, etc. |
| `actor_user_id` | UUID | | NULL for system actions |
| `actor_kind` | TEXT | NOT NULL, CHECK (`actor_kind IN ('user','system','integration')`) | |
| `correlation_id` | UUID | | Request correlation ID for tracing |
| `subject_kind` | TEXT | NOT NULL | `farm`, `block`, `alert`, `recommendation`, `user`, etc. |
| `subject_id` | UUID | NOT NULL | |
| `farm_id` | UUID | | Denormalized for filtering |
| `details` | JSONB | NOT NULL | Event-specific payload (before/after values, parameters) |
| `client_ip` | INET | | |
| `user_agent` | TEXT | | |

**Hypertable:**
- Chunk: 30 days
- Compression: after 60 days
- Retention: 2 years hot, then S3 export and detach

**Indexes:**
- `(subject_kind, subject_id, time DESC)`
- `(actor_user_id, time DESC) WHERE actor_user_id IS NOT NULL`
- `(event_type, time DESC)`
- `(farm_id, time DESC) WHERE farm_id IS NOT NULL`
- `(correlation_id) WHERE correlation_id IS NOT NULL`

**Important:** `audit_events` is **append-only**. No UPDATE or DELETE permissions are granted to application roles; only the migration role can alter the table.

### 13.3 `audit_data_changes` (tenant schema)

Captures row-level changes on sensitive tables (`users`, `tenant_role_assignments`, `farm_scopes`, `tenant_subscriptions`). Populated by **pgaudit** extension or by row-level triggers — pick one consistently. Recommendation: triggers for the small set of sensitive tables (more control); pgaudit for cluster-wide DDL/DCL audit (security posture).

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `changed_at` | TIMESTAMPTZ | NOT NULL, DEFAULT now() | |
| `actor_user_id` | UUID | | |
| `table_schema` | TEXT | NOT NULL | |
| `table_name` | TEXT | NOT NULL | |
| `row_pk` | UUID | NOT NULL | The PK of the row that changed |
| `operation` | TEXT | NOT NULL, CHECK (`operation IN ('INSERT','UPDATE','DELETE')`) | |
| `before_data` | JSONB | | NULL on INSERT |
| `after_data` | JSONB | | NULL on DELETE |
| `correlation_id` | UUID | | |

**Indexes:** `INDEX (table_schema, table_name, row_pk, changed_at DESC)`, `INDEX (actor_user_id, changed_at DESC)`

---

## 14. `analytics` module — views & continuous aggregates

No tables of its own. Composed of TimescaleDB continuous aggregates over hot hypertables, plus regular views over the operational tables. All defined in `tenant_<id>` schema (the continuous aggregates) or `public` (the platform views).

### 14.1 Continuous aggregates (TimescaleDB)

```sql
-- Daily index aggregate per block
CREATE MATERIALIZED VIEW block_index_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS day,
    block_id,
    index_code,
    avg(mean) AS mean,
    min(min) AS min,
    max(max) AS max,
    sum(valid_pixel_count) AS valid_pixels,
    avg(valid_pixel_pct) AS valid_pct
FROM block_index_aggregates
GROUP BY day, block_id, index_code;

-- Refresh policy: every 1 hour, lookback 2 days
```

```sql
-- Weekly index aggregate per block, used by recommendation evaluator
CREATE MATERIALIZED VIEW block_index_weekly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('7 days', time) AS week,
    block_id,
    index_code,
    avg(mean) AS mean,
    stddev(mean) AS std_of_means
FROM block_index_aggregates
GROUP BY week, block_id, index_code;
```

```sql
-- Hourly weather rollup per farm
CREATE MATERIALIZED VIEW weather_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS hour,
    farm_id,
    avg(air_temp_c) AS air_temp_c,
    sum(precipitation_mm) AS precip_mm,
    avg(et0_mm) AS et0_mm
FROM weather_observations
GROUP BY hour, farm_id;
```

```sql
-- Alert frequency per rule per day
CREATE MATERIALIZED VIEW alert_rule_daily_count
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS day,
    rule_id,
    count(*) FILTER (WHERE to_state = 'open') AS firings
FROM alerts_history
GROUP BY day, rule_id;
```

### 14.2 Regular views

```sql
-- Active alerts with denormalized rule + scope info, drives the alerts page
CREATE VIEW v_active_alerts AS
SELECT
    a.id, a.severity, a.state, a.fired_at,
    a.farm_id, f.name AS farm_name,
    a.block_id, b.name AS block_name,
    r.id AS rule_id, r.name AS rule_name
FROM alerts a
JOIN farms f ON a.farm_id = f.id
LEFT JOIN blocks b ON a.block_id = b.id
JOIN alert_rules r ON a.rule_id = r.id
WHERE a.state IN ('open', 'acknowledged', 'snoozed');
```

```sql
-- Block dashboard view: current crop, latest indices, latest weather
CREATE VIEW v_block_dashboard AS
SELECT
    b.id AS block_id,
    b.farm_id,
    b.name,
    b.area_m2,
    bc.crop_id,
    bc.season_label,
    bc.planting_date,
    bc.growth_stage,
    -- latest NDVI per block (LATERAL subquery for performance)
    (SELECT mean FROM block_index_aggregates
       WHERE block_id = b.id AND index_code = 'ndvi'
       ORDER BY time DESC LIMIT 1) AS ndvi_latest,
    (SELECT time FROM block_index_aggregates
       WHERE block_id = b.id AND index_code = 'ndvi'
       ORDER BY time DESC LIMIT 1) AS ndvi_latest_time
FROM blocks b
LEFT JOIN block_crops bc ON bc.block_id = b.id AND bc.is_current = TRUE
WHERE b.deleted_at IS NULL;
```

```sql
-- Farm summary view, drives the farm card list
CREATE VIEW v_farm_summary AS
SELECT
    f.id, f.name, f.area_m2, f.governorate,
    count(b.id) FILTER (WHERE b.deleted_at IS NULL) AS active_blocks,
    count(a.id) FILTER (WHERE a.state = 'open') AS open_alerts
FROM farms f
LEFT JOIN blocks b ON b.farm_id = f.id
LEFT JOIN alerts a ON a.farm_id = f.id
WHERE f.deleted_at IS NULL
GROUP BY f.id;
```

These views are stable APIs for the dashboard. Phase 2's Apache Superset will connect to the same views directly.

---

## 15. Cross-cutting concerns

### 15.1 Deferrable foreign keys
All FKs are `INITIALLY IMMEDIATE` by default. Migrations that reorder data set them `DEFERRABLE INITIALLY DEFERRED` for the duration of the migration only.

### 15.2 Multi-schema migrations
Alembic alone manages `public`. A custom runner (`scripts/migrate_tenants.py`) iterates `public.tenants` and applies tenant-schema migrations to each, with checkpointing so a failed mid-batch run can resume. Migrations must be **N+1 backward compatible** — code from version N must work against schema N+1 — to allow zero-downtime deploys. We do this by:
1. Always adding columns as nullable first; backfill; tighten in next release.
2. Renames done as `add new → dual-write → migrate readers → drop old` over two releases.
3. Drops always done one release after readers stop using the column.

### 15.3 RLS policies on shared tables
Shared tables that store any tenant-scoped reference data (none in MVP) would have:

```sql
ALTER TABLE public.<table> ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON public.<table>
  FOR ALL
  USING (tenant_id::text = current_setting('app.current_tenant_id', TRUE));
```

Set in tenancy middleware: `SET LOCAL app.current_tenant_id = '<tenant_uuid>'`.

### 15.4 Connection pool sizing
With ~12 services each holding a pool, target Postgres `max_connections = 200` for MVP. PgBouncer in transaction-pooling mode in front of Postgres recommended once we exceed 50 active app instances or 200 tenants.

### 15.5 Backup & PITR
- WAL archiving every 5 minutes via CloudNativePG to S3.
- Base backup nightly.
- PITR window: 30 days.
- Tenant-level restore (P2): export single tenant schema to a separate database, replay WAL, extract schema. Until then, restore is platform-wide.

### 15.6 Estimated row counts at MVP and Year 3

| Table | MVP (3 tenants × 10 blocks × 1 yr) | Year 3 (500 tenants × 50 blocks × 3 yr) | Notes |
|---|---|---|---|
| `farms` | ~9 | ~2,500 | |
| `blocks` | ~30 | ~25,000 | |
| `block_index_aggregates` | ~13K | ~110M | 6 indices × 73/yr × blocks × yrs |
| `weather_observations` | ~26K | ~13M | hourly × farms × yrs |
| `weather_forecasts` | ~440K | ~220M | retention drops this; aggregates kept |
| `signal_observations` | ~5K | ~5M | varies wildly with IoT |
| `alerts` (open) | <100 | <10K | |
| `alerts_history` | ~1K | ~1M | |
| `recommendations` | ~100 | ~100K | |
| `audit_events` | ~10K | ~50M | |

Year 3 totals are well within single-instance Postgres + TimescaleDB capability. We'd likely shard or split TimescaleDB out at year 3+ if growth continues.

---

## 16. Open questions / decisions to revisit

These are deliberately deferred but should not be forgotten:

1. **`forecasting` module schema** — parked. Will need ground-truth harvest weight tables and a model-versioning scheme.
2. **IoT signal ingestion** — `signals` shape supports it; the ingestion API and machine-to-machine auth via Keycloak service accounts is a P2 build.
3. **Cross-tenant `ExternalAdvisor` users** — the `tenant_memberships` shape supports it, but UX and permission semantics need design.
4. **Tenant data export & deletion** — for compliance / contract exit. Needs a per-tenant export job that bundles every schema row to JSON/CSV/GeoJSON in S3.
5. **Translation of seeded reference data** — crop names already covered (`name_en`, `name_ar`). Decision-tree node text and recommendation text strings: handled per-version in `tree_yaml`.
6. **`alert_rule_versions`** table — currently rules are mutated in place with a `version` counter; full version history (analogous to `decision_tree_versions`) is P2.
7. **GIS performance at scale** — at year 3 we may need partitioned PostGIS tables by farm cluster; revisit when block count crosses ~50K.

---

*End of document.*
