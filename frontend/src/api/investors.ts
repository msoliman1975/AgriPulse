// Mirrors backend/app/modules/investors/schemas.py — keep in lock-step.
//
// A holding is a drawn area inside one block that an investor owns. Design:
// docs/proposals/investor-holdings-design.html.

import type { Polygon } from "geojson";

import { apiClient } from "./client";

export type InvestorType = "person" | "company";
export type InvestorStatus = "not_invited" | "invited" | "active" | "suspended" | "archived";
export type InvestorLanguage = "ar" | "en";
export type IdType = "national_id" | "passport" | "commercial_register" | "other";
/** `sold` is derived (has a current owner); `archived` goes through `:archive`. */
export type HoldingStatus = "draft" | "available" | "sold" | "archived";
export type HoldingWritableStatus = "draft" | "available";
export type AcquiredBy = "purchase" | "transfer" | "inheritance" | "other";
export type EndedBy = "resale" | "buyback" | "contract_end" | "correction" | "other";
export type OwnershipPeriod = "past" | "current" | "future";

export interface Investor {
  id: string;
  code: string;
  investor_type: InvestorType;
  full_name: string;
  full_name_ar: string | null;
  contact_person: string | null;
  email: string;
  phone: string | null;
  national_id_type: IdType | null;
  national_id_last4: string | null;
  nationality: string | null;
  country: string | null;
  city: string | null;
  preferred_language: InvestorLanguage;
  user_id: string | null;
  status: InvestorStatus;
  relationship_manager_id: string | null;
  notes_internal: string | null;
  invited_at: string | null;
  last_app_seen_at: string | null;
  archived_at: string | null;
  current_holdings_count: number;
  /** Decimal as a string, in m². */
  current_area_m2: string;
  created_at: string;
  updated_at: string;
}

export interface Ownership {
  id: string;
  holding_id: string;
  holding_code: string;
  holding_name: string;
  holding_name_ar: string | null;
  farm_id: string;
  farm_name: string | null;
  farm_name_ar: string | null;
  block_id: string;
  block_code: string | null;
  investor_id: string;
  investor_code: string;
  investor_name: string;
  investor_name_ar: string | null;
  start_date: string;
  end_date: string | null;
  acquired_by: AcquiredBy;
  ended_by: EndedBy | null;
  contract_ref: string | null;
  period: OwnershipPeriod;
  area_m2: string;
  created_at: string;
}

/** An investor as seen from one farm. */
export interface FarmInvestor extends Investor {
  holdings_in_farm: number;
  area_in_farm_m2: string;
  other_farms: number;
  other_farm_holdings: number;
}

export interface InvestorDetail extends Investor {
  ownerships: Ownership[];
}

export interface InvestorPayload {
  code?: string | null;
  investor_type?: InvestorType;
  full_name?: string;
  full_name_ar?: string | null;
  contact_person?: string | null;
  email?: string;
  phone?: string | null;
  national_id_type?: IdType | null;
  national_id_last4?: string | null;
  nationality?: string | null;
  country?: string | null;
  city?: string | null;
  preferred_language?: InvestorLanguage;
  notes_internal?: string | null;
}

export interface HoldingOwnerSummary {
  ownership_id: string;
  investor_id: string;
  investor_code: string;
  investor_name: string;
  investor_name_ar: string | null;
  since: string;
  /** Current holdings the same investor has on other farms. */
  other_farm_holdings: number;
}

