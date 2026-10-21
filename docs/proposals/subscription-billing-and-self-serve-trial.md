# Subscription, billing, and the self-serve trial

**Status:** design agreed, nothing built.
**Authoritative:** this file. A shared copy exists as a Google Doc; if the two
disagree, this file wins.
**Roadmap entry:** Prompt 8 in `prompts/roadmap.md`.

Every money figure here is a placeholder. The financial analysis fills them in.
The market research behind the ranges is summarised in § 12.

---

## 1. Vocabulary

"Subscription" already means three things in this codebase:

| Name | Meaning |
|---|---|
| `ImageryAoiSubscription` | a farm area registered for satellite imagery fetch |
| `WeatherSubscription` | a point registered for weather fetch |
| `TenantSubscription` | the commercial plan, `public.tenant_subscriptions` |

The new module is `billing`. Inside it the words are **plan**, **term**, **price
list**, **rate**, **meter** and **entitlement**. Never "subscription".

A second collision: `BillingAdmin` in `role_capabilities.yaml` is a **tenant**
role — the customer's own billing person. The new platform role is
`PlatformBillingAdmin`.

---

## 2. What already exists

| Thing | Where | State |
|---|---|---|
| `tenant_subscriptions` | `public`, tenancy module | Has `tier`, `plan_type`, `price_per_feddan`, `trial_start`, `trial_end`, `started_at`, `expires_at`, `is_current`, `feature_flags` |
| Tier names | `tenancy/router.py:201`, `schemas.py:27` | `free`, `standard`, `premium`, `enterprise`. Labels only. |
| `feature_flags` | `tenancy/service.py` | Stored and shown. **Read by nothing.** No tier is enforced anywhere today. |
| Area | `farms.area_m2`, `blocks.area_m2` | One canonical unit. Feddan, hectare, dunum are display only. |
| Crop per block | `block_crops`, tenant schema | `crop_id`, `crop_path`, valid time `[effective_from, effective_to)` |
| Crop catalogue | `public.crops` | Read-mostly. A real foreign key from billing is allowed. |
| `create_tenant` | `tenancy/service.py:376` | Already takes `initial_tier="free"`, `owner_email`, `default_unit_system="feddan"` |
| `retry_provisioning` | `tenancy/service.py:544` | Exists. The self-serve flow depends on it. |
| RBAC | `shared/rbac/*.yaml`, `CapabilityRegistry` | Enforced by `requires_capability`. Capability names are stable: add, never rename. |
| Platform roles | `admins_service.py`, `admins_router.py`, `auth/context.py` | Only `PlatformAdmin` (wildcard `*`) and `PlatformSupport` |

`price_per_feddan` holds one rate for a whole tenant. Under a per-crop rate card
it is wrong. Stop writing it, keep it one release, then drop it.

---

## 3. Decisions (locked — do not re-litigate)

1. **Free is a time-limited trial**, not a permanent tier. A platform admin can
   extend it, as an audited write with a reason.
2. **At trial end the tenant becomes read-only.** Sign-in works, data is visible,
   writes are blocked, background jobs stop. Paying restores it.
3. **One dollar rate per feddan per crop**, plus one default rate. Not a
   multiplier on a base rate.
4. **Rates are maintained on their own screen**, not on the crop catalogue
   screen. The catalogue stays about agronomy.
5. **A published price list is immutable.** Changing a rate means publishing a
   new version. A term pins the version for a year.
6. **A block's billing crop is pinned** the first time the block enters the
   meter, and does not change until renewal.
7. **Volume discount is a percentage on the whole bill.** Rates never change.
8. **The contract belongs to the tenant**, not the farm. One term, one meter,
   one invoice.
9. **Enterprise is a committed area** at negotiated rates. Area above the
   commitment bills at the normal rate.
10. **Every rate and threshold is editable in the interface.** No number in
    `settings.py`, in a Python constant, or in a frontend constant.
