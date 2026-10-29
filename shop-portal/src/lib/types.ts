/** Mirrors backend/app/schemas/api.py (shop side). */

export type Option = { value: string; label: string };

export type Options = {
  symptoms: Option[];
  equipment_types: Option[];
  certifications: Option[];
  soft_skills: Option[];
  demo_mode: boolean;
};

export type Tokens = { access_token: string; refresh_token: string; expires_in: number };

export type LoginStep = { step: 'mfa' | 'mfa_setup'; token: string; dev_code: string | null };

export type Shop = {
  id: string;
  name: string;
  phone: string | null;
  address: string | null;
  lat: number | null;
  lng: number | null;
  timezone: string;
  is_live: boolean;
  payouts_enabled: boolean;
  payout_schedule: 'daily' | 'weekly' | 'manual';
  scheduling_provider: 'none' | 'servicetitan' | 'housecall_pro';
  scheduling_last_synced_at: string | null;
  scheduling_last_error: string | null;
  write_back_jobs: boolean;
};

export type ShopMe = { user_email: string; user_name: string | null; shop: Shop };

export type WorkingHours = Record<string, string[][]>;

export type Technician = {
  id: string;
  name: string;
  phone: string | null;
  photo_url: string | null;
  external_id: string | null;
  equipment_types: string[];
  certifications: string[];
  soft_skills: string[];
  service_radius_km: number;
  working_hours: WorkingHours;
  is_active: boolean;
  rating: number | null;
  rating_count: number;
};

export type TechDay = {
  technician: Technician;
  blocks: { kind: 'shift' | 'busy'; starts_at: string; ends_at: string }[];
  free_now: boolean;
  on_job: boolean;
};

export type Dashboard = {
  techs_free_now: number;
  techs_on_job: number;
  open_offers: number;
  active_jobs: number;
  waitlisted_nearby: number;
};

export type JobStatus =
  | 'offered'
  | 'dispatched'
  | 'en_route'
  | 'on_site'
  | 'quoted'
  | 'in_progress'
  | 'completed';

export type Job = {
  id: string;
  status: JobStatus;
  created_at: string;
  customer_first_name: string | null;
  customer_phone: string | null;
  address: string | null;
  area_label: string;
  distance_km: number | null;
  symptoms: string[];
  description: string | null;
  photos: { id: string; url: string }[];
  unit: {
    brand: string | null;
    model_number: string | null;
    equipment_type: string;
    approx_age_years: number | null;
  } | null;
  diagnosis: { primary_issue_label: string; summary: string; confidence: string } | null;
  estimate: { diagnostic_fee_cents: number | null; low_cents: number | null };
  soft_skills: string[];
  technician_id: string | null;
  technician_name: string | null;
  offer_expires_at: string | null;
  quote: { final_price_cents: number; notes: string | null } | null;
  payment: { authorized_cents: number | null; captured_cents: number | null };
  payout_cents: number | null;
};
