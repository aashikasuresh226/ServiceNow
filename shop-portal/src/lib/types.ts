/** Mirrors backend/app/schemas/api.py (shop side). */

export type Option = { value: string; label: string };

export type Options = {
  symptoms: Option[];
  issues: Option[]; // what the technician actually found
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
  technician_sign_in_url: string;
  app_url: string;
};

/** Firebase emailed the link (delivery=firebase), or in development open `dev_link`. */
export type EmailLink = {
  email: string;
  continue_url: string;
  delivery: 'firebase' | 'development';
  dev_link: string | null;
};

export type Tokens = { access_token: string; refresh_token: string; expires_in: number };

export type LoginStep = {
  step: 'verify_email' | 'mfa' | 'mfa_email' | 'mfa_setup';
  token: string;
  email_link: EmailLink | null;
};

export type Shop = {
  id: string;
  name: string;
  logo_url: string | null;
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
  /** platform: we pick the tech · office: you pick when accepting · software: Housecall Pro's dispatcher */
  dispatch_mode: DispatchMode;
  instant_book: boolean;
  instant_book_daily_limit: number;
  /** Paste into Housecall Pro's webhook settings (optional; we also check every minute). */
  scheduling_webhook_url: string | null;
};

export type DispatchMode = 'platform' | 'office' | 'software';

export type TechOption = {
  technician_id: string;
  name: string;
  arrival_at: string | null;
  distance_km: number | null;
  available: boolean;
  reason: string | null;
  suggested: boolean;
};

export type TimeOff = { id: string; starts_at: string; ends_at: string; label: string | null };

export type ShopMe = { user_email: string; user_name: string | null; has_password: boolean; shop: Shop };

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
  estimate: {
    diagnostic_fee_cents: number | null;
    low_cents: number | null;
    high_cents?: number | null;
    basis?: string | null;
    source?: string | null;
  };
  technician_id: string | null;
  technician_name: string | null;
  offer_expires_at: string | null;
  quote: { final_price_cents: number; notes: string | null } | null;
  payment: { authorized_cents: number | null; captured_cents: number | null };
  payout_cents: number | null;
  /** The homeowner chose your company or technician (e.g. from a shared link). */
  picked_by_customer: boolean;
  customer_availability?: { start: string; end: string }[] | null; // when they're home (null: any time)
  /** The technician said they can't make it: reassign or call the customer. */
  technician_flag: string | null;
  chat_open: boolean;
  /** The technician is on the way and sharing their location with the customer. */
  driving: boolean;
  /** False until your office / Housecall Pro dispatcher picks who goes. */
  technician_confirmed: boolean;
  instant_booked: boolean;
  /** Offered to several shops at once: the first to accept gets it. */
  offered_to_several: boolean;
  external_job_id: string | null;
  external_error: string | null;
};

/** A job from the shop's Housecall Pro, copied every minute (read-only here). */
export type OutsideJob = {
  id: string;
  provider: string;
  invoice_number: string | null;
  work_status: string;
  description: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  address: string | null;
  starts_at: string | null;
  ends_at: string | null;
  technician_id: string | null;
  technician_name: string | null;
  customer_uses_app: boolean;
  app_status: '' | 'en_route' | 'on_site' | 'working' | 'finished';
  on_my_way_at: string | null;
  arrived_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  unsent: number;
};

export type Customer = {
  id: string;
  provider: 'housecall_pro' | 'app';
  name: string | null;
  phone: string | null;
  email: string | null;
  address: string | null;
  status: 'joined' | 'invited' | 'not_invited';
  invited_at: string | null;
  joined_at: string | null;
  last_job_at: string | null;
  invite_url: string;
  invite_message: string;
};

export type CustomerList = {
  customers: Customer[];
  total: number;
  joined: number;
  invited: number;
  imported_at: string | null;
  shop_invite_url: string;
  shop_invite_message: string;
};

export type ShopComplaint = {
  id: string;
  category: string;
  category_label: string;
  details: string;
  status: 'open' | 'resolved';
  shop_response: string | null;
  created_at: string;
  request_id: string;
  technician_id: string | null;
  technician_name: string | null;
  customer_name: string | null;
  job_date: string;
  issue: string | null;
  shop_responded_at: string | null;
  resolved_at: string | null;
  resolved_by: 'shop' | 'admin' | null;
};

export type AdminComplaint = ShopComplaint & { shop_id: string; shop_name: string; admin_note: string | null };

export type AdminReview = {
  request_id: string;
  completed_at: string | null;
  shop_name: string | null;
  technician_name: string | null;
  technician_rating: number | null;
  shop_rating: number | null;
  review: string | null;
};

export type HcpActivity = {
  connected: boolean;
  last_read_at: string | null;
  last_error: string | null;
  waiting: number;
  log: { created_at: string; action: string; ok: boolean; detail: string | null }[];
};
