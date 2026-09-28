import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { BookOpen, GraduationCap } from 'lucide-react';
import { getApiErrorCode } from '@/api/axios';
import { Badge } from '@/components/ui/Badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Input, Select } from '@/components/ui/Input';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { academicsApi } from '../api';
import { useCatalog } from '../hooks';
import { PROGRAM_LEVELS, label, num, type PublicCourse } from '../types';

/** Tenant of the public page: ``?institution=<slug>``, else the sub-domain (``<slug>.universe…``); a signed-in
 *  visitor's own institution travels in ``X-Institution-Id`` (axios interceptor). */
function useInstitutionSlug(): string | undefined {
  const [sp] = useSearchParams();
  const fromQuery = sp.get('institution') ?? undefined;
  const host = window.location.hostname;
  const fromHost = host.split('.').length >= 3 ? host.split('.')[0] : undefined;
  return fromQuery ?? fromHost;
}

function useSeo(title: string, description: string) {
  useEffect(() => {
    document.title = title;
    let meta = document.querySelector<HTMLMetaElement>('meta[name="description"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.name = 'description';
      document.head.appendChild(meta);
    }
    meta.content = description;
  }, [title, description]);
}

function Unavailable({ code }: { code?: string }) {
  return (
    <main className="mx-auto max-w-3xl p-8 text-center">
      <BookOpen className="mx-auto h-10 w-10 text-muted-foreground" />
      <h1 className="mt-3 text-xl font-semibold">Course catalogue unavailable</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {code === 'FEATURE_DISABLED' ? 'This institution has not published its course catalogue.' : 'Institution not found — open the catalogue from the institution website.'}
      </p>
    </main>
  );
}

const ltpc = (c: PublicCourse) => `${c.lecture_hours}-${c.tutorial_hours}-${c.practical_hours}-${num(c.credits)}`;

/** Public ``/catalog`` — programme cards → course lists (no internal ids; indexable title/meta). */
export default function CatalogPage() {
  const institution = useInstitutionSlug();
  const [level, setLevel] = useState('');
  const [q, setQ] = useState('');
  const catalog = useCatalog({ institution, level: level || undefined });
  const data = catalog.data?.data;
  useSeo(`Programmes & courses${data ? ` · ${data.institution}` : ''}`, `Programmes, curricula and course syllabi${data ? ` of ${data.institution}` : ''}.`);
  const programs = useMemo(
    () => (data?.programs ?? []).filter((p) => !q || `${p.code} ${p.name} ${p.specialization ?? ''}`.toLowerCase().includes(q.toLowerCase())),
    [data, q],
  );
  if (catalog.isLoading) return <PageSkeleton />;
  if (catalog.isError) return <Unavailable code={getApiErrorCode(catalog.error)} />;
  const qs = institution ? `?institution=${encodeURIComponent(institution)}` : '';
  return (
    <main className="mx-auto max-w-6xl space-y-4 p-4 sm:p-8">
      <header>
        <h1 className="text-2xl font-semibold">Programmes & courses</h1>
        <p className="text-sm text-muted-foreground">{programs.length} programmes · curricula under the active regulations</p>
      </header>
      <div className="flex flex-wrap gap-2">
        <Input className="w-64" placeholder="Search programmes…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search programmes" />
        <Select className="w-44" placeholder="All levels" aria-label="Level" options={PROGRAM_LEVELS.map((l) => ({ value: l, label: label(l) }))} value={level} onChange={(e) => setLevel(e.target.value)} />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {programs.map((p) => (
          <Card key={`${p.college}-${p.code}`}>
            <CardHeader>
              <CardTitle className="flex items-start justify-between gap-2 text-lg">
                <Link className="hover:underline" to={`/catalog/${encodeURIComponent(p.code)}${qs}`}>
                  {p.name}
                </Link>
                <GraduationCap className="h-5 w-5 shrink-0 text-muted-foreground" />
              </CardTitle>
              <p className="flex flex-wrap gap-1 text-xs">
                <Badge variant="outline">{p.degree_name}</Badge>
                <Badge variant="secondary">{label(p.level)}</Badge>
                <Badge variant="secondary">{num(p.duration_years)} years · {p.total_terms} terms</Badge>
                {p.regulation && <Badge variant="info">{p.regulation}</Badge>}
                {p.sanctioned_intake && <Badge variant="secondary">intake {p.sanctioned_intake}</Badge>}
              </p>
            </CardHeader>
            <CardContent className="text-sm">
              <p className="text-muted-foreground">
                {p.college_name ?? p.college} · {p.courses.length} courses{p.total_credits ? ` · ${num(p.total_credits)} credits` : ''}
              </p>
              <ul className="mt-2 grid gap-x-4 sm:grid-cols-2">
                {p.courses.slice(0, 8).map((c) => (
                  <li key={c.code} className="truncate">
                    <span className="font-medium">{c.code}</span> {c.title}
                  </li>
                ))}
              </ul>
              {p.courses.length > 8 && (
                <Link className="mt-2 inline-block text-primary hover:underline" to={`/catalog/${encodeURIComponent(p.code)}${qs}`}>
                  All {p.courses.length} courses →
                </Link>
              )}
            </CardContent>
          </Card>
        ))}
        {programs.length === 0 && <p className="text-sm text-muted-foreground">No programmes published.</p>}
      </div>
    </main>
  );
}

