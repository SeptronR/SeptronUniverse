/** Auth / RBAC / features / privacy types — mirrors backend/app/schemas/{auth,rbac,features,privacy,saas}.py. */
import type { PaginationMeta, ScopeName } from '@/utils/types';

export interface InstitutionSummary {
  id: string;
  name: string;
  slug: string;
  type: string;
  logo_url?: string | null;
  timezone: string;
  locale: string;
  currency: string;
}

export interface Scope {
  scope_type: string;
  scope_id: string | null;
  label?: string | null;
}

export interface MeUser {
  id: string;
  institution_id: string | null;
  username: string;
  email?: string | null;
  phone?: string | null;
  display_name: string | null;
  avatar_url?: string | null;
  user_type: string;
  is_super_admin: boolean;
  role_slugs: string[];
  scopes: Scope[];
  mfa_enabled: boolean;
  must_change_password: boolean;
  locale?: string | null;
  timezone?: string | null;
  valid_to?: string | null;
  impersonator_id?: string | null;
  impersonation_read_only?: boolean;
}

export interface VisibilityDefault {
  self: boolean;
  scopes: ScopeName[];
  default: ScopeName;
}

export interface PrincipalPayload {
  user: MeUser;
  institution: InstitutionSummary | null;
  permissions: string[];
  features: string[];
  scopes: Scope[];
  visibility_defaults: Record<string, VisibilityDefault>;
  session_id: string | null;
}

export interface LoginResponse extends PrincipalPayload {
  access_token: string;
  refresh_token?: string | null;
  mfa_required?: boolean;
  mfa_setup_required?: boolean;
}

export interface LoginRequest {
  identifier: string;
  password: string;
  mfa_code?: string;
  institution_slug?: string;
  platform?: 'web' | 'pwa' | 'android' | 'ios' | 'script';
  device_label?: string;
}

export interface MfaSetup {
  secret: string;
  otpauth_url: string;
  qr_png_base64: string;
}

export interface MfaConfirmResponse {
  recovery_codes: string[];
  access_token?: string | null;
}

export interface SessionRow {
  id: string;
  device_label: string | null;
  platform: string | null;
  ip_masked: string | null;
  user_agent: string | null;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  current: boolean;
}

export interface LoginHistoryRow {
  id: string;
  outcome: string;
  ip: string | null;
  user_agent: string | null;
  occurred_at: string;
}

// ---- RBAC ----------------------------------------------------------------------------------------------------
export interface Permission {
  id: string;
  module: string;
  action: string;
  description?: string | null;
  is_platform: boolean;
}

export interface PermissionCatalogue {
  modules: string[];
  standard_actions: string[];
  permissions: Permission[];
}

export interface Role {
  id: string;
  institution_id: string | null;
  name: string;
  slug: string;
  description?: string | null;
  is_system: boolean;
  default_scope_type: string;
  portal?: string | null;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  permission_count?: number | null;
  assignment_count?: number | null;
}

export interface MatrixModule {
  module: string;
  actions: { action: string; granted: boolean }[];
}

export interface RolePermissionMatrix {
  role_id?: string | null;
  modules: MatrixModule[];
}

export interface UserRoleAssignment {
  id: string;
  role_id: string;
  role_slug: string;
  role_name: string;
  scope_type: string;
  scope_id: string | null;
  scope_label?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  assigned_at: string;
}

export interface UserRow {
  id: string;
  institution_id: string | null;
  username: string;
  email?: string | null;
  phone?: string | null;
  display_name: string | null;
  avatar_url?: string | null;
  user_type: string;
  is_super_admin: boolean;
  is_active: boolean;
  is_verified: boolean;
  must_change_password: boolean;
  mfa_enabled: boolean;
  last_login_at?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  role_slugs: string[];
}

export interface UserDetail extends UserRow {
  roles: UserRoleAssignment[];
}

export interface UserCreated extends UserDetail {
  temporary_password?: string | null;
}

export interface UserListParams {
  page?: number;
  page_size?: number;
  sort?: string;
  scope?: string;
  q?: string;
  user_type?: string;
  is_active?: boolean;
  role?: string;
  [key: string]: string | number | boolean | undefined;
}

export interface UserCreatePayload {
  username: string;
  email?: string;
  phone?: string;
  display_name?: string;
  user_type?: string;
  password?: string;
  must_change_password?: boolean;
  valid_from?: string | null;
  valid_to?: string | null;
  roles?: { role_id: string; scope_type?: string; scope_id?: string | null }[];
}

// ---- features -------------------------------------------------------------------------------------------------
export interface FeatureDefinition {
  key: string;
  group: string;
  name: string;
  description?: string | null;
  default_enabled: boolean;
  min_plan_tier: string;
  depends_on: string[];
  is_core: boolean;
  registered: boolean;
}

export interface InstitutionFeatureFlag extends Omit<FeatureDefinition, 'default_enabled' | 'registered'> {
  platform_enabled: boolean;
  institution_enabled: boolean;
  effective: boolean;
  source: string;
  config?: Record<string, unknown> | null;
  plan_allows: boolean;
  set_at?: string | null;
}

export interface FeatureFlagChange {
  id: string;
  feature_key: string;
  old_value?: Record<string, unknown> | null;
  new_value?: Record<string, unknown> | null;
  changed_by?: string | null;
  changed_at: string;
  reason?: string | null;
}

export interface InstitutionFeatures {
  institution_id: string;
  plan_code: string | null;
  flags: InstitutionFeatureFlag[];
  changes: FeatureFlagChange[];
}

export interface FeatureMatrix {
  features: FeatureDefinition[];
  institutions: { id: string; name: string; slug: string; plan_code: string | null; effective: string[] }[];
}

// ---- privacy / entitlements ------------------------------------------------------------------------------------
export interface Consent {
  id: string;
  purpose: string;
  granted: boolean;
  text_version?: string | null;
  recorded_at: string;
  withdrawn_at?: string | null;
}

export interface DataSubjectRequest {
  id: string;
  request_type: string;
  status: string;
  details?: string | null;
  due_at?: string | null;
  result_url?: string | null;
  created_at: string;
  closed_at?: string | null;
}

export interface Entitlements {
  institution_id: string;
  plan: string | null;
  plan_name: string | null;
  tier: string | null;
  status: string;
  starts_on?: string | null;
  ends_on?: string | null;
  grace_until?: string | null;
  limits: { students: number | null; staff: number | null; storage_gb: number | null; sms_credits: number | null };
  usage: { students: number; staff: number; storage_bytes: number; sms_sent: number; period_month?: string | null };
  writable: boolean;
}

export type { PaginationMeta };