export interface Holding {
  id: string;
  code: string;
  farm_id: string;
  farm_name: string | null;
  farm_name_ar: string | null;
  block_id: string;
  block_code: string | null;
  block_name: string | null;
  block_name_ar: string | null;
  name: string;
  name_ar: string | null;
  boundary: Polygon;
  area_m2: string;
  block_area_m2: string;
  /** Holding area ÷ block area × 100. Staff only. */
  share_pct: string;
  tree_count: number | null;
  status: HoldingStatus;
  notes_internal: string | null;
  current_owner: HoldingOwnerSummary | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface HoldingDetail extends Holding {
  ownerships: Ownership[];
}

export interface BlockHoldingsContext {
  block_id: string;
  block_code: string | null;
  block_name: string | null;
  block_name_ar: string | null;
  farm_id: string;
  boundary: Polygon;
  block_area_m2: string;
  eligible: boolean;
  ineligible_reason: string | null;
  holdings: Holding[];
  sold_area_m2: string;
  unsold_area_m2: string;
}

export interface HoldingCreatePayload {
  code?: string | null;
  name: string;
  name_ar?: string | null;
  boundary: Polygon;
  tree_count?: number | null;
  status?: HoldingWritableStatus;
  notes_internal?: string | null;
}

export interface HoldingUpdatePayload {
  name?: string;
  name_ar?: string | null;
  boundary?: Polygon;
  tree_count?: number | null;
  status?: HoldingWritableStatus;
  notes_internal?: string | null;
}

export interface OwnershipCreatePayload {
  investor_id: string;
  start_date: string;
  acquired_by?: AcquiredBy;
  contract_ref?: string | null;
  previous_ended_by?: EndedBy;
}

// ---- Investors ------------------------------------------------------------

export async function listInvestors(
  params: { status?: InvestorStatus; q?: string; include_archived?: boolean } = {},
): Promise<Investor[]> {
  const { data } = await apiClient.get<Investor[]>("/v1/investors", { params });
  return data;
}

export async function listFarmInvestors(
  farmId: string,
  params: { status?: InvestorStatus; q?: string; include_archived?: boolean } = {},
): Promise<FarmInvestor[]> {
  const { data } = await apiClient.get<FarmInvestor[]>(`/v1/farms/${farmId}/investors`, {
    params,
  });
  return data;
}

export async function getInvestor(investorId: string): Promise<InvestorDetail> {
  const { data } = await apiClient.get<InvestorDetail>(`/v1/investors/${investorId}`);
  return data;
}

export async function createInvestor(payload: InvestorPayload): Promise<Investor> {
  const { data } = await apiClient.post<Investor>("/v1/investors", payload);
  return data;
}

export async function updateInvestor(
  investorId: string,
  payload: InvestorPayload,
): Promise<Investor> {
  const { data } = await apiClient.patch<Investor>(`/v1/investors/${investorId}`, payload);
  return data;
}

export async function archiveInvestor(investorId: string): Promise<Investor> {
  const { data } = await apiClient.post<Investor>(`/v1/investors/${investorId}:archive`);
  return data;
}

// ---- Holdings -------------------------------------------------------------

export async function listFarmHoldings(
  farmId: string,
  params: { block_id?: string; include_archived?: boolean } = {},
): Promise<Holding[]> {
  const { data } = await apiClient.get<Holding[]>(`/v1/farms/${farmId}/holdings`, { params });
  return data;
}

export async function getBlockHoldings(
  farmId: string,
  blockId: string,
): Promise<BlockHoldingsContext> {
  const { data } = await apiClient.get<BlockHoldingsContext>(
    `/v1/farms/${farmId}/blocks/${blockId}/holdings`,
  );
  return data;
}

export async function createHolding(
  farmId: string,
  blockId: string,
  payload: HoldingCreatePayload,
): Promise<Holding> {
  const { data } = await apiClient.post<Holding>(
    `/v1/farms/${farmId}/blocks/${blockId}/holdings`,
    payload,
  );
  return data;
}

export async function getHolding(farmId: string, holdingId: string): Promise<HoldingDetail> {
  const { data } = await apiClient.get<HoldingDetail>(`/v1/farms/${farmId}/holdings/${holdingId}`);
  return data;
}

export async function updateHolding(
  farmId: string,
  holdingId: string,
  payload: HoldingUpdatePayload,
): Promise<Holding> {
  const { data } = await apiClient.patch<Holding>(
    `/v1/farms/${farmId}/holdings/${holdingId}`,
    payload,
  );
  return data;
}

export async function archiveHolding(farmId: string, holdingId: string): Promise<Holding> {
  const { data } = await apiClient.post<Holding>(
    `/v1/farms/${farmId}/holdings/${holdingId}:archive`,
  );
  return data;
}

// ---- Ownership ------------------------------------------------------------

export async function assignOwner(
  farmId: string,
  holdingId: string,
  payload: OwnershipCreatePayload,
): Promise<HoldingDetail> {
  const { data } = await apiClient.post<HoldingDetail>(
    `/v1/farms/${farmId}/holdings/${holdingId}/ownerships`,
    payload,
  );
  return data;
}

export async function endOwnership(
  farmId: string,
  ownershipId: string,
  payload: { end_date: string; ended_by: EndedBy },
): Promise<HoldingDetail> {
  const { data } = await apiClient.post<HoldingDetail>(
    `/v1/farms/${farmId}/ownerships/${ownershipId}:end`,
    payload,
  );
  return data;
}

export async function deleteOwnership(farmId: string, ownershipId: string): Promise<void> {
  await apiClient.delete(`/v1/farms/${farmId}/ownerships/${ownershipId}`);
}

// ---- App login ------------------------------------------------------------

export interface InvestorLoginResult {
  investor: Investor;
  /** False when the set-password email could not be sent. */
  email_sent: boolean;
  temporary_password: string | null;
  provisioning: string | null;
}

export async function createInvestorLogin(investorId: string): Promise<InvestorLoginResult> {
  const { data } = await apiClient.post<InvestorLoginResult>(
    `/v1/investors/${investorId}:create-login`,
  );
  return data;
}

export async function resendInvestorLogin(investorId: string): Promise<InvestorLoginResult> {
  const { data } = await apiClient.post<InvestorLoginResult>(
    `/v1/investors/${investorId}:resend-login`,
  );
  return data;
}

export async function setInvestorLoginEnabled(
  investorId: string,
  enabled: boolean,
): Promise<Investor> {
  const action = enabled ? "enable-login" : "disable-login";
  const { data } = await apiClient.post<Investor>(`/v1/investors/${investorId}:${action}`);
  return data;
}

// ---- Investments overview and farm map ------------------------------------

export interface OverviewFarmRow {
  farm_id: string;
  farm_name: string;
  farm_name_ar: string | null;
  holdings: number;
  sold: number;
  for_sale: number;
  draft: number;
  area_sold_m2: string;
  block_area_m2: string;
  area_not_sold_m2: string;
}

export interface OverviewRecentRow {
  id: string;
  start_date: string;
  acquired_by: AcquiredBy;
  created_at: string;
  holding_id: string;
  holding_code: string;
  farm_id: string;
  investor_id: string;
  investor_code: string;
  investor_name: string;
  investor_name_ar: string | null;
  previous_investor_code: string | null;
  previous_ended_by: EndedBy | null;
}

export interface InvestmentsOverview {
  farm: OverviewFarmRow;
  /** Distinct investors who own a holding on this farm today. */
  investors: number;
  recent: OverviewRecentRow[];
  all_farms: {
    farms: number;
    sold: number;
    area_sold_m2: string;
    area_not_sold_m2: string;
  };
}

export async function getInvestmentsOverview(farmId: string): Promise<InvestmentsOverview> {
  const { data } = await apiClient.get<InvestmentsOverview>(
    `/v1/farms/${farmId}/investments/overview`,
  );
  return data;
}

export interface FarmMapBlock {
  id: string;
  code: string;
  name: string | null;
  name_ar: string | null;
  boundary: Polygon;
  area_m2: string;
  eligible: boolean;
}

export interface FarmHoldingsMap {
  farm_id: string;
  blocks: FarmMapBlock[];
  holdings: Holding[];
}

export async function getFarmHoldingsMap(farmId: string): Promise<FarmHoldingsMap> {
  const { data } = await apiClient.get<FarmHoldingsMap>(`/v1/farms/${farmId}/holdings-map`);
  return data;
}

// ---- The signed-in investor -----------------------------------------------

export interface InvestorAppMe {
  code: string;
  full_name: string;
  full_name_ar: string | null;
  preferred_language: InvestorLanguage;
  company_name: string | null;
}

export interface InvestorAppHolding {
  holding_id: string;
  code: string;
  name: string;
  name_ar: string | null;
  farm_name: string | null;
  farm_name_ar: string | null;
  block_code: string | null;
  block_name: string | null;
  block_name_ar: string | null;
  area_m2: string;
  tree_count: number | null;
  crop_name_en: string | null;
  crop_name_ar: string | null;
  variety_name_en: string | null;
  variety_name_ar: string | null;
  planting_date: string | null;
  start_date: string;
  end_date: string | null;
  period: OwnershipPeriod;
  boundary: Polygon;
  block_boundary: Polygon;
}

export async function getInvestorMe(): Promise<InvestorAppMe> {
  const { data } = await apiClient.get<InvestorAppMe>("/v1/investor/me");
  return data;
}

export async function listMyHoldings(): Promise<InvestorAppHolding[]> {
  const { data } = await apiClient.get<InvestorAppHolding[]>("/v1/investor/holdings");
  return data;
}
