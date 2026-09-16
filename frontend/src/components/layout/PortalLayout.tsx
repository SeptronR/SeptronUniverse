import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, GraduationCap, LogOut } from 'lucide-react';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { NotificationCenter } from '@/components/shared/NotificationCenter';
import { useAuthStore } from '@/store/authStore';
import { useSessionStore } from '@/store/sessionStore';

interface PortalLayoutProps {
  title: string;
  children: ReactNode;
}

/** Self-only portals (student, parent, faculty, alumni, ...): compact header, no admin sidebar (Phase 39 adds tabs + PWA). */
export function PortalLayout({ title, children }: PortalLayoutProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.currentUser);
  const logout = useAuthStore((s) => s.logout);
  const readOnly = useSessionStore((s) => s.readOnly);
  const institutionName = useSessionStore((s) => s.institutionName);

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-card px-4">
        <GraduationCap className="h-6 w-6 text-primary" />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{institutionName ?? 'SeptronUniverse'}</p>
          <p className="truncate text-xs text-muted-foreground">{title} portal</p>
        </div>
        <div className="ml-auto flex items-center gap-1">
          <NotificationCenter />
          <Avatar name={user?.display_name ?? user?.username} src={user?.avatar_url} size="sm" />
          <Button
            variant="ghost"
            size="icon"
            aria-label={t('common.logout')}
            onClick={() => {
              logout();
              navigate('/login');
            }}
          >
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </header>
      {readOnly && (
        <div role="status" className="flex items-center gap-2 bg-destructive px-4 py-1.5 text-sm text-destructive-foreground">
          <AlertTriangle className="h-4 w-4" />
          {t('common.readOnly')}
        </div>
      )}
      <main className="mx-auto w-full max-w-5xl p-4 sm:p-6">{children}</main>
    </div>
  );
}
