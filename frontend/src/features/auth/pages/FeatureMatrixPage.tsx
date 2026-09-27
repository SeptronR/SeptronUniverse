import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader } from '@/components/shared/PageHeader';
import { Input } from '@/components/ui/Input';
import { Badge } from '@/components/ui/Badge';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useFeatureMatrix } from '../hooks';

/** /super-admin/features/matrix — institutions × features grid (Prompts/02 §02.9; docs/Feature_Flags.md §1.5). */
export default function FeatureMatrixPage() {
  const matrix = useFeatureMatrix();
  const [search, setSearch] = useState('');

  const features = useMemo(() => {
    const rows = (matrix.data?.data.features ?? []).filter((f) => !f.is_core);
    const needle = search.trim().toLowerCase();
    return needle ? rows.filter((f) => f.key.includes(needle)) : rows.slice(0, 60);
  }, [matrix.data, search]);
  const institutions = matrix.data?.data.institutions ?? [];

  if (matrix.isLoading) return <PageSkeleton />;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Feature matrix"
        description={`${institutions.length} institution(s) × ${matrix.data?.data.features.length ?? 0} features (core keys omitted).`}
      />
      <Input
        className="w-72"
        placeholder="Filter features (the first 60 are shown without a filter)…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <div className="overflow-auto rounded-md border">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/40">
              <th scope="col" className="sticky left-0 bg-muted/40 px-3 py-2 text-left">
                Feature
              </th>
              {institutions.map((i) => (
                <th key={i.id} scope="col" className="px-3 py-2 text-left">
                  <Link to={`/super-admin/institutions/${i.id}/features`} className="hover:underline">
                    {i.name}
                  </Link>
                  <div className="text-[11px] font-normal text-muted-foreground">{i.plan_code ?? 'no plan'}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {features.map((f) => (
              <tr key={f.key} className="border-b last:border-0">
                <th scope="row" className="sticky left-0 bg-card px-3 py-1.5 text-left font-normal">
                  <code className="text-xs">{f.key}</code>
                </th>
                {institutions.map((i) => (
                  <td key={i.id} className="px-3 py-1.5">
                    {i.effective.includes(f.key) ? <Badge variant="success">on</Badge> : <Badge variant="outline">off</Badge>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
