/* eslint-disable react-refresh/only-export-components */
import { useEffect, useSyncExternalStore, type ReactNode } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Download, GraduationCap, LayoutDashboard, LogOut, RefreshCw, WifiOff } from 'lucide-react';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { NotificationCenter } from '@/components/shared/NotificationCenter';
import { PlatformBanners } from '@/features/saas/components/PlatformBanners';
import { portalApi, type PortalShellConfig } from '@/features/portals/api';
import { HelpDrawer } from '@/features/portals/components/HelpDrawer';
import { NavIcon } from '@/features/portals/components/icons';
import { TourRunner } from '@/features/portals/components/TourRunner';
import { applyUpdate, initPwa, loadLocale, promptInstall, pushLogout, pwaState } from '@/features/portals/lib';
import { useFeature } from '@/hooks/useFeature';
import { useAuthStore } from '@/store/authStore';
import { useSessionStore } from '@/store/sessionStore';
import { ConsentBanner } from '@/features/privacy/ConsentBanner';

interface PortalLayoutProps {
  title: string;
  children: ReactNode;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;

export const usePortalConfig = () =>
  useQuery({ queryKey: ['portal', 'config'], queryFn: () => portalApi.config(), retry: false, staleTime: 5 * 60_000 });

const useOnline = () =>
  useSyncExternalStore(
    (cb) => {
      window.addEventListener('online', cb);
      window.addEventListener('offline', cb);
      return () => {
        window.removeEventListener('online', cb);
        window.removeEventListener('offline', cb);
      };
    },
    () => navigator.onLine,
  );

/**
 * Branded portal shell (Prompts/39 §39.9): header (logo / app name / theme colour from `GET /portal/config`), persona
 * tabs (left rail on desktop, bottom bar on phones), term chip, ward switcher, notification bell, contextual help +
 * feedback, profile menu (language, admin-view switch, sign out), Phase 01/38 banners, install prompt, update toast and
 * an offline banner. No ScopeTabs are rendered in portals.
 */
export function PortalLayout({ title, children }: PortalLayoutProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const qc = useQueryClient();
  const user = useAuthStore((s) => s.currentUser);
  const logout = useAuthStore((s) => s.logout);
  const readOnly = useSessionStore((s) => s.readOnly);
  const institutionName = useSessionStore((s) => s.institutionName);
  const i18nWeb = useFeature('i18n.web');
  const cfg = usePortalConfig();
  const c: PortalShellConfig | undefined = cfg.data?.data;
  const online = useOnline();
  const pwa = useSyncExternalStore(pwaState.subscribe, () => `${pwaState.canInstall()}:${pwaState.updateReady()}`);
  const [canInstall, updateReady] = pwa.split(':').map((v) => v === 'true');
  const wards = useQuery({ queryKey: ['portal', 'wards'], queryFn: () => portalApi.wards(), enabled: c?.persona === 'parent', retry: false });

  useEffect(() => initPwa((user as Any)?.institution_slug ?? null), [user]);
  useEffect(() => {
    if (c?.language) void loadLocale(c.language, i18nWeb);
  }, [c?.language, i18nWeb]);
  useEffect(() => {
    if (c?.branding?.theme_color) {
      document.querySelector('meta[name="theme-color"]')?.setAttribute('content', c.branding.theme_color);
      document.title = `${title} · ${c.branding.short_name}`;
    }
  }, [c?.branding, title]);

  const err: Any = cfg.error;
  if (err?.response?.data?.error?.code === 'FEATURE_DISABLED') {
    const to = err.response.data.error.details?.redirect ?? '/access-denied';
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 p-6 text-center">
        <AlertTriangle className="h-8 w-8 text-warning" />
        <p>{t('portal.notEnabled')}</p>
        <Button onClick={() => navigate(to)}>{t('common.back')}</Button>
      </div>
    );
  }
  const tabs = c?.tabs ?? [];
  const switchWard = async (id: string) => {
    await portalApi.switchWard(id);
    await qc.invalidateQueries();
  };
  const changeLanguage = async (lng: string) => {
    await portalApi.updateMe({ locale: lng });
    await loadLocale(lng, i18nWeb);
    void qc.invalidateQueries({ queryKey: ['portal', 'config'] });
  };
  const signOut = async () => {
    await pushLogout();
    logout();
    navigate('/login');
  };
  const brandStyle = c?.branding?.theme_color ? { borderTopColor: c.branding.theme_color } : undefined;

