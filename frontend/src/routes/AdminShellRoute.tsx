import { Navigate, Outlet } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import { PORTAL_HOME, PORTAL_ONLY_ROLES, type RoleSlug } from '@/utils/constants';
import { AppLayout } from '@/components/layout/AppLayout';

/**
 * Renders the admin shell (AppLayout). Portal-only roles (student, parent, alumni, driver, ...) are bounced to their
 * portal home; staff roles that also hold a portal role (e.g. faculty) stay in the shell.
 */
export default function AdminShellRoute() {
  const user = useAuthStore((s) => s.currentUser);
  const slugs = (user?.role_slugs ?? []) as RoleSlug[];
  const portalOnly = slugs.length > 0 && slugs.every((s) => PORTAL_ONLY_ROLES.includes(s)) && !user?.is_super_admin;
  if (portalOnly) {
    const home = slugs.map((s) => PORTAL_HOME[s]).find(Boolean) ?? '/login';
    return <Navigate to={home} replace />;
  }
  return (
    <AppLayout>
      <Outlet />
    </AppLayout>
  );
}