11. **`PlatformAdmin` keeps access through its wildcard.** No deny list is added
    to `CapabilityRegistry`. The control is the audit trail, not the role list.

---

## 4. The pricing model

### 4.1 Per block, on a meter date

```
crop_b  = the billing crop pinned to block b for this term
rate_b  = rate(pinned_price_list, crop_b)
          or default_rate(pinned_price_list) if that crop has no rate
area_b  = block.area_m2 / 4200        (feddan)
line_b  = area_b × rate_b
```

### 4.2 Per term

```
A_total    = Σ area_b
Gross      = Σ line_b
Area_fee   = max( Gross , M_units × R_default )
Seat_fee   = max(0, seats_used − S_inc) × p_seat
Subtotal   = B_base + Area_fee + Seat_fee + Σ addons
Discount   = discount_pct(A_total)  or the negotiated override on the term
Price_term = Subtotal × (1 − Discount) × k_term
```

The minimum is expressed in units. The shortfall between the real area and the
minimum is priced at the default rate, because a customer below the minimum has
no crop mix to average.

### 4.3 Variables the financial analysis must fill

| Variable | Meaning | Set by |
|---|---|---|
| `R_crop[c]` | Dollars per feddan per year, per crop | price list |
| `R_default` | Rate for a crop with no rate of its own | price list |
| `B_base` | Platform fee per term, per tier | price list |
| `M_units` | Minimum billable feddan | price list |
| `discount_pct(A)` | Size table: thresholds and percentages | price list |
| `S_inc`, `p_seat` | Included seats, price per extra seat | price list |
| `k_term` | Annual prepay factor. 1.0 monthly. | price list |
| `D_trial` | Trial length in days | price list, per-tenant override |
| `A_free`, `F_free`, `S_free` | Trial caps: feddan, farms, seats | price list |
| `G_readonly` | Days read-only before archive | price list |
| `A_commit`, `R_commit` | Enterprise commitment and its rate | negotiated, on the term |
| `d_override` | Negotiated discount, replaces the size table | negotiated, on the term |

### 4.4 Worked example

| Farm | Area | Pinned crop | Rate | Line |
|---|---|---|---|---|
| A | 5,000 fd | wheat | $3.50 | $17,500 |
| B | 400 fd | mango | $12.00 | $4,800 |
| B | 600 fd | citrus | $10.50 | $6,300 |

```
A_total  = 6,000 fd        Gross    = $28,600
B_base   = $1,800          Seats    = 12 used, 10 included, 2 × $180 = $360
Subtotal = $30,760         Discount = 10%
Total    = $27,684 per year   ($4.61 per feddan)
```

### 4.5 Area units

Rates are always stored per feddan. Display unit is a per-tenant setting and
changes nothing about the price.

| Display unit | Divide `area_m2` by |
|---|---|
| feddan | 4,200 |
| hectare | 10,000 |
| dunum, Levant and Gulf | 1,000 |
| dunum, Iraq | 2,500 |
| acre | 4,046.86 |

**Store two constants for dunum.** Iraq and Jordan use the same word for areas
that differ by 2.5 times. One shared constant bills Iraqi customers 2.5× wrong.

---

## 5. The three tiers

| | Free trial | Subscription | Enterprise |
|---|---|---|---|
| Cost | 0 | `B_base` + per feddan per crop | negotiated rates, committed area |
| Length | `D_trial` days, extendable | 12 months, renews | 12 to 36 months |
| Area | capped at `A_free` | unlimited, minimum `M_units` | unlimited, minimum `A_commit` |
| Farms | `F_free` | unlimited | unlimited |
| Seats | `S_free` | `S_inc`, then `p_seat` | unlimited |
| Rate card | not billed | published list, pinned | rates on the term |
| Discount | none | size table | negotiated override |
| At end | read-only | renews, or read-only if unpaid | negotiated |

### 5.1 The commitment and the minimum are one mechanism

```
Area_fee = max( Σ(area_b × rate_b) , floor_units × floor_rate )
```

