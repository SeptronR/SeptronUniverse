import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ShieldAlert } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { Navbar } from './Navbar';
import { CommandPalette } from '@/components/shared/CommandPalette';
import { ConsentBanner } from '@/features/privacy/ConsentBanner';
import { useAuthStore } from '@/store/authStore';
import { useSessionStore } from '@/store/sessionStore';
import { useReadOnlyPoll } from '@/features/platform/hooks';
import { useStopImpersonation } from '@/features/auth/hooks';
import { Button } from '@/components/ui/Button';
import { wsClient } from '@/lib/ws';
import { PlatformBanners } from '@/features/saas/components/PlatformBanners';

/** Admin shell: sidebar + navbar + banners (impersonation, read-only). Portals use PortalLayout instead. */
export function AppLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem('universe-sidebar') === 'collapsed';
    } catch {
      return false;
    }
  });
  const readOnly = useSessionStore((s) => s.readOnly);
  const impersonatorId = useAuthStore((s) => s.impersonatorId);
  const user = useAuthStore((s) => s.currentUser);
  const readOnlyState = useReadOnlyPoll(); // GET /platform/read-only every minute → banner + disabled writes
  const stopImpersonation = useStopImpersonation();

  useEffect(() => {
    try {
      localStorage.setItem('universe-sidebar', collapsed ? 'collapsed' : 'expanded');
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  useEffect(() => {
    wsClient.connect();
    return () => wsClient.disconnect();
  }, []);

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <div className="hidden md:block">
        <Sidebar collapsed={collapsed} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <Navbar onToggleSidebar={() => setCollapsed((c) => !c)} />
        <PlatformBanners />
        {impersonatorId && (
          <div role="status" className="flex items-center gap-2 bg-warning px-4 py-1.5 text-sm text-warning-foreground">
            <ShieldAlert className="h-4 w-4" />
            {t('common.impersonating', { name: user?.display_name ?? user?.username })}
            <Button
              size="sm"
              variant="outline"
              className="ml-auto h-6"
              loading={stopImpersonation.isPending}
              onClick={() => stopImpersonation.mutate()}
            >
              {t('common.stopImpersonating')}
            </Button>
          </div>
        )}
        {readOnly && (
          <div
            role="status"
            className="flex items-center gap-2 bg-destructive px-4 py-1.5 text-sm text-destructive-foreground"
          >
            <AlertTriangle className="h-4 w-4" />
            {t('common.readOnly')}
            {readOnlyState.data?.data.reason && <span className="opacity-80">— {readOnlyState.data.data.reason}</span>}
          </div>
        )}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6" data-read-only={readOnly || undefined}>
          {children}
        </main>
      </div>
      <CommandPalette />
      <ConsentBanner />
    </div>
  );
}
