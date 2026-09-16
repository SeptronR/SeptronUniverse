import { Navigate, Outlet } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import { PORTAL_HOME, type RoleSlug } from '@/utils/constants';
import { PortalLayout } from '@/components/layout/PortalLayout';

interface Props {
  /** Role slugs allowed into this portal (e.g. ['student', 'learner']). */
  roles: RoleSlug[];
  title: string;
}

/** Portals are self-only and keyed by role_slugs; users without the role are sent to their own home. */
export default function PortalRoute({ roles, title }: Props) {
  const user = useAuthStore((s) => s.currentUser);
  const slugs = user?.role_slugs ?? [];
  if (!user?.is_super_admin && !roles.some((r) => slugs.includes(r))) {
    const home = slugs.map((s) => PORTAL_HOME[s as RoleSlug]).find(Boolean) ?? '/dashboard';
    return <Navigate to={home} replace />;
  }
  return (
    <PortalLayout title={title}>
      <Outlet />
    </PortalLayout>
  );
}