- **Subscription:** `floor_units = M_units`, `floor_rate = R_default`. A small
  floor so a five-feddan customer does not cost more to invoice than they pay.
- **Enterprise:** `floor_units = A_commit`, `floor_rate = R_commit`. A large
  floor that guarantees the revenue.

Area above the commitment needs no overage rate — it is already inside the sum.
One formula, one code path to test.

### 5.2 Tier names

The enum has four values, the design has three. Map `free` to the trial,
`standard` to Subscription, `enterprise` to Enterprise, and stop issuing
`premium`. Leave the value in the enum so existing rows stay valid.

---

## 6. The locks

A term pins three things at start and nothing moves them until renewal: the
price list version, each block's billing crop, and the tier with its fees.

**Area is not pinned.** Adding or removing blocks changes the quantity, so the
invoice still moves during the year. That is the only part a customer changes.

### 6.1 Why a version, not an edit

A price list an admin can edit in place is not locked. The next edit would
rewrite what every existing contract owes, including terms already invoiced.

### 6.2 Pinning the crop

> A block's billing crop is pinned the first time the block enters the meter,
> and does not change until renewal.

| Case | Result |
|---|---|
| Block exists at term start | pinned to the crop valid on the term start date |
| Block added in month 3 | pinned to the crop valid that day, priced from the pinned list |
| Block has no crop at pin time | pinned to "none", billed at `R_default` |
| Block switches wheat → mango in month 4 | keeps paying wheat until renewal |
| Block goes fallow in month 7 | keeps paying its pinned rate until renewal |
| Block deleted or deactivated | leaves the meter from that date |
| Renewal | every block re-pins; the term re-pins to the current published list |

At renewal the screen must show the difference before it is applied.

---

## 7. The self-serve trial

A website visitor provisions their own trial tenant. Nothing in the product does
this today: `create_tenant` is behind `platform.manage_tenants`, and there is no
unauthenticated route surface anywhere in the API.

### 7.1 The flow

**Stage 1 — the form.** On the marketing site (Cloudflare Workers): full name,
work email, organisation name, country, phone (optional), accept terms. A
Cloudflare Turnstile token rides with the post — the site is already on
Cloudflare, so this needs no third-party script.

**Stage 2 — `POST /api/v1/public/trial/signups`** (unauthenticated).
Validates, checks Turnstile, rate-limits by IP and by email domain, writes a
`trial_signups` row with status `pending_verification`, and emails a signed,
single-use, expiring verification link.
**It always returns `202` with the same body**, whether or not the address is
already known. No account enumeration.

**Stage 3 — `GET /api/v1/public/trial/verify?token=…`.**
Marks the signup `verified`, then routes it:

| Condition | Result |
|---|---|
| Email domain matches an active tenant | `routed_to_existing`. The page says to ask their administrator for an invitation. **No second tenant is created.** |
| Free-mail or disposable domain | `held` for platform review (configurable) |
| Otherwise | `provisioning`, and the provisioning task is enqueued |

**Stage 4 — provisioning**, in a Celery task, never inline in the request.

1. Generate a unique slug from the organisation name, with a numeric suffix on
   collision. A visitor must never see a 409.
2. `create_tenant(initial_tier="free", owner_email=…, default_unit_system="feddan")`.
3. Set `trial_start = today`, `trial_end = today + D_trial` from the published
   price list, and pin `price_list_id`.
4. **Report success only when `keycloak_provisioning == "succeeded"`.** On
   `pending`, hold the signup in `provisioning`, retry with backoff through the
   existing `retry_provisioning`, and raise a platform alert after N attempts.
5. On success, email a "set your password" link and mark `provisioned`.

**Stage 5 — first sign-in.** The owner sets a password, lands in the app with
the `TenantOwner` role, and is walked through drawing one farm and picking a
crop. Trial caps apply: `A_free` feddan, `F_free` farms, `S_free` seats.

**Stage 6 — trial life.** Reminder emails at D−7 and D−1. At `D_trial` the
tenant goes read-only. A platform admin can extend `trial_end` with a reason.