  return (
    <div className="min-h-screen bg-background pb-16 md:pb-0">
      <a href="#portal-main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-card focus:p-2">
        {t('portal.skip')}
      </a>
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-t-4 bg-card px-4 print:hidden" style={brandStyle}>
        {c?.branding?.logo_url ? (
          <img src={c.branding.logo_url} alt="" className="h-8 w-8 rounded object-contain" />
        ) : (
          <GraduationCap className="h-6 w-6 text-primary" aria-hidden="true" />
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold">{c?.branding?.app_name ?? institutionName ?? 'SeptronUniverse'}</p>
          <p className="truncate text-xs text-muted-foreground">
            {title}
            {c?.term ? ` · ${c.term.name}` : ''}
          </p>
        </div>
        {c?.persona === 'parent' && (wards.data?.data as Any[])?.length > 0 && (
          <select
            data-tour="portal-ward"
            aria-label={t('portal.ward')}
            className="ml-2 h-8 max-w-[10rem] rounded-md border bg-background px-2 text-sm"
            value={c.ward_id ?? ''}
            onChange={(e) => void switchWard(e.target.value)}
          >
            {(wards.data?.data as Any[]).map((w) => (
              <option key={w.student_id} value={w.student_id}>{w.name}</option>
            ))}
          </select>
        )}
        <div className="ml-auto flex items-center gap-1">
          {canInstall && (
            <Button variant="ghost" size="icon" aria-label={t('portal.install')} title={t('portal.installHint')} onClick={() => void promptInstall()}>
              <Download className="h-4 w-4" />
            </Button>
          )}
          <span data-tour="portal-bell"><NotificationCenter /></span>
          <HelpDrawer persona={c?.persona ?? null} />
          {c?.admin_switch && (
            <Button variant="ghost" size="icon" aria-label={t('portal.adminView')} title={t('portal.adminView')} data-tour="portal-admin-switch" onClick={() => navigate('/dashboard')}>
              <LayoutDashboard className="h-4 w-4" />
            </Button>
          )}
          {(c?.locales?.length ?? 0) > 1 && (
            <select aria-label={t('portal.language')} className="h-8 rounded-md border bg-background px-1 text-xs" value={c?.language} onChange={(e) => void changeLanguage(e.target.value)}>
              {c?.locales.map((l) => <option key={l} value={l}>{l === 'hi' ? 'हिन्दी' : l.toUpperCase()}</option>)}
            </select>
          )}
          <Link to={`${c?.home ?? ''}/profile`} aria-label={t('portal.profile')}>
            <Avatar name={user?.display_name ?? user?.username} src={user?.avatar_url} size="sm" />
          </Link>
          <Button variant="ghost" size="icon" aria-label={t('common.logout')} onClick={() => void signOut()}>
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </header>
      <PlatformBanners />
      {readOnly && (
        <div role="status" className="flex items-center gap-2 bg-destructive px-4 py-1.5 text-sm text-destructive-foreground">
          <AlertTriangle className="h-4 w-4" />
          {t('common.readOnly')}
        </div>
      )}
      {!online && (
        <div role="status" className="flex items-center gap-2 bg-warning px-4 py-1.5 text-sm text-warning-foreground">
          <WifiOff className="h-4 w-4" /> {t('portal.offline')}
        </div>
      )}
      {updateReady && (
        <div role="status" className="fixed bottom-20 right-4 z-40 flex items-center gap-2 rounded-lg border bg-card p-3 text-sm shadow-lg md:bottom-4">
          {t('portal.update')}
          <Button size="sm" onClick={applyUpdate}><RefreshCw className="mr-1 h-3 w-3" />{t('portal.reload')}</Button>
        </div>
      )}
      <div className="mx-auto flex w-full max-w-6xl">
        {tabs.length > 0 && (
          <nav aria-label={title} data-tour="portal-tabs" className="hidden w-48 shrink-0 flex-col gap-1 p-3 md:flex print:hidden">
            {tabs.map((tab) => (
              <NavLink
                key={tab.key}
                to={tab.route}
                end={tab.route === c?.home}
                className={({ isActive }) => `flex items-center gap-2 rounded-md px-3 py-2 text-sm ${isActive ? 'bg-primary/10 font-medium text-primary' : 'hover:bg-muted'}`}
              >
                <NavIcon name={tab.icon} className="h-4 w-4" /> {t(tab.label_key)}
              </NavLink>
            ))}
          </nav>
        )}
        <main id="portal-main" tabIndex={-1} className="min-w-0 flex-1 p-4 outline-none sm:p-6" data-tour="page-main">
          {children}
          <ConsentBanner />
        </main>
      </div>
      {tabs.length > 0 && (
        <nav aria-label={title} className="fixed inset-x-0 bottom-0 z-30 flex border-t bg-card md:hidden print:hidden" data-tour="portal-more">
          {tabs.slice(0, 5).map((tab) => (
            <NavLink
              key={tab.key}
              to={tab.route}
              end={tab.route === c?.home}
              className={({ isActive }) => `flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] ${isActive || pathname === tab.route ? 'text-primary' : 'text-muted-foreground'}`}
            >
              <NavIcon name={tab.icon} /> {t(tab.label_key)}
            </NavLink>
          ))}
        </nav>
      )}
      <TourRunner enabled={Boolean(c?.tours_enabled)} />
    </div>
  );
}
