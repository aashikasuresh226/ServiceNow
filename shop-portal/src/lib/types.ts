/** Mirrors backend/app/schemas/api.py (shop side). */

export type Option = { value: string; label: string };

export type Options = {
  symptoms: Option[];
  equipment_types: Option[];
  certifications: Option[];
  features: Features;
};

/** What the backend has switched on (each turns on when its keys are configured). */
export type Features = {
  google_client_id: string | null;
  payments: boolean;
  stripe_publishable_key: string | null;
  photo_analysis: boolean;
  texts: 'twilio' | 'development';
  scheduling_integrations: boolean;
  /** Who emails sign-up links and technician invites. */
  email_links: 'firebase' | 'development';
  firebase: FirebaseConfig | null;
};

export type FirebaseConfig = { apiKey: string; authDomain: string; projectId: string; appId?: string };

/** Send `continue_url` to `email` with Firebase, or (development) open `dev_link`. */
export type EmailLink = {
  email: string;
  continue_url: string;
  delivery: 'firebase' | 'development';
  dev_link: string | null;
};

export type Tokens = { access_token: string; refresh_token: string; expires_in: number };

export type LoginStep = {
  step: 'verify_email' | 'mfa' | 'mfa_setup';
  token: string;
  email_link: EmailLink | null;
};

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
  rating: number | null;
  rating_count: number;
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
  service_radius_km: number;
  working_hours: WorkingHours;
  is_active: boolean;
  rating: number | null;
  rating_count: number;
  email: string | null;
  /** Technician app: none (office runs their jobs) | invited | active | disabled */
  app_status: 'none' | 'invited' | 'active' | 'disabled';
  invited_at: string | null;
  joined_at: string | null;
  can_respond_offers: boolean;
  can_contact_customers: boolean;
  schedule_view: 'full' | 'next';
};

export type TechPermissions = Pick<Technician, 'can_respond_offers' | 'can_contact_customers' | 'schedule_view'>;

export type Message = {
  id: string;
  sender: 'homeowner' | 'technician' | 'shop';
  sender_name: string | null;
  body: string;
  created_at: string;
};

export type Block = {
  kind: 'shift' | 'busy';
  starts_at: string;
  ends_at: string;
  label: string | null;
  /** job = booked through the app; manual = marked busy here; hours = working hours */
  source: string | null;
};

export type CalendarLink = { url: string; webcal_url: string; google_url: string };

export type TechDay = {
  technician: Technician;
  blocks: Block[];
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

export type Readiness = {
  ready: boolean;
  checks: { ok: boolean; label: string; detail: string }[];
  technicians: { id: string; name: string; next_opening: string | null; next_opening_label: string; problems: string[] }[];
};

export type Job = {
  id: string;
  status: JobStatus;
  created_at: string;
  arrival_at: string | null;
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
    serial_number?: string | null;
    equipment_type: string;
    approx_age_years: number | null;
    manufacture_year?: number | null;
    tonnage?: number | null;
    refrigerant?: string | null;
    fuel?: string | null;
    seer_rating?: number | null;
  } | null;
  diagnosis: {
    primary_issue_label: string;
    summary: string;
    confidence: string;
    visible_issues?: string[];
    ai_used?: boolean;
  } | null;
  estimate: { diagnostic_fee_cents: number | null; low_cents: number | null };
  technician_id: string | null;
  technician_name: string | null;
  offer_expires_at: string | null;
  quote: { final_price_cents: number; notes: string | null } | null;
  payment: { authorized_cents: number | null; captured_cents: number | null };
  payout_cents: number | null;
  /** The homeowner chose your company or technician (e.g. from a shared link). */
  picked_by_customer: boolean;
  technician_rating: number | null;
  shop_rating: number | null;
  review: string | null;
  /** The technician said they can't make it: reassign or call the customer. */
  technician_flag: string | null;
  chat_open: boolean;
  /** The technician is on the way and sharing their location with the customer. */
  driving: boolean;
};
