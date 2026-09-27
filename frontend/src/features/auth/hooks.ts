import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api } from '@/api/axios';
import { useAuthStore } from '@/store/authStore';
import { useSessionStore } from '@/store/sessionStore';
import { PORTAL_HOME, type RoleSlug } from '@/utils/constants';
import { authApi } from './api';
import type { LoginRequest, PrincipalPayload, UserListParams } from './types';

/** Query keys follow `[module, params]`; invalidate by `[module]` (frontend coding standard 1). */
export const authKeys = {
  me: ['auth', 'me'] as const,
  sessions: ['auth', 'sessions'] as const,
  history: ['auth', 'login-history'] as const,
  consents: ['auth', 'consents'] as const,
  dsrs: ['auth', 'dsrs'] as const,
};
export const roleKeys = {
  all: ['roles'] as const,
  list: (p: object) => ['roles', p] as const,
  matrix: (id: string) => ['roles', 'matrix', id] as const,
  permissions: ['roles', 'permissions'] as const,
};
export const userKeys = {
  all: ['users'] as const,
  list: (p: UserListParams) => ['users', p] as const,
  one: (id: string) => ['users', 'one', id] as const,
  roles: (id: string) => ['users', 'roles', id] as const,
};
export const featureKeys = {
  all: ['features'] as const,
  definitions: ['features', 'definitions'] as const,
  institution: (id: string) => ['features', 'institution', id] as const,
  matrix: ['features', 'matrix'] as const,
  entitlements: ['features', 'entitlements'] as const,
};

/** Writes the principal into the auth + session stores (login, OTP, SSO and the /auth/me bootstrap all funnel here). */
export const applyPrincipal = (payload: PrincipalPayload, accessToken?: string) => {
  const { user, institution, permissions, features } = payload;
  if (accessToken) useAuthStore.getState().setAccessToken(accessToken);
  useAuthStore.getState().setSession(
    {
      id: user.id,
      institution_id: user.institution_id,
      username: user.username,
      display_name: user.display_name,
      avatar_url: user.avatar_url,
      is_super_admin: user.is_super_admin,
      role_slugs: user.role_slugs,
      scopes: user.scopes.map((s) => ({ scope_type: s.scope_type, scope_id: s.scope_id })),
      must_change_password: user.must_change_password,
    },
    permissions,
    features,
    user.impersonator_id ?? null,
  );
  if (institution) useSessionStore.getState().setInstitution(institution.id, institution.name);
};

/** Home route after sign-in: portal-only roles land on their portal, everyone else on the dashboard. */
export const homeFor = (roleSlugs: string[], isSuperAdmin: boolean) => {
  if (isSuperAdmin) return '/platform';
  const portal = roleSlugs.map((s) => PORTAL_HOME[s as RoleSlug]).find(Boolean);
  const staffOnly = roleSlugs.some((s) => !PORTAL_HOME[s as RoleSlug]);
  return staffOnly || !portal ? '/dashboard' : portal;
};

export const useLogin = () =>
  useMutation({
    mutationFn: (body: LoginRequest) => authApi.login(body),
    onSuccess: (res) => applyPrincipal(res.data, res.data.access_token),
  });

export const useVerifyOtp = () =>
  useMutation({
    mutationFn: (body: { phone?: string; email?: string; code: string; institution_slug?: string }) =>
      authApi.verifyOtp(body),
    onSuccess: (res) => applyPrincipal(res.data, res.data.access_token),
  });

export const useSendOtp = () => useMutation({ mutationFn: authApi.sendOtp });

/** Refreshes the principal (permissions/features/scopes) for an already authenticated session. */
export const useMe = (enabled = true) =>
  useQuery({
    queryKey: authKeys.me,
    queryFn: async () => {
      const res = await authApi.me();
      applyPrincipal(res.data);
      return res;
    },
    enabled,
    staleTime: 60_000,
  });

export const useLogout = () => {
  const navigate = useNavigate();
  return useMutation({
    mutationFn: (all: boolean = false) => authApi.logout(all),
    onSettled: () => {
      useAuthStore.getState().logout();
      navigate('/login', { replace: true });
    },
  });
};

export const useForgotPassword = () => useMutation({ mutationFn: authApi.forgotPassword });
export const useResetPassword = () => useMutation({ mutationFn: authApi.resetPassword });
export const useChangePassword = () =>
  useMutation({
    mutationFn: authApi.changePassword,
    onSuccess: () => {
      const user = useAuthStore.getState().currentUser;
      if (user) useAuthStore.getState().setSession({ ...user, must_change_password: false }, useAuthStore.getState().permissions, useAuthStore.getState().features, useAuthStore.getState().impersonatorId);
    },
  });