### 7.2 Abuse and cost controls

An unauthenticated endpoint that creates a Postgres schema per call is a
resource attack surface, and a trial tenant that draws a farm starts imagery and
weather fetch that cost real money.

- **Nothing is provisioned from an unverified address.** Email verification
  comes before any tenant exists.
- Turnstile on the form. Rate limits per IP and per email domain. A global cap
  on trials provisioned per hour, with the excess queued rather than dropped.
- A disposable-domain blocklist.
- One live trial per verified email, and one per organisation domain.
- `A_free` caps area. The trial carries its own imagery cadence entitlement, so
  a trial cannot cost what a paying tenant costs.
- A trial tenant whose owner never signs in is archived after `G_readonly` days.

### 7.3 What this needs that does not exist

- **An unauthenticated route surface.** Every route today sits behind
  `requires_capability`. `app_factory.py` needs a public router with its own
  rate limiting, and it must be excluded from the tenant-context middleware,
  because at that point there is no tenant.
- **Four email templates**: verify address, set password, trial ending, trial
  ended. Reuse the existing template machinery.
- **A Turnstile secret** in the shared chart.

---

## 8. Data model

All new tables are in `public`, because billing is a platform concern and
`tenant_subscriptions` is already there.

| Table | Key columns | Purpose |
|---|---|---|
| `billing_price_lists` | version, name, currency, status (`draft`/`published`/`superseded`), `default_rate_per_feddan`, `base_fee`, `minimum_units`, `included_seats`, `seat_price`, `annual_factor`, `trial_days`, trial caps, `readonly_grace_days`, `published_at`, `published_by` | one immutable version of the whole rate card |
| `billing_crop_rates` | `price_list_id`, `crop_id` (FK `public.crops`), `rate_per_feddan`; unique on the pair | the dollar figure per feddan per crop |
| `billing_discount_bands` | `price_list_id`, `from_units`, `to_units`, `discount_pct` | the size table |
| `billing_block_crop_pins` | `subscription_id`, `tenant_id`, `farm_id`, `block_id`, `crop_id`, `pinned_on`, `unpinned_on` | the crop lock, one row per block per term |
| `billing_meter_readings` | `tenant_id`, `subscription_id`, `read_on`, `farm_id`, `block_id`, `crop_id`, `rate_per_feddan`, `area_m2`, `area_feddan`, `amount` | append-only; the evidence behind every invoice |
| `billing_invoices` | `tenant_id`, `subscription_id`, period, currency, `subtotal`, `discount_pct`, `total`, `status` | the bill |
| `billing_invoice_lines` | `invoice_id`, `kind` (base/area/seat/addon/discount), `crop_id`, `units`, `unit_price`, `amount` | the lines |
| `billing_entitlements` | `tier`, `capability`, `value` (jsonb) | what a tier may do; read by `requires_capability` |
| `trial_signups` | email, `email_normalised`, name, org, country, locale, phone, `source` (utm), `ip_hash`, `turnstile_ok`, `status`, `verification_token_hash`, `verification_expires_at`, `verified_at`, `tenant_id`, `provisioning_attempts`, `last_error`, `held_reason` | the funnel record |

`trial_signups.status`: `pending_verification`, `verified`, `held`,
`provisioning`, `provisioned`, `routed_to_existing`, `rejected`, `expired`.
A partial unique index on `email_normalised` where the status is not `rejected`
or `expired` enforces one live trial per address.

### 8.1 Columns to add to `tenant_subscriptions`

Each row already behaves like a term — it has `started_at`, `expires_at` and
`is_current`. Reuse it rather than adding a rival table.

```
price_list_id    uuid  FK billing_price_lists
base_fee         numeric(10,2)
minimum_units    numeric(12,2)
minimum_rate     numeric(10,2)
committed_units  numeric(12,2)   -- enterprise
discount_pct     numeric(5,2)    -- negotiated override, null = size table
included_seats   integer
seat_price       numeric(10,2)
billing_period   text            -- monthly | annual
currency         char(3)
```

