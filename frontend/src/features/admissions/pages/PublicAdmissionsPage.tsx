import { useEffect } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { Badge } from '@/components/ui/Badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { SimpleTable } from '@/features/hr/components/shared';
import { admissionsApi } from '../api';
import { useInstitutionSlug } from '../institution';
import { label, rupees } from '../types';

/** Public /admissions?institution=<slug> — open cycles with the apply link and published merit lists. */
export default function PublicAdmissionsPage() {
  const institution = useInstitutionSlug();
  const list = useQuery({ queryKey: ['public-admissions', institution], queryFn: () => admissionsApi.publicCycles(institution), retry: false });
  useEffect(() => {
    document.title = 'Admissions';
  }, []);
  return (
    <main className="mx-auto max-w-4xl space-y-4 p-4 sm:p-6">
      <h1 className="text-2xl font-semibold">Admissions</h1>
      {list.isError && <p className="text-sm text-muted-foreground">{getApiError(list.error)}</p>}
      {list.data?.data.length === 0 && <p className="text-sm text-muted-foreground">No admission cycles are open right now.</p>}
      {(list.data?.data ?? []).map((c) => (
        <CycleCard key={c.slug} institution={institution} slug={c.slug} />
      ))}
    </main>
  );
}

function CycleCard({ institution, slug }: { institution: string; slug: string }) {
  const q = useQuery({ queryKey: ['public-cycle', institution, slug], queryFn: () => admissionsApi.publicCycle(institution, slug), retry: false });
  const c = q.data?.data;
  if (!c) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center justify-between gap-2 text-lg">
          {c.name}
          <Badge variant={c.is_open ? 'success' : 'outline'}>{c.is_open ? 'Applications open' : label(c.status)}</Badge>
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          {label(c.level)} · fee {rupees(c.application_fee_paise)} {c.closes_at ? `· apply by ${new Date(c.closes_at).toLocaleDateString()}` : ''}
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <SimpleTable head={['Programme', 'College', 'Intake', 'Entrance']} rows={c.programs.map((p) => [`${p.code} — ${p.name}`, p.college_name, p.intake + p.lateral_intake, label(p.entrance_source)])} />
        <div className="flex flex-wrap gap-3 text-sm">
          {c.is_open && <Link className="font-medium text-primary underline" to={`/apply/${c.slug}?institution=${institution}`}>Apply now</Link>}
          {c.published_merit_lists.map((m) => (
            <Link key={m.id} className="underline" to={`/admissions/${c.slug}/merit/${m.id}?institution=${institution}`}>{m.name}</Link>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

/** Public /admissions/:slug/merit/:id — published merit list (application number + rank only). */
export function PublicMeritPage() {
  const { slug, id } = useParams();
  const institution = useInstitutionSlug();
  const q = useQuery({ queryKey: ['public-merit', institution, slug, id], queryFn: () => admissionsApi.publicMerit(institution, slug!, id!), retry: false });
  useEffect(() => {
    document.title = q.data ? q.data.data.name : 'Merit list';
  }, [q.data]);
  return (
    <main className="mx-auto max-w-2xl space-y-4 p-4 sm:p-6">
      {q.isError && <p className="text-sm text-muted-foreground">{getApiError(q.error)}</p>}
      {q.data && (
        <>
          <h1 className="text-2xl font-semibold">{q.data.data.name}</h1>
          <p className="text-sm text-muted-foreground">{q.data.data.cycle} · published {q.data.data.published_at ? new Date(q.data.data.published_at).toLocaleString() : ''}</p>
          <SimpleTable head={['Rank', 'Application number']} rows={q.data.data.entries.map((e) => [e.rank, <span key="n" className="font-mono">{e.application_number}</span>])} />
        </>
      )}
    </main>
  );
}
