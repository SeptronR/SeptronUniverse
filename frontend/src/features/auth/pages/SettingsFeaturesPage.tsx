import { useMemo, useState } from 'react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Input } from '@/components/ui/Input';
import { Switch } from '@/components/ui/Switch';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { useAuthStore } from '@/store/authStore';
import { titleCase } from '@/utils/formatters';
import { useInstitutionFeatures, useInstitutionToggle } from '../hooks';
import type { InstitutionFeatureFlag } from '../types';

/**
 * /admin/settings/features — the institution's own view: the platform state is read-only and the institution switch
 * can only narrow it (docs/Feature_Flags.md §1.5). Core keys are never toggleable.
 */
export default function SettingsFeaturesPage() {
  const institutionId = useAuthStore((s) => s.currentUser?.institution_id) ?? undefined;
  const features = useInstitutionFeatures(institutionId);
  const toggle = useInstitutionToggle();
  const [search, setSearch] = useState('');

  const groups = useMemo(() => {
    const rows = (features.data?.data.flags ?? []).filter((f) => !f.is_core);
    const needle = search.trim().toLowerCase();
    const filtered = needle ? rows.filter((f) => f.key.includes(needle) || f.name.toLowerCase().includes(needle)) : rows;
    const map = new Map<string, InstitutionFeatureFlag[]>();
    for (const f of filtered) map.set(f.group, [...(map.get(f.group) ?? []), f]);
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [features.data, search]);

  if (features.isLoading) return <PageSkeleton />;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Features"
        description="Switch off what your institution does not use. Enabling a feature the platform disabled needs the SeptronUniverse team."
      />
      <Input className="w-72" placeholder="Search features…" value={search} onChange={(e) => setSearch(e.target.value)} />
      <div className="space-y-6">
        {groups.map(([group, flags]) => (
          <section key={group}>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">{titleCase(group)}</h2>
            <div className="divide-y rounded-md border">
              {flags.map((f) => (
                <div key={f.key} className="flex items-center justify-between gap-4 p-3">
                  <div className="min-w-0">
                    <p className="flex items-center gap-2 text-sm font-medium">
                      {f.name}
                      {!f.platform_enabled && <Badge variant="outline">disabled by the platform</Badge>}
                    </p>
                    {f.description && <p className="truncate text-xs text-muted-foreground">{f.description}</p>}
                  </div>
                  <Switch
                    checked={f.effective}
                    disabled={!f.platform_enabled || toggle.isPending}
                    onCheckedChange={(enabled) =>
                      toggle.mutate(
                        { key: f.key, enabled },
                        {
                          onSuccess: () => toast.success(`${f.name} ${enabled ? 'enabled' : 'disabled'}`),
                          onError: (e) => toast.error(getApiError(e)),
                        },
                      )
                    }
                    aria-label={`${f.key} ${f.effective ? 'enabled' : 'disabled'}`}
                  />
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