### 8.2 Rules the schema must respect

- **No foreign key from `public` into a tenant schema.**
  `billing_block_crop_pins.block_id` and `farm_id` are logical UUIDs with no
  foreign key. `crop_id` may have a real one, because `public.crops` is in the
  same schema.
- **The meter loops tenants and reads tenant-schema tables.** Each iteration
  needs its own SAVEPOINT, or one bad tenant kills the whole run.
- Every new tenant-scoped table must join the purge manifest, or CI fails.

---

## 9. The meter

- Runs on the first day of each month.
- For each active tenant and each active block, writes one
  `billing_meter_readings` row from the pinned crop and the pinned price list.
- **Never reads `block_crops` for pricing.** It reads it only when a new block
  needs a pin.
- The invoice is built from the readings, not recomputed from live data. That is
  what makes "why did my bill change" answerable a year later.
- The current billable area is visible to the customer in the app, not only on
  the invoice.

---

## 10. Entitlements and enforcement

No tier is enforced anywhere today. This is the piece with no substitute.

Every entitlement is read through the existing `requires_capability`. Anything
that invents a second check will drift and end up inert, the way `feature_flags`
did.

| Entitlement | Trial | Subscription | Enterprise |
|---|---|---|---|
| `max_farms` | `F_free` | unlimited | unlimited |
| `max_area_feddan` | `A_free` | unlimited | unlimited |
| `max_seats` | `S_free` | `S_inc`, then paid | unlimited |
| `indices` | basic set | all 13 | all 13 |
| `imagery_cadence_days` | trial value | tenant setting | tenant setting |
| `weather_indices`, `scouting_app`, `decision_trees`, `recommendations`, `reports_export` | to confirm | yes | yes |
| `api_access` | no | add-on | yes |
| `sso`, `data_residency`, `sla`, `on_premises` | no | no | yes |
| `writes_allowed` | until trial end | while paid | yes |

**Open item.** Which features are in the trial basic set is a product decision.
It changes what a prospect sees before they buy.

---

## 11. Access control

### 11.1 New capabilities (platform scope)

| Capability | Allows |
|---|---|
| `platform.pricing.read` | view price lists, rates, bands, the platform meter |
| `platform.pricing.manage` | create and edit a draft price list |
| `platform.pricing.publish` | publish a version, which binds every new contract |
| `platform.subscription.manage` | set a tenant's tier, term, discount, commitment; extend a trial |
| `platform.trial.read` | view the trial signup queue |
| `platform.trial.manage` | approve, reject, resend verification, force provisioning |

Publish is separate from manage on purpose. Editing a draft is reversible;
publishing is not.

Tenant scope is unchanged. `subscription.read` already covers a customer seeing
their own plan, meter and invoices.

### 11.2 Roles

| Role | Scope | Access |
|---|---|---|
| `PlatformBillingAdmin` (new) | platform | `platform.read`, `tenant.read`, and all six new capabilities |
| `PlatformAdmin` | platform | holds `*`, inherits them |
| `PlatformSupport` | platform | `subscription.read` and `platform.trial.read`. No pricing. |
| `BillingAdmin` | tenant | unchanged; the customer's own subscription only |

### 11.3 Registering a new platform role — every place

The role list lives in seven places across two backend files alone. Change one
and miss another, and the role can be granted but not listed, or listed but
rejected on grant.

| File | What to change |
|---|---|
| `shared/rbac/capabilities.yaml` | the six new capabilities |
| `shared/rbac/role_capabilities.yaml` | the new role |
| `platform_admins/admins_service.py` | allow-list at **line 113 and line 306** — two copies |
| `platform_admins/admins_router.py` | five `Literal["PlatformAdmin", "PlatformSupport"]` at lines 51, 61, 68, 118, 156 |
| `shared/auth/context.py` | line 21 |
| `shared/keycloak/` | `set_platform_role` and the test fakes |
| `frontend/src/rbac/capabilities.ts` | `PlatformRole` at line 106, and the capability sets |
| `frontend/src/api/platformAdminsRoles.ts:3`, `PlatformAdminsPage.tsx:23` | the role type and the `ROLES` array |

