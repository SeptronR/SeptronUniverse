import { Outlet } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import AccessDeniedPage from '@/pages/AccessDeniedPage';

/** Platform console (Phase 38): super_admin and support_agent only. */
export default function SuperAdminRoute() {
  const user = useAuthStore((s) => s.currentUser);
  const allowed = !!user?.is_super_admin || !!user?.role_slugs.includes('support_agent');
  if (!allowed) return <AccessDeniedPage />;
  return <Outlet />;
}
