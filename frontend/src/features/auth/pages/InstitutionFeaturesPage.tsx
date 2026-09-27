import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { History, RotateCcw } from 'lucide-react';
import { getApiError, getApiErrorDetails } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Switch } from '@/components/ui/Switch';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { useAuthStore } from '@/store/authStore';
import { formatDateTime, titleCase } from '@/utils/formatters';
import { useApplyPlanDefaults, useInstitutionFeatures, useSetPlatformFlag } from '../hooks';
import type { InstitutionFeatureFlag } from '../types';

/**
 * /super-admin/institutions/:id/features — grouped toggles with search, plan badge, dependency confirmation dialog
 * and the change log (Prompts/02 §02.9; docs/Feature_Flags.md §1.5).
 */
export default function InstitutionFeaturesPage() {
  const routeParams = useParams<{ id: string }>();
  const currentInstitution = useAuthStore((s) => s.currentUser?.institution_id);
  const institutionId = routeParams.id ?? currentInstitution ?? undefined;
  const features = useInstitutionFeatures(institutionId);
  const setFlag = useSetPlatformFlag(institutionId);
  const applyDefaults = useApplyPlanDefaults(institutionId);
  const [search, setSearch] = useState('');
  const [pending, setPending] = useState<{ flag: InstitutionFeatureFlag; missing: string[] } | null>(null);
  const [showLog, setShowLog] = useState(false);

  const groups = useMemo(() => {
    const rows = features.data?.data.flags ?? [];
    const needle = search.trim().toLowerCase();
    const filtered = needle
      ? rows.filter((f) => f.key.includes(needle) || f.name.toLowerCase().includes(needle))
      : rows;
    const map = new Map<string, InstitutionFeatureFlag[]>();
    for (const f of filtered) map.set(f.group, [...(map.get(f.group) ?? []), f]);
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [features.data, search]);

  const toggle = (flag: InstitutionFeatureFlag, enabled: boolean, confirmDependencies = false) => {
    setFlag.mutate(
      { key: flag.key, enabled, confirm_dependencies: confirmDependencies },
      {
        onSuccess: () => {
          setPending(null);
          toast.success(`${flag.name} ${enabled ? 'enabled' : 'disabled'}`);
        },
        onError: (e) => {
          const details = getApiErrorDetails(e) as { missing_dependencies?: string[]; dependants?: string[] };
          if (details.missing_dependencies?.length) {
            setPending({ flag, missing: details.missing_dependencies });
            return;
          }
          toast.error(getApiError(e, 'Could not change the feature'));
        },
      },
    );
  };

  if (features.isLoading) return <PageSkeleton />;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Features"
        description={
          <span className="flex items-center gap-2">
            Plan
            <Badge variant="info">{features.data?.data.plan_code ?? 'none'}</Badge>
            <span className="text-xs">Effective = platform switch AND the institution's own switch.</span>
          </span>
        }
        actions={
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setShowLog(true)}>
              <History className="h-4 w-4" /> Change log
            </Button>
            <Button
              variant="outline"
              loading={applyDefaults.isPending}
              onClick={() =>
                applyDefaults.mutate(undefined, {
                  onSuccess: (res) => toast.success(`${res.data.applied} feature(s) reset to the ${res.data.plan_code} plan`),
                  onError: (e) => toast.error(getApiError(e)),
                })
              }
            >
              <RotateCcw className="h-4 w-4" /> Apply plan defaults
            </Button>
          </div>
        }
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
                      <code className="text-xs text-muted-foreground">{f.key}</code>
                      {f.is_core && <Badge variant="secondary">core</Badge>}
                      {f.source === 'override' && <Badge variant="warning">override</Badge>}
                      {!f.plan_allows && <Badge variant="outline">above plan</Badge>}
                    </p>
                    {f.description && <p className="truncate text-xs text-muted-foreground">{f.description}</p>}
                    {f.depends_on.length > 0 && (
                      <p className="text-xs text-muted-foreground">depends on: {f.depends_on.join(', ')}</p>
                    )}
                  </div>
                  <Switch
                    checked={f.effective}
                    disabled={f.is_core || setFlag.isPending}
                    onCheckedChange={(v) => toggle(f, v)}
                    aria-label={`${f.key} ${f.effective ? 'enabled' : 'disabled'}`}
                  />
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>

      <Modal
        open={!!pending}
        onOpenChange={(open) => !open && setPending(null)}
        title="Enable dependencies?"
        description={`${pending?.flag.name ?? ''} needs other features to work.`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setPending(null)}>
              Cancel
            </Button>
            <Button loading={setFlag.isPending} onClick={() => pending && toggle(pending.flag, true, true)}>
              Enable all
            </Button>
          </>
        }
      >
        <ul className="list-inside list-disc text-sm">
          {(pending?.missing ?? []).map((k) => (
            <li key={k}>{k}</li>
          ))}
        </ul>
      </Modal>

      <Modal open={showLog} onOpenChange={setShowLog} title="Feature change log" size="lg">
        <ul className="space-y-2 text-sm">
          {(features.data?.data.changes ?? []).map((c) => (
            <li key={c.id} className="rounded-md border p-2">
              <p className="font-medium">{c.feature_key}</p>
              <p className="text-xs text-muted-foreground">
                {formatDateTime(c.changed_at)}
                {c.reason ? ` · ${c.reason}` : ''} ·{' '}
                {JSON.stringify(c.old_value ?? {})} → {JSON.stringify(c.new_value ?? {})}
              </p>
            </li>
          ))}
          {(features.data?.data.changes ?? []).length === 0 && (
            <li className="text-muted-foreground">No changes recorded yet.</li>
          )}
        </ul>
      </Modal>
    </div>
  );
}
