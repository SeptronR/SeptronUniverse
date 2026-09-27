import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type {
  Consent,
  DataSubjectRequest,
  Entitlements,
  FeatureDefinition,
  FeatureMatrix,
  InstitutionFeatureFlag,
  InstitutionFeatures,
  LoginHistoryRow,
  LoginRequest,
  LoginResponse,
  MfaConfirmResponse,
  MfaSetup,
  PermissionCatalogue,
  PrincipalPayload,
  Role,
  RolePermissionMatrix,
  SessionRow,
  UserCreatePayload,
  UserCreated,
  UserDetail,
  UserListParams,
  UserRoleAssignment,
  UserRow,
} from './types';

// The axios response interceptor unwraps to the envelope, so the resolved value is `Envelope<T>`.
const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const post = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.put(url, body, config) as unknown as Promise<Envelope<T>>;
const del = <T>(url: string, config?: AxiosRequestConfig) =>
  api.delete(url, config) as unknown as Promise<Envelope<T>>;

/** Auth, RBAC, feature-flag, privacy and entitlement API (Prompts/02 §02.8) — the only caller of these routes. */
export const authApi = {
  // ---- session ------------------------------------------------------------------------------------------------
  login: (body: LoginRequest) => post<LoginResponse>('/auth/login', { platform: 'web', ...body }, { idempotent: false }),
  sendOtp: (body: { phone?: string; email?: string; institution_slug?: string; captcha_token?: string }) =>
    post<{ sent: boolean; ttl_seconds: number; resend_after: number }>('/auth/send-otp', body, { idempotent: false }),
  verifyOtp: (body: { phone?: string; email?: string; code: string; institution_slug?: string }) =>
    post<LoginResponse>('/auth/verify-otp', { platform: 'web', ...body }, { idempotent: false }),
  me: () => get<PrincipalPayload>('/auth/me'),
  logout: (all = false) => post<{ detail: string }>('/auth/logout', undefined, { params: { all }, idempotent: false }),
  ssoStart: (provider: string, institution_slug?: string, login_hint?: string) =>
    get<{ provider: string; authorize_url: string; state: string }>(`/auth/sso/${provider}/start`, {
      params: { institution_slug, login_hint },
    }),

  // ---- passwords / MFA ----------------------------------------------------------------------------------------
  forgotPassword: (body: { identifier: string; institution_slug?: string; captcha_token?: string }) =>
    post<{ detail: string }>('/auth/forgot-password', body, { idempotent: false }),
  resetPassword: (body: { token: string; password: string }) =>
    post<{ detail: string }>('/auth/reset-password', body, { idempotent: false }),
  changePassword: (body: { current_password: string; new_password: string }) =>
    post<{ detail: string }>('/auth/change-password', body, { idempotent: false }),
  mfaSetup: () => post<MfaSetup>('/auth/mfa/setup', undefined, { idempotent: false }),
  mfaConfirm: (code: string) => post<MfaConfirmResponse>('/auth/mfa/confirm', { code }, { idempotent: false }),
  mfaDisable: (body: { password: string; code: string }) =>
    post<{ detail: string }>('/auth/mfa/disable', body, { idempotent: false }),
  regenerateRecoveryCodes: () =>
    post<{ recovery_codes: string[] }>('/auth/mfa/recovery-codes/regenerate', undefined, { idempotent: false }),

  // ---- sessions -----------------------------------------------------------------------------------------------
  sessions: () => get<SessionRow[]>('/auth/sessions'),
  revokeSession: (id: string) => del<{ detail: string }>(`/auth/sessions/${id}`),
  revokeOtherSessions: () => del<{ detail: string }>('/auth/sessions'),
  loginHistory: () => get<LoginHistoryRow[]>('/auth/login-history'),

  // ---- RBAC ---------------------------------------------------------------------------------------------------
  permissions: () => get<PermissionCatalogue>('/permissions'),
  listRoles: (params: { page?: number; page_size?: number; q?: string } = {}) => get<Role[]>('/roles', { params }),
  getRole: (id: string) => get<Role>(`/roles/${id}`),
  createRole: (body: { name: string; slug: string; description?: string; default_scope_type?: string }) =>
    post<Role>('/roles', body),
  updateRole: (id: string, body: Record<string, unknown>) => put<Role>(`/roles/${id}`, body),
  deleteRole: (id: string) => del<null>(`/roles/${id}`),
  cloneRole: (id: string, body: { name: string; slug: string }) => post<Role>(`/roles/${id}/clone`, body),
  getMatrix: (id: string) => get<RolePermissionMatrix>(`/roles/${id}/permissions`),
  setMatrix: (id: string, body: RolePermissionMatrix & { version?: number }) =>
    put<RolePermissionMatrix>(`/roles/${id}/permissions`, body),

  // ---- users --------------------------------------------------------------------------------------------------
  listUsers: (params: UserListParams = {}) => get<UserRow[]>('/users', { params }),
  getUser: (id: string) => get<UserDetail>(`/users/${id}`),
  createUser: (body: UserCreatePayload) => post<UserCreated>('/users', body),
  updateUser: (id: string, body: Record<string, unknown>) => put<UserDetail>(`/users/${id}`, body),
  deactivateUser: (id: string) => post<UserDetail>(`/users/${id}/deactivate`, undefined, { idempotent: false }),
  reactivateUser: (id: string) => post<UserDetail>(`/users/${id}/reactivate`, undefined, { idempotent: false }),
  resetUserPassword: (id: string) =>
    post<{ user_id: string; temporary_password: string }>(`/users/${id}/reset-password`, undefined, {
      idempotent: false,
    }),
  userRoles: (id: string) => get<UserRoleAssignment[]>(`/users/${id}/roles`),
  assignRole: (id: string, body: { role_id: string; scope_type?: string; scope_id?: string | null }) =>
    post<UserRoleAssignment>(`/users/${id}/roles`, body),
  revokeRole: (id: string, assignmentId: string) => del<null>(`/users/${id}/roles/${assignmentId}`),
  credentialSheets: (body: { audience: string; ids: string[]; batch_label?: string }) =>
    post<{ job_id: string; sheet_id: string; audience: string; count: number }>('/users/credential-sheets', body),
  impersonate: (id: string, reason: string) =>
    post<{ access_token: string; user: UserDetail; impersonation_log_id: string; read_only: boolean }>(
      `/users/${id}/impersonate`,
      { reason },
      { idempotent: false },
    ),
  stopImpersonation: () => post<{ detail: string }>('/auth/impersonation/stop', undefined, { idempotent: false }),

  // ---- features -----------------------------------------------------------------------------------------------
  featureDefinitions: () => get<FeatureDefinition[]>('/features'),
  institutionFeatures: (institutionId: string) =>
    get<InstitutionFeatures>(`/institutions/${institutionId}/features`, {
      headers: { 'X-Institution-Id': institutionId },
    }),
  setPlatformFlag: (
    institutionId: string,
    key: string,
    body: { enabled: boolean; reason?: string; config?: Record<string, unknown>; confirm_dependencies?: boolean },
  ) =>
    put<InstitutionFeatureFlag>(`/institutions/${institutionId}/features/${key}`, body, {
      headers: { 'X-Institution-Id': institutionId },
    }),
  applyPlanDefaults: (institutionId: string) =>
    post<{ applied: number; plan_code: string | null }>(
      `/institutions/${institutionId}/features/apply-plan-defaults`,
      undefined,
      { headers: { 'X-Institution-Id': institutionId }, idempotent: false },
    ),
  institutionToggle: (key: string, body: { enabled: boolean; reason?: string }) =>
    put<InstitutionFeatureFlag>(`/features/${key}/institution-toggle`, body),
  featureMatrix: () => get<FeatureMatrix>('/platform/features/matrix'),

  // ---- privacy / entitlements -----------------------------------------------------------------------------------
  myConsents: () => get<Consent[]>('/consents/me'),
  recordConsent: (body: { purpose: string; granted: boolean; text_version?: string }) =>
    post<Consent>('/consents', body),
  myDsrs: () => get<DataSubjectRequest[]>('/data-subject-requests/me'),
  createDsr: (body: { request_type: string; details?: string }) =>
    post<DataSubjectRequest>('/data-subject-requests', body),
  entitlements: () => get<Entitlements>('/entitlements'),
};