// ---- MFA --------------------------------------------------------------------------------------------------------
export const useMfaSetup = () => useMutation({ mutationFn: authApi.mfaSetup });
export const useMfaConfirm = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => authApi.mfaConfirm(code),
    onSuccess: () => qc.invalidateQueries({ queryKey: authKeys.me }),
  });
};
export const useMfaDisable = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: authApi.mfaDisable,
    onSuccess: () => qc.invalidateQueries({ queryKey: authKeys.me }),
  });
};
export const useRecoveryCodes = () => useMutation({ mutationFn: authApi.regenerateRecoveryCodes });

// ---- sessions ---------------------------------------------------------------------------------------------------
export const useSessions = () => useQuery({ queryKey: authKeys.sessions, queryFn: authApi.sessions });
export const useRevokeSession = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => authApi.revokeSession(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: authKeys.sessions }),
  });
};
export const useRevokeOtherSessions = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => authApi.revokeOtherSessions(),
    onSuccess: () => qc.invalidateQueries({ queryKey: authKeys.sessions }),
  });
};
export const useLoginHistory = () => useQuery({ queryKey: authKeys.history, queryFn: authApi.loginHistory });

// ---- RBAC -------------------------------------------------------------------------------------------------------
export const usePermissionCatalogue = () =>
  useQuery({ queryKey: roleKeys.permissions, queryFn: authApi.permissions, staleTime: 10 * 60_000 });

export const useRoles = (params: { page?: number; page_size?: number; q?: string } = {}) =>
  useQuery({ queryKey: roleKeys.list(params), queryFn: () => authApi.listRoles(params), placeholderData: keepPreviousData });

export const useRoleMatrix = (id: string | undefined) =>
  useQuery({ queryKey: roleKeys.matrix(id ?? ''), queryFn: () => authApi.getMatrix(id!), enabled: !!id });

export const useSetRoleMatrix = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, modules }: { id: string; modules: { module: string; actions: { action: string; granted: boolean }[] }[] }) =>
      authApi.setMatrix(id, { modules }),
    onSuccess: (_res, vars) => {
      void qc.invalidateQueries({ queryKey: roleKeys.matrix(vars.id) });
      void qc.invalidateQueries({ queryKey: roleKeys.all });
    },
  });
};

export const useCloneRole = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name, slug }: { id: string; name: string; slug: string }) => authApi.cloneRole(id, { name, slug }),
    onSuccess: () => qc.invalidateQueries({ queryKey: roleKeys.all }),
  });
};

export const useCreateRole = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: authApi.createRole,
    onSuccess: () => qc.invalidateQueries({ queryKey: roleKeys.all }),
  });
};

export const useDeleteRole = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => authApi.deleteRole(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: roleKeys.all }),
  });
};

// ---- users ------------------------------------------------------------------------------------------------------
export const useUsers = (params: UserListParams) =>
  useQuery({ queryKey: userKeys.list(params), queryFn: () => authApi.listUsers(params), placeholderData: keepPreviousData });

export const useUser = (id: string | undefined) =>
  useQuery({ queryKey: userKeys.one(id ?? ''), queryFn: () => authApi.getUser(id!), enabled: !!id });

export const useCreateUser = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: authApi.createUser,
    onSuccess: () => qc.invalidateQueries({ queryKey: userKeys.all }),
  });
};

export const useUpdateUser = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Record<string, unknown>) => authApi.updateUser(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: userKeys.all }),
  });
};

export const useToggleUserActive = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      active ? authApi.reactivateUser(id) : authApi.deactivateUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: userKeys.all }),
  });
};

export const useResetUserPassword = () => useMutation({ mutationFn: (id: string) => authApi.resetUserPassword(id) });

export const useUserRoles = (id: string | undefined) =>
  useQuery({ queryKey: userKeys.roles(id ?? ''), queryFn: () => authApi.userRoles(id!), enabled: !!id });

export const useAssignRole = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; role_id: string; scope_type?: string; scope_id?: string | null }) =>
      authApi.assignRole(id, body),
    onSuccess: (_r, vars) => {
      void qc.invalidateQueries({ queryKey: userKeys.roles(vars.id) });
      void qc.invalidateQueries({ queryKey: userKeys.all });
    },
  });
};

export const useRevokeRole = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, assignmentId }: { id: string; assignmentId: string }) => authApi.revokeRole(id, assignmentId),
    onSuccess: (_r, vars) => {
      void qc.invalidateQueries({ queryKey: userKeys.roles(vars.id) });
      void qc.invalidateQueries({ queryKey: userKeys.all });
    },
  });
};

