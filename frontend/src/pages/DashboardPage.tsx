import { useQuery } from '@tanstack/react-query';
import { Activity, Building2, GraduationCap, Users } from 'lucide-react';
import axios from 'axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatCard } from '@/components/ui/Card';
import { StatusBadge } from '@/components/ui/Badge';
import { useAuthStore } from '@/store/authStore';

/** Placeholder dashboard (Phase 01 adds the StatCard grid from /dashboard; Phase 35 the role dashboards). */
export default function DashboardPage() {
  const user = useAuthStore((s) => s.currentUser);
  const health = useQuery({
    queryKey: ['health'],
    queryFn: async () => (await axios.get<{ status: string; environment: string }>('/health')).data,
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Welcome${user?.display_name ? `, ${user.display_name}` : ''}`}
        description="Skeleton dashboard: role widgets land in Phase 35."
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Students" value="—" icon={<GraduationCap className="h-5 w-5" />} />
        <StatCard label="Staff" value="—" icon={<Users className="h-5 w-5" />} />
        <StatCard label="Colleges" value="—" icon={<Building2 className="h-5 w-5" />} />
        <StatCard
          label="API"
          value={health.isLoading ? '…' : <StatusBadge status={health.data?.status === 'ok' ? 'healthy' : 'failed'} />}
          hint={health.data?.environment}
          icon={<Activity className="h-5 w-5" />}
        />
      </div>
    </div>
  );
}