The Keycloak realm must also accept the new `platform_role` attribute value.

### 11.4 Audit

Every write goes through the audit module: who, when, old value, new value.
Publishing a price list, extending a trial, and setting a negotiated discount or
commitment each require a typed reason. Without it, "the price changed and
nobody knows why" cannot be answered a year later, which is when it is asked.

---

## 12. Screens

| Screen | Capability |
|---|---|
| Crop rates and price list editor | `platform.pricing.manage` |
| Publish a version | `platform.pricing.publish` |
| Version history and difference view | `platform.pricing.read` |
| Tenant subscription, including extend trial | `platform.subscription.manage` |
| Platform meter viewer | `platform.pricing.read` |
| Invoices | `platform.pricing.read` |
| Trial signup queue | `platform.trial.read` / `platform.trial.manage` |
| A customer's own billing page | `subscription.read` |

The crop rate screen reads the crop list from the catalogue but is not part of
the catalogue screen.

---

## 13. What the market charges

Source research, August 2026. Almost nobody publishes a rate card: of ten
comparable platforms, four publish a number and six do not.

| Vendor | Published price | US$/ha/yr | US$/feddan/yr |
|---|---|---|---|
| Semios (permanent crops) | from $60/acre/yr | 148 | 62 |
| Farmonaut (API) | ~$2.69/acre/yr | 6.6 | 2.8 |
| Siora (soil analysis) | from €5/ha | 5.4 one-off | 2.3 |
| CropSense | $0.50–$1.00/ha | 0.5–1.0 | 0.21–0.42 |
| Climate FieldView | $649/yr flat, Plus | 1.3 at 500 ha | 0.5 at 1,190 fd |

Two bands, not one disagreement: field crops sell at **$1–7 per hectare per
year**, permanent crops at **$60–150**. Both sit under about **1 percent of crop
gross revenue per area**. That is the ceiling to price against.

Market size, for scale: arable land is **137.05 million feddan** across the Arab
countries and **41.92 million feddan** in the core Middle East. Egypt has over
10 million feddan cultivated but roughly 90 percent of holdings are under 3
feddan, so per-feddan selling reaches the reclamation and corporate block —
about 1.6 to 3 million feddan today — not the Delta smallholder.

---

## 14. Build order

1. Price list tables, crop rates, discount bands, the six capabilities, the
   `PlatformBillingAdmin` role, and the admin screens to maintain and publish.
2. Entitlements table, wired into `requires_capability`.
3. Trial state, trial extension with audit, and the read-only state at trial end.
4. The public signup surface, verification, and provisioning.
5. Crop pinning and the monthly meter, visible to the customer in the app.
6. Price calculation and invoice generation.
7. Renewal, with a screen showing the rate difference before it applies.
8. Enterprise commitment fields and negotiated rate overrides.

Steps 1 to 4 give a product with tiers that mean something and a front door.
Steps 5 to 8 turn it into a bill.

---

## 15. Open questions

1. Which features are in the trial basic set.
2. Auto-provision on email verification, or hold every signup for review?
3. Free-mail addresses (gmail, hotmail): allow, hold, or reject?
4. Does a trial start with a seeded demo farm, so a visitor sees something in
   two minutes, or empty?
5. Does the signup form live on the marketing site or on a page in the app?
6. Does a block with no crop bill at the default rate or at zero? This design
   assumes the default rate.
7. How long read-only lasts before archive and purge.
8. Does reactivation backfill the imagery and weather gap, or start fresh?
9. Are invoices produced here or handed to an outside accounting tool? This
   design produces them here.
10. Currency — one US dollar price list for the first release is assumed.
11. Tax. Not modelled. Egypt and Saudi Arabia both charge VAT on software.
