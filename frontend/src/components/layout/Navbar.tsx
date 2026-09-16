import { Building2, LogOut, Menu, Search, User } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Avatar } from '@/components/ui/Avatar';
import { Button } from '@/components/ui/Button';
import { Dropdown } from '@/components/ui/Dropdown';
import { AppearanceMenu } from '@/components/shared/AppearanceMenu';
import { JobsTray } from '@/components/shared/JobsTray';
import { NotificationCenter } from '@/components/shared/NotificationCenter';
import { useAuthStore } from '@/store/authStore';
import { useSessionStore } from '@/store/sessionStore';

interface NavbarProps {
  onToggleSidebar: () => void;
}

/**
 * Admin-shell navbar: sidebar toggle, institution/college switcher (visible with >1 scope or super admin),
 * academic year/term selector (fed by Phase 03), global search (Ctrl+K), jobs tray, bell, user menu.
 */
export function Navbar({ onToggleSidebar }: NavbarProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.currentUser);
  const logout = useAuthStore((s) => s.logout);
  const { institutionName, collegeName, years, terms, academicYearId, termId, setYear, setTerm } = useSessionStore();
  const showSwitcher =
    !!user?.is_super_admin || (user?.scopes.filter((s) => s.scope_type === 'college').length ?? 0) > 1;

  return (
    <header className="app-navbar flex h-14 items-center gap-2 border-b bg-card px-3 sm:px-4">
      <Button variant="ghost" size="icon" onClick={onToggleSidebar} aria-label="Toggle navigation">
        <Menu className="h-5 w-5" />
      </Button>

      {showSwitcher && (
        <Button variant="outline" size="sm" className="hidden sm:inline-flex" onClick={() => navigate('/platform')}>
          <Building2 className="h-4 w-4" />
          <span className="max-w-[12rem] truncate">{collegeName ?? institutionName ?? 'Institution'}</span>
        </Button>
      )}

      {years.length === 0 && (
        <span
          className="hidden rounded-md border border-dashed px-2 py-1 text-xs text-muted-foreground md:inline"
          title="Academic years arrive with Phase 03"
        >
          Academic year —
        </span>
      )}
      {years.length > 0 && (
        <div className="hidden items-center gap-1 md:flex">
          <select
            className="h-8 rounded-md border bg-card px-2 text-sm"
            value={academicYearId ?? ''}
            onChange={(e) => setYear(e.target.value || null)}
            aria-label="Academic year"
          >
            {years.map((y) => (
              <option key={y.id} value={y.id}>
                {y.name}
              </option>
            ))}
          </select>
          <select
            className="h-8 rounded-md border bg-card px-2 text-sm"
            value={termId ?? ''}
            onChange={(e) => setTerm(e.target.value || null)}
            aria-label="Term"
          >
            <option value="">All terms</option>
            {terms
              .filter((tm) => !academicYearId || tm.academic_year_id === academicYearId)
              .map((tm) => (
                <option key={tm.id} value={tm.id}>
                  {tm.name}
                </option>
              ))}
          </select>
        </div>
      )}

      <div className="ml-auto flex items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          className="hidden text-muted-foreground sm:inline-flex"
          onClick={() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))}
        >
          <Search className="h-4 w-4" /> {t('common.search')}{' '}
          <kbd className="ml-2 rounded border px-1 text-[10px]">Ctrl K</kbd>
        </Button>
        <AppearanceMenu />
        <JobsTray />
        <NotificationCenter />
        <Dropdown
          trigger={
            <button
              type="button"
              className="ml-1 flex items-center gap-2 rounded-md p-1 hover:bg-accent"
              aria-label="Account menu"
            >
              <Avatar name={user?.display_name ?? user?.username} src={user?.avatar_url} size="sm" />
              <span className="hidden max-w-[10rem] truncate text-sm font-medium md:inline">
                {user?.display_name ?? user?.username}
              </span>
            </button>
          }
          items={[
            { label: 'My profile', icon: <User className="h-4 w-4" />, onSelect: () => navigate('/profile') },
            {
              label: t('common.logout'),
              icon: <LogOut className="h-4 w-4" />,
              destructive: true,
              separatorBefore: true,
              onSelect: () => {
                logout();
                navigate('/login');
              },
            },
          ]}
        />
      </div>
    </header>
  );
}
