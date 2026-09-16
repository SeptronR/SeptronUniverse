import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { queryClient } from '@/lib/queryClient';
import { useSessionStore } from '@/store/sessionStore';

/** Session principal as returned by /auth/me (Phase 02): roles, flat permissions, effective features, scopes. */
export interface CurrentUser {
  id: string;
  institution_id: string | null;
  username: string;
  display_name: string | null;
  avatar_url?: string | null;
  is_super_admin: boolean;
  role_slugs: string[];
  scopes: { scope_type: string; scope_id: string | null }[];
  must_change_password?: boolean;
}

interface AuthState {
  accessToken: string | null;
  currentUser: CurrentUser | null;
  permissions: string[];
  features: string[];
  isAuthenticated: boolean;
  impersonatorId: string | null;
  setAccessToken: (token: string | null) => void;
  setSession: (user: CurrentUser, permissions: string[], features: string[], impersonatorId?: string | null) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      currentUser: null,
      permissions: [],
      features: [],
      isAuthenticated: false,
      impersonatorId: null,
      setAccessToken: (token) => set({ accessToken: token, isAuthenticated: !!token }),
      setSession: (user, permissions, features, impersonatorId = null) =>
        set({ currentUser: user, permissions, features, impersonatorId, isAuthenticated: true }),
      logout: () => {
        queryClient.clear();
        useSessionStore.getState().reset();
        set({
          accessToken: null,
          currentUser: null,
          permissions: [],
          features: [],
          impersonatorId: null,
          isAuthenticated: false,
        });
      },
    }),
    {
      name: 'universe-auth',
      // the access token lives in memory only (15 min); the refresh token is an httpOnly cookie
      partialize: (s) => ({
        currentUser: s.currentUser,
        permissions: s.permissions,
        features: s.features,
        impersonatorId: s.impersonatorId,
      }),
    },
  ),
);
