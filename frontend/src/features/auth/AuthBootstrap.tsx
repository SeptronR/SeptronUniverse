import { useEffect, useState, type ReactNode } from 'react';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useAuthStore } from '@/store/authStore';
import { restoreSession } from './hooks';

/**
 * Restores the session after a reload: the access token lives in memory only (15 minutes), the refresh token is an
 * httpOnly cookie scoped to `/api/v1/auth/refresh`. When a principal is remembered but no token is held, this
 * rotates the cookie once (single-flight — see `restoreSession`) and reloads `/auth/me`, so permissions, features
 * and scopes are current before the first render of a guarded route.
 */
export function AuthBootstrap({ children }: { children: ReactNode }) {
  const remembered = useAuthStore((s) => !!s.currentUser);
  const hasToken = useAuthStore((s) => !!s.accessToken);
  const [restoring, setRestoring] = useState(remembered && !hasToken);

  useEffect(() => {
    if (!remembered || hasToken) {
      setRestoring(false);
      return;
    }
    let cancelled = false;
    void restoreSession().finally(() => {
      if (!cancelled) setRestoring(false);
    });
    return () => {
      cancelled = true;
    };
  }, [remembered, hasToken]);

  if (restoring) return <PageSkeleton />;
  return <>{children}</>;
}
