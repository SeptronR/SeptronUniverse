import { PageHeader } from '@/components/shared/PageHeader';
import { EmptyState } from '@/components/shared/EmptyState';
import { useAuthStore } from '@/store/authStore';

/** Portal landing placeholder; Phase 39 aggregates the per-role portal pages (self-only). */
export default function PortalHomePage() {
  const user = useAuthStore((s) => s.currentUser);
  return (
    <div className="space-y-4">
      <PageHeader title={`Hello${user?.display_name ? `, ${user.display_name}` : ''}`} description="Your portal is being set up." />
      <EmptyState title="Nothing here yet" description="Portal pages arrive with their modules (Phases 07-39)." />
    </div>
  );
}
