import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
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
import { useLogout } from '@/features/auth/hooks';
import { institutionApi } from '@/features/institution/api';
import { useFeature } from '@/hooks/useFeature';

interface NavbarProps {
  onToggleSidebar: () => void;
}

/**
 * Admin-shell navbar: sidebar toggle, institution/college switcher (live since Phase 03 — colleges from `/colleges`,
 * shown with `institution.multi_college` and more than one college), academic year/term selector (from
 * `/academic-years` + `/academic-terms`; `sessionStore` persists the choice and clears the query cache on a college
 * switch), global search (Ctrl+K), jobs tray, bell, user menu.
 */
export function Navbar({ onToggleSidebar }: NavbarProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.currentUser);
  const logout = useLogout();
  const { institutionName, collegeId, collegeName, years, terms, academicYearId, termId, setYear, setTerm, setYears, setCollege } =
    useSessionStore();
  const multiCollege = useFeature('institution.multi_college');
  const hasTenant = !!user?.institution_id;
  const colleges = useQuery({
    queryKey: ['colleges', { scope: 'all', page_size: 200, switcher: true }],
    queryFn: () => institutionApi.colleges({ scope: 'all', page_size: 200 }),
    enabled: hasTenant && multiCollege,
    staleTime: 5 * 60_000,
  });
  const sessions = useQuery({
    queryKey: ['academic-years', { college_id: collegeId, navbar: true }],
    queryFn: () => institutionApi.years({ college_id: collegeId ?? undefined, page_size: 50 }),
    enabled: hasTenant,
    staleTime: 5 * 60_000,
  });
  useEffect(() => {
    const rows = sessions.data?.data;
    if (!rows) return;
    setYears(
      rows.map((y) => ({ id: y.id, name: y.name, is_current: y.is_current })),
      rows.flatMap((y) => y.terms.map((t) => ({ id: t.id, name: t.name, academic_year_id: y.id, is_current: t.is_current }))),
    );
    const state = useSessionStore.getState();
    if (!state.academicYearId || !rows.some((y) => y.id === state.academicYearId)) {
      const current = rows.find((y) => y.is_current && y.college_id === collegeId) ?? rows.find((y) => y.is_current) ?? rows[0];
      if (current) {
        setYear(current.id);
        const term = current.terms.find((t) => t.is_current);
        if (term) setTerm(term.id);
      }
    }
  }, [sessions.data, collegeId, setYears, setYear, setTerm]);
  const collegeRows = colleges.data?.data ?? [];
  const showSwitcher = multiCollege && collegeRows.length > 1;

  return (
    <header className="app-navbar flex h-14 items-center gap-2 border-b bg-card px-3 sm:px-4">
      <Button variant="ghost" size="icon" onClick={onToggleSidebar} aria-label="Toggle navigation">
        <Menu className="h-5 w-5" />
      </Button>

      {showSwitcher && (
        <Dropdown
          trigger={
            <Button variant="outline" size="sm" className="hidden sm:inline-flex" aria-label="Switch college">
              <Building2 className="h-4 w-4" />
              <span className="max-w-[12rem] truncate">{collegeName ?? institutionName ?? 'Institution'}</span>
            </Button>
          }
          items={[
            { label: `All colleges · ${institutionName ?? 'Institution'}`, onSelect: () => setCollege(null, null) },
            ...collegeRows.map((c) => ({ label: `${c.code} · ${c.name}`, onSelect: () => setCollege(c.id, c.name) })),
          ]}
        />
      )}

      {years.length === 0 && (
        <span className="hidden rounded-md border border-dashed px-2 py-1 text-xs text-muted-foreground md:inline">
          No academic year
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
            { label: t('common.profile'), icon: <User className="h-4 w-4" />, onSelect: () => navigate('/profile') },
            {
              label: t('common.logout'),
              icon: <LogOut className="h-4 w-4" />,
              destructive: true,
              separatorBefore: true,
              onSelect: () => logout.mutate(false), // revokes the session server-side, then clears the store
            },
          ]}
        />
      </div>
    </header>
  );
}
