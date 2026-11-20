/** Types mirroring the backend API (backend/app/schemas/api.py). */

export type Option = { value: string; label: string };

export type Options = {
  symptoms: Option[];
  urgency: Option[];
  equipment_types: Option[];
  certifications: Option[];
  diagnostic_fee_cents: number;
  features: Features;
};

/** What the backend has switched on (each turns on when its keys are configured). */
export type Features = {
  google_client_id: string | null;
  payments: boolean;
  stripe_publishable_key: string | null;
  photo_analysis: boolean;
  /** 'twilio' = codes arrive by text; 'development' = codes are shown on screen. */
  texts: 'twilio' | 'development';
  scheduling_integrations: boolean;
  /** Emailed links (technician invites): sent by Firebase, or shown on screen in development. */
  email_links: 'firebase' | 'development';
};

export type Tokens = { access_token: string; refresh_token: string; expires_in: number };

export type Homeowner = {
  id: string;
  phone: string | null;
  email: string | null;
  name: string | null;
  address: string | null;
  lat: number | null;
  lng: number | null;
  sms_opt_in: boolean;
  payment_method_label: string | null;
};

export type RequestStatus =
  | 'draft'
  | 'analyzed'
  | 'proposed'
  | 'waitlisted'
  | 'offered'
  | 'dispatched'
  | 'en_route'
  | 'on_site'
  | 'quoted'
  | 'in_progress'
  | 'completed'
  | 'canceled';

export type UnitInfo = {
  brand: string | null;
  model_number: string | null;
  serial_number: string | null;
  equipment_type: string;
  approx_age_years: number | null;
  tonnage: number | null;
  manufacture_year?: number | null;
  refrigerant?: string | null;
  fuel?: string | null;
  seer_rating?: number | null;
  voltage?: string | null;
  photo_feedback?: string | null;
  edited_by_homeowner?: boolean;
};

export type Diagnosis = {
  primary_issue: string;
  primary_issue_label: string;
  summary: string;
  alternatives: { issue: string; label: string }[];
  confidence: 'low' | 'medium' | 'high';
  safety_warning: string | null;
  visible_issues?: string[];
  /** false when photo analysis is switched off (no Anthropic key yet). */
  ai_used?: boolean;
  /** ai | skipped (no photo or description) | off | failed | photo_unusable */
  analysis?: 'ai' | 'skipped' | 'off' | 'failed' | 'photo_unusable';
  /** Why photo analysis failed, when it did (the request still goes ahead). */
  ai_error?: string | null;
};

export type TechnicianSummary = {
  id: string;
  name: string;
  first_name: string;
  photo_url: string | null;
  rating: number | null;
  rating_count: number;
  certifications: string[];
  shop_name: string;
  shop_phone: string | null;
  distance_km: number | null;
  eta_minutes: number | null;
  /** When the tech is expected: soon, or a later opening (e.g. tomorrow 8:15 AM). */
  arrival_at: string | null;
  /** Live position: only while the technician is driving to THIS job. */
  location: { lat: number; lng: number } | null;
  location_updated_at: string | null;
  /** The technician's own number, only if their company lets them take customer calls. */
  phone: string | null;
  can_message: boolean;
  /** False while the company is still choosing which technician comes. */
  assigned: boolean;
};

export type Message = {
  id: string;
  sender: 'homeowner' | 'technician' | 'shop';
  sender_name: string | null;
  body: string;
  created_at: string;
};

// --- Technician app ---------------------------------------------------------------------------
export type TechMe = {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  shop_name: string;
  shop_phone: string | null;
  can_respond_offers: boolean;
  can_contact_customers: boolean;
  schedule_view: 'full' | 'next';
};

export type TechJob = {
  id: string;
  status: RequestStatus;
  arrival_at: string | null;
  offer_expires_at: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  address: string | null;
  area_label: string;
  distance_km: number | null;
  symptoms: string[];
  description: string | null;
  photos: { id: string; url: string }[];
  unit: ServiceRequest['unit'];
  diagnosis: ServiceRequest['diagnosis'];
  quote: { final_price_cents: number; notes: string | null } | null;
  approved: boolean;
  technician_flag: string | null;
  chat_open: boolean;
  can_contact: boolean;
  completed_at: string | null;
};

export type TechBoard = {
  offers: TechJob[];
  jobs: TechJob[];
  hidden_jobs: number;
  recent: TechJob[];
  outside_jobs: OutsideJob[];
};

