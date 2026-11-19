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
  location: { lat: number; lng: number } | null;
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
  estimate: { diagnostic_fee_cents: number | null; low_cents: number | null };
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
