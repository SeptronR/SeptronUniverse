import { LogOut } from 'lucide-react';
import { NavLink, Outlet } from 'react-router-dom';
import { AppearanceMenu } from '@/components/shared/AppearanceMenu';
import { Button } from '@/components/ui/Button';
import { useLogout } from '@/features/auth/hooks';
import { useAuthStore } from '@/store/authStore';
import AccessDeniedPage from '@/pages/AccessDeniedPage';
import { cn } from '@/utils/cn';

const LINKS = [
  { to: '/platform', label: 'Dashboard', end: true },
  { to: '/super-admin/institutions', label: 'Institutions', end: false },
  { to: '/super-admin/features/matrix', label: 'Feature matrix', end: false },
];

/** Platform console (Phase 38): super_admin and support_agent only. Minimal header (links, appearance, sign-out) until
 * Phase 38 builds the full console shell — the institution AppLayout needs an institution context it does not have. */
export default function SuperAdminRoute() {
  const user = useAuthStore((s) => s.currentUser);
  const logout = useLogout();
  const allowed = !!user?.is_super_admin || !!user?.role_slugs.includes('support_agent');
  if (!allowed) return <AccessDeniedPage />;
  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-4 border-b bg-card px-4">
        <span className="font-semibold">Platform console</span>
        <nav aria-label="Platform" className="flex flex-1 items-center gap-1 overflow-x-auto">
          {LINKS.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) =>
                cn('whitespace-nowrap rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-accent-foreground', isActive && 'bg-accent font-medium text-accent-foreground')
              }
            >
              {l.label}
            </NavLink>
          ))}
        </nav>
        <span className="hidden text-sm text-muted-foreground sm:inline">{user?.display_name ?? user?.username}</span>
        <AppearanceMenu />
        <Button variant="ghost" size="sm" loading={logout.isPending} onClick={() => logout.mutate(false)}>
          <LogOut className="h-4 w-4" /> Sign out
        </Button>
      </header>
      <main className="mx-auto max-w-7xl p-4 sm:p-6">
        <Outlet />
      </main>
    </div>
  );
}
