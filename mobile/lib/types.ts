/** Types mirroring the backend API (backend/app/schemas/api.py). */

export type Option = { value: string; label: string };

export type Options = {
  symptoms: Option[];
  urgency: Option[];
  equipment_types: Option[];
  certifications: Option[];
  soft_skills: Option[];
  diagnostic_fee_cents: number;
  demo_mode: boolean;
};

export type Tokens = { access_token: string; refresh_token: string; expires_in: number };

export type Homeowner = {
  id: string;
  phone: string;
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
  edited_by_homeowner?: boolean;
};

export type Diagnosis = {
  primary_issue: string;
  primary_issue_label: string;
  summary: string;
  alternatives: { issue: string; label: string }[];
  confidence: 'low' | 'medium' | 'high';
  safety_warning: string | null;
};

export type TechnicianSummary = {
  id: string;
  name: string;
  first_name: string;
  photo_url: string | null;
  rating: number | null;
  rating_count: number;
  certifications: string[];
  soft_skills_matched: string[];
  shop_name: string;
  shop_phone: string | null;
  distance_km: number | null;
  eta_minutes: number | null;
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
  soft_skills: string[];
  require_all_skills: boolean;
  technician: TechnicianSummary | null;
  proposal_expires_at: string | null;
  offer_expires_at: string | null;
  waitlist: { position: number | null; eta_minutes: number | null; since: string | null } | null;
  quote: { final_price_cents: number; notes: string | null } | null;
  payment: { authorized_cents: number | null; captured_cents: number | null };
  rating: number | null;
  canceled_reason: string | null;
  completed_at: string | null;
};

export type CardSetup = {
  provider: 'stripe' | 'demo';
  publishable_key: string | null;
  customer_id: string;
  setup_intent_id: string;
  client_secret: string;
  ephemeral_key_secret: string | null;
};
