import { useEffect, useMemo, useState } from 'react';
import { EmptyState } from '@/components/shared/EmptyState';
import { PageHeader } from '@/components/shared/PageHeader';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { getApiError } from '@/api/axios';
import { useAuthStore } from '@/store/authStore';
import { cn } from '@/utils/cn';
import { useWardDashboard, useWards } from '../hooks';
import { DashboardCards } from './StudentPortal';

const KEY = 'parent.ward';
const remembered = () => {
  try {
    return localStorage.getItem(KEY) ?? undefined;
  } catch {
    return undefined;
  }
};

/** /parent — ward switcher + ward dashboard. Wards whose consent is withdrawn (adult students decide) disappear on the
 *  next load; the API answers 404 for them. */
export default function ParentHomePage() {
  const user = useAuthStore((s) => s.currentUser);
  const wards = useWards();
  const list = useMemo(() => wards.data?.data ?? [], [wards.data]);
  const [active, setActive] = useState<string | undefined>(remembered);
  useEffect(() => {
    if (list.length && !list.some((w) => w.student_id === active)) setActive(list[0].student_id);
  }, [list, active]);
  useEffect(() => {
    try {
      if (active) localStorage.setItem(KEY, active);
    } catch {
      /* private mode */
    }
  }, [active]);
  const dash = useWardDashboard(list.some((w) => w.student_id === active) ? active : undefined);

  if (wards.isLoading) return <PageSkeleton />;
  return (
    <div className="space-y-4">
      <PageHeader title={`Hello${user?.display_name ? `, ${user.display_name}` : ''}`} description="Your wards' progress." />
      {list.length === 0 ? (
        <EmptyState title="No wards to show" description="Your ward's record appears here once the institution links you and portal access is consented." />
      ) : (
        <>
          {list.length > 1 && (
            <div role="tablist" aria-label="Ward" className="inline-flex flex-wrap rounded-md border bg-muted p-1">
              {list.map((w) => (
                <button
                  key={w.student_id}
                  role="tab"
                  type="button"
                  aria-selected={w.student_id === active}
                  onClick={() => setActive(w.student_id)}
                  className={cn('rounded-sm px-3 py-1 text-sm font-medium', w.student_id === active ? 'bg-card shadow-xs' : 'text-muted-foreground')}
                >
                  {w.name}
                </button>
              ))}
            </div>
          )}
          {dash.data ? (
            <>
              <DashboardCards d={dash.data.data} ward />
              <ConfirmedCourses courses={dash.data.data.confirmed_courses ?? []} />
            </>
          ) : dash.error ? <EmptyState title="Unavailable" description={getApiError(dash.error)} /> : <PageSkeleton />}
        </>
      )}
    </div>
  );
}

/** Phase 09: the ward's confirmed courses of the current term. */
function ConfirmedCourses({ courses }: { courses: { course_code: string; course_title: string; credits: number; section_code: string | null }[] }) {
  return (
    <section className="rounded-lg border bg-card p-4">
      <h2 className="mb-2 text-sm font-semibold">Registered courses</h2>
      {courses.length === 0 ? (
        <p className="text-sm text-muted-foreground">No confirmed course registration for the current term yet.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {courses.map((c) => (
            <li key={c.course_code} className="flex justify-between gap-2">
              <span><b>{c.course_code}</b> {c.course_title}{c.section_code ? ` · section ${c.section_code}` : ''}</span>
              <span className="text-muted-foreground">{c.credits} cr</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