/** Public ``/catalog/:program`` — the programme's curriculum by term with syllabus units. */
export function CatalogProgramPage() {
  const { program = '' } = useParams();
  const institution = useInstitutionSlug();
  const detail = useQuery({
    queryKey: ['catalog', 'program', program, institution],
    queryFn: () => academicsApi.catalogProgram(program, { institution }),
    retry: false,
  });
  const p = detail.data?.data;
  useSeo(p ? `${p.name} (${p.regulation ?? ''}) — curriculum` : 'Programme', p ? `${p.degree_name} ${p.name}: ${p.courses.length} courses over ${p.total_terms} terms.` : 'Programme curriculum');
  if (detail.isLoading) return <PageSkeleton />;
  if (detail.isError || !p) return <Unavailable code={getApiErrorCode(detail.error)} />;
  const terms = [...new Set(p.courses.map((c) => c.term_number ?? 0))].sort((a, b) => a - b);
  const qs = institution ? `?institution=${encodeURIComponent(institution)}` : '';
  return (
    <main className="mx-auto max-w-5xl space-y-4 p-4 sm:p-8">
      <Link to={`/catalog${qs}`} className="text-sm text-primary hover:underline">
        ← All programmes
      </Link>
      <header>
        <h1 className="text-2xl font-semibold">{p.name}</h1>
        <p className="text-sm text-muted-foreground">
          {p.degree_name} · {label(p.level)} · {num(p.duration_years)} years · {p.college_name ?? p.college} · regulation {p.regulation ?? '—'}
          {p.total_credits ? ` · ${num(p.total_credits)} credits` : ''}
        </p>
      </header>
      {terms.map((t) => (
        <section key={t} aria-labelledby={`term-${t}`}>
          <h2 id={`term-${t}`} className="mb-2 text-lg font-semibold">
            {t ? `Term ${t}` : 'Electives'}
          </h2>
          <div className="space-y-2">
            {p.courses
              .filter((c) => (c.term_number ?? 0) === t)
              .map((c) => (
                <details key={c.code} className="rounded-md border p-3">
                  <summary className="cursor-pointer text-sm">
                    <span className="font-medium">{c.code}</span> · {c.title} <span className="text-muted-foreground">({label(c.course_type)}, L-T-P-C {ltpc(c)})</span>
                  </summary>
                  <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
                    {(c.syllabus ?? []).map((u) => (
                      <li key={u.unit}>
                        <span className="font-medium">{u.title}</span>
                        {u.hours ? <span className="text-muted-foreground"> · {u.hours} h</span> : null}
                        {u.topics.length > 0 && <p className="text-muted-foreground">{u.topics.join(' · ')}</p>}
                      </li>
                    ))}
                    {(c.syllabus ?? []).length === 0 && <li className="list-none text-muted-foreground">Syllabus not published.</li>}
                  </ol>
                  {c.textbooks && c.textbooks.length > 0 && <p className="mt-2 text-xs text-muted-foreground">Textbooks: {c.textbooks.join('; ')}</p>}
                </details>
              ))}
          </div>
        </section>
      ))}
    </main>
  );
}