export const useCredentialSheets = () => useMutation({ mutationFn: authApi.credentialSheets });

export const useImpersonate = () => {
  const navigate = useNavigate();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => authApi.impersonate(id, reason),
    onSuccess: async (res) => {
      useAuthStore.getState().setAccessToken(res.data.access_token);
      const me = await authApi.me();
      applyPrincipal(me.data);
      navigate('/dashboard', { replace: true });
    },
  });
};

export const useStopImpersonation = () => {
  const navigate = useNavigate();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => authApi.stopImpersonation(),
    // the impersonation token is blacklisted server-side; the impersonator's own refresh cookie was never replaced,
    // so rotating it restores their real session instead of forcing a fresh sign-in
    onSettled: async () => {
      useAuthStore.getState().setAccessToken(null);
      qc.clear();
      const me = await restoreSession();
      navigate(me ? homeFor(me.user.role_slugs, me.user.is_super_admin) : '/login', { replace: true });
    },
  });
};

// ---- features / entitlements -------------------------------------------------------------------------------------
export const useFeatureDefinitions = () =>
  useQuery({ queryKey: featureKeys.definitions, queryFn: authApi.featureDefinitions, staleTime: 5 * 60_000 });

export const useInstitutionFeatures = (institutionId: string | undefined) =>
  useQuery({
    queryKey: featureKeys.institution(institutionId ?? ''),
    queryFn: () => authApi.institutionFeatures(institutionId!),
    enabled: !!institutionId,
  });

export const useSetPlatformFlag = (institutionId: string | undefined) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, ...body }: { key: string; enabled: boolean; reason?: string; confirm_dependencies?: boolean }) =>
      authApi.setPlatformFlag(institutionId!, key, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: featureKeys.institution(institutionId ?? '') }),
  });
};

export const useApplyPlanDefaults = (institutionId: string | undefined) => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => authApi.applyPlanDefaults(institutionId!),
    onSuccess: () => qc.invalidateQueries({ queryKey: featureKeys.institution(institutionId ?? '') }),
  });
};

export const useInstitutionToggle = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, enabled, reason }: { key: string; enabled: boolean; reason?: string }) =>
      authApi.institutionToggle(key, { enabled, reason }),
    onSuccess: async () => {
      void qc.invalidateQueries({ queryKey: featureKeys.all });
      const me = await authApi.me(); // effective features changed for this tenant
      applyPrincipal(me.data);
    },
  });
};

export const useFeatureMatrix = () => useQuery({ queryKey: featureKeys.matrix, queryFn: authApi.featureMatrix });

export const useEntitlements = () =>
  useQuery({ queryKey: featureKeys.entitlements, queryFn: authApi.entitlements, staleTime: 60_000 });

// ---- privacy ------------------------------------------------------------------------------------------------------
export const useMyConsents = () => useQuery({ queryKey: authKeys.consents, queryFn: authApi.myConsents });
export const useRecordConsent = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: authApi.recordConsent,
    onSuccess: () => qc.invalidateQueries({ queryKey: authKeys.consents }),
  });
};
export const useMyDsrs = () => useQuery({ queryKey: authKeys.dsrs, queryFn: authApi.myDsrs });
export const useCreateDsr = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: authApi.createDsr,
    onSuccess: () => qc.invalidateQueries({ queryKey: authKeys.dsrs }),
  });
};

/** The login page offers SSO when the tenant has the feature (public config exposes nothing tenant-private). */
export const useSsoStart = () =>
  useMutation({
    mutationFn: ({ provider, slug, hint }: { provider: string; slug?: string; hint?: string }) =>
      authApi.ssoStart(provider, slug, hint),
  });

export const refreshPrincipal = async () => {
  const res = await authApi.me();
  applyPrincipal(res.data);
  return res.data;
};

/**
 * Rotates the refresh cookie once and reloads the principal — **single-flight**: React StrictMode invokes effects
 * twice in development and two rotations of the same cookie would look like a replay to the API's reuse detection
 * (which revokes the whole family). Every caller shares one in-flight promise.
 */
let restoring: Promise<PrincipalPayload | null> | null = null;

export const restoreSession = (): Promise<PrincipalPayload | null> => {
  restoring ??= (async () => {
    try {
      const refreshed = (await api.post('/auth/refresh', undefined, { idempotent: false })) as unknown as {
        data: { access_token: string };
      };
      useAuthStore.getState().setAccessToken(refreshed.data.access_token);
      return await refreshPrincipal();
    } catch {
      useAuthStore.getState().logout(); // the cookie is gone or revoked: back to the login page
      return null;
    } finally {
      restoring = null;
    }
  })();
  return restoring;
};

export { api };