/** A job from the company's own software (Housecall Pro). Read-only in our apps. */
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
  /** Progress from our app (Housecall Pro gets each step as a note). */
  app_status: '' | 'en_route' | 'on_site' | 'working' | 'finished';
  on_my_way_at: string | null;
  arrived_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  unsent: number;
};

export type OutsideStep = 'on_my_way' | 'arrived' | 'started' | 'finished';

export type OutsideJobDetail = OutsideJob & {
  activity: { id: string; kind: string; text: string; created_at: string; sent: boolean; error: string | null }[];
  line_items: { name: string; quantity: number; unit_price_cents: number; total_cents: number }[] | null;
};

export type InviteInfo = {
  shop_name: string;
  technician_name: string;
  email: string;
  email_verified: boolean;
  can_respond_offers: boolean;
  can_contact_customers: boolean;
  schedule_view: 'full' | 'next';
};

export type ServiceRequest = {
  id: string;
  status: RequestStatus;
  created_at: string;
  symptoms: string[];
  description: string | null;
  urgency: string;
  address: string | null;
  lat: number;
  lng: number;
  photos: { id: string; url: string }[];
  unit: UnitInfo | null;
  diagnosis: Diagnosis | null;
  estimate: Estimate;
  require_all_skills: boolean;
  technician: TechnicianSummary | null;
  proposal_expires_at: string | null;
  offer_expires_at: string | null;
  waitlist: {
    position: number | null;
    eta_minutes: number | null;
    since: string | null;
    /** Why nobody could be matched yet, in plain language. */
    reason: string | null;
  } | null;
  quote: { final_price_cents: number; notes: string | null } | null;
  payment: { authorized_cents: number | null; captured_cents: number | null };
  rating: number | null;
  shop_rating: number | null;
  preferred_shop_id: string | null;
  preferred_technician_id: string | null;
  canceled_reason: string | null;
  /** Messages with the shop / technician are open (from acceptance until 48 h after the job). */
  chat_open: boolean;
  completed_at: string | null;
};

export type CardSetup = {
  publishable_key: string;
  customer_id: string;
  setup_intent_id: string;
  client_secret: string;
  ephemeral_key_secret: string | null;
};

export type OtpStarted = { phone: string; resend_after_seconds: number; dev_code: string | null };

export type ProviderShop = {
  id: string;
  name: string;
  your_company?: boolean; // the homeowner is already this company's customer
  rating: number | null;
  rating_count: number;
  technician_count: number;
  distance_km: number;
  arrival_at: string;
};

export type ProviderTech = {
  id: string;
  name: string;
  photo_url: string | null;
  shop_id: string;
  shop_name: string;
  rating: number | null;
  rating_count: number;
  certifications: string[];
  distance_km: number;
  arrival_at: string;
};

export type Providers = { shops: ProviderShop[]; technicians: ProviderTech[] };

type ShopCard = {
  id: string;
  name: string;
  phone: string | null;
  area: string | null;
  rating: number | null;
  rating_count: number;
  taking_requests: boolean;
};

export type PublicProvider =
  | ({ kind: 'shop' } & ShopCard)
  | {
      kind: 'technician';
      id: string;
      name: string;
      photo_url: string | null;
      rating: number | null;
      rating_count: number;
      certifications: string[];
      equipment_types: string[];
      shop: ShopCard;
    };

export type ShareTarget = { title: string; url: string; message: string; phone?: string | null };
export type ShareInfo = { technician: ShareTarget; shop: ShareTarget };

/** Visit + repair. high_cents null: the repair is priced on site. */
export type Estimate = {
  diagnostic_fee_cents: number | null;
  low_cents: number | null;
  high_cents?: number | null;
  basis?: string | null;
  source?: 'ai' | 'past_jobs' | 'price_book' | 'visit_only' | null;
};

export type UnreadChat = {
  request_id: string;
  count: number;
  sender_name: string | null;
  preview: string;
  last_at: string;
};

export type Complaint = {
  id: string;
  category: string;
  category_label: string;
  details: string;
  status: 'open' | 'resolved';
  shop_response: string | null;
  created_at: string;
};

export type ComplaintState = {
  can_file: boolean;
  categories: Record<string, string>;
  complaint: Complaint | null;
};

/** A visit the homeowner's company booked in Housecall Pro. */
export type HomeVisit = {
  id: string;
  shop_name: string;
  shop_phone: string | null;
  technician_first_name: string | null;
  starts_at: string | null;
  ends_at: string | null;
  description: string | null;
  status: 'scheduled' | 'en_route' | 'on_site' | 'working' | 'finished';
};
