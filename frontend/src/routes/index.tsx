import { lazy, Suspense } from 'react';
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router-dom';
import PrivateRoute from './PrivateRoute';
import AdminShellRoute from './AdminShellRoute';
import PermissionRoute from './PermissionRoute';
import FeatureRoute from './FeatureRoute';
import SuperAdminRoute from './SuperAdminRoute';
import PortalRoute from './PortalRoute';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import NotFoundPage from '@/pages/NotFoundPage';

/**
 * Guard chain (docs/Technical_Architecture.md §14):
 *   PrivateRoute → SuperAdminRoute | AdminShellRoute(FeatureRoute(PermissionRoute(page))) | PortalRoute
 * Phases add lazy pages here; keep route-level code splitting.
 */
const LoginPage = lazy(() => import('@/pages/LoginPage'));
const DashboardPage = lazy(() => import('@/pages/DashboardPage'));
const AccessDeniedPage = lazy(() => import('@/pages/AccessDeniedPage'));
const FeatureDisabledPage = lazy(() => import('@/pages/FeatureDisabledPage'));
const PortalHomePage = lazy(() => import('@/pages/PortalHomePage'));

const page = (node: React.ReactNode) => (
  <ErrorBoundary>
    <Suspense fallback={<PageSkeleton />}>{node}</Suspense>
  </ErrorBoundary>
);

export const router = createBrowserRouter([
  { path: '/login', element: page(<LoginPage />) },
  { path: '/access-denied', element: page(<AccessDeniedPage />) },
  { path: '/feature-disabled', element: page(<FeatureDisabledPage />) },
  {
    element: <PrivateRoute />,
    children: [
      {
        element: <AdminShellRoute />,
        children: [
          { index: true, element: <Navigate to="/dashboard" replace /> },
          {
            path: '/dashboard',
            element: page(
              <FeatureRoute feature="core.dashboard">
                <PermissionRoute module="dashboard">
                  <DashboardPage />
                </PermissionRoute>
              </FeatureRoute>,
            ),
          },
        ],
      },
      {
        path: '/platform',
        element: <SuperAdminRoute />,
        children: [{ index: true, element: page(<DashboardPage />) }],
      },
      // Portals (self-only). Phase 39 fills the pages; the shells exist so PORTAL_HOME targets resolve.
      { path: '/student', element: <PortalRoute roles={['student', 'learner']} title="Student" />, children: [{ index: true, element: page(<PortalHomePage />) }] },
      { path: '/parent', element: <PortalRoute roles={['parent']} title="Parent" />, children: [{ index: true, element: page(<PortalHomePage />) }] },
      { path: '/faculty', element: <PortalRoute roles={['faculty', 'guest_faculty']} title="Faculty" />, children: [{ index: true, element: page(<PortalHomePage />) }] },
      { path: '/alumni', element: <PortalRoute roles={['alumni']} title="Alumni" />, children: [{ index: true, element: page(<PortalHomePage />) }] },
      { path: '/warden', element: <PortalRoute roles={['hostel_warden', 'hostel_gate_staff']} title="Warden" />, children: [{ index: true, element: page(<PortalHomePage />) }, { path: 'gate', element: page(<PortalHomePage />) }] },
      { path: '/driver', element: <PortalRoute roles={['driver']} title="Driver" />, children: [{ index: true, element: page(<PortalHomePage />) }] },
      { path: '/evaluator', element: <PortalRoute roles={['external_examiner']} title="Evaluator" />, children: [{ index: true, element: page(<PortalHomePage />) }] },
      { path: '/scholar', element: <PortalRoute roles={['research_scholar']} title="Scholar" />, children: [{ index: true, element: page(<PortalHomePage />) }] },
      { path: '/recruiter', element: <PortalRoute roles={['recruiter']} title="Recruiter" />, children: [{ index: true, element: page(<PortalHomePage />) }] },
      { path: '/apply', element: <PortalRoute roles={['applicant']} title="Admissions" />, children: [{ index: true, element: page(<PortalHomePage />) }] },
    ],
  },
  { path: '*', element: page(<NotFoundPage />) },
]);

export default function AppRoutes() {
  return <RouterProvider router={router} />;
}
