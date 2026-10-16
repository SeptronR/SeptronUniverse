import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { AlertTriangle, ArrowDown, ArrowUp } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { cn } from '@/utils/cn';
import { registrationApi } from '../api';
import { useCatalog, useMyHistory, useMyOfferings, useMyRegistration, useRegistrationMutation } from '../hooks';
import { label, rupees, type CatalogBasket, type CatalogCourse, type CatalogOffering } from '../types';

function Seats({ o }: { o: CatalogOffering }) {
  const full = o.seats_left !== null && o.seats_left <= 0;
  return (
    <span className={cn('text-xs', full ? 'text-status-rejected' : 'text-muted-foreground')}>
      {o.enrolled_count}/{o.max_seats ?? '∞'} {full ? '· full (waitlist)' : ''}{o.waitlist_count ? ` · ${o.waitlist_count} waiting` : ''}
    </span>
  );
}

/** /student/registration — cart with credit meter, prerequisite hints, seats + waitlist, holds banners, fee preview. */
export default function StudentRegistrationPage() {
  const catalog = useCatalog();
  const mine = useMyRegistration();
  const [confirm, setConfirm] = useState(false);
  const [idemKey, setIdemKey] = useState(() => crypto.randomUUID());
  const add = useRegistrationMutation((v: { offering_id: string; registration_type?: string }) => registrationApi.addItem(v));
  const remove = useRegistrationMutation((id: string) => registrationApi.removeItem(id));
  const submit = useRegistrationMutation(() => registrationApi.submit(idemKey));
  const accept = useRegistrationMutation((id: string) => registrationApi.acceptWaitlist(id));
  useEffect(() => {
    document.title = 'Course registration';
  }, []);
  const c = catalog.data?.data;
  const reg = mine.data?.data ?? null;
  const live = useMemo(() => (reg?.items ?? []).filter((i) => ['selected', 'confirmed', 'waitlisted'].includes(i.status)), [reg]);
  const credits = reg?.total_credits ?? 0;
  const limits = c?.limits ?? reg?.limits;
  const editable = !reg || ['draft', 'changes_requested', 'rejected', 'approved'].includes(reg.status);
  const blocked = (c?.holds.length ?? 0) > 0 || (c?.undertakings_pending.length ?? 0) > 0;
  const over = limits ? credits > limits.max : false;
  const under = limits ? credits < limits.min : false;

  const doAdd = (offering_id: string, registration_type = 'regular') =>
    add.mutateAsync({ offering_id, registration_type }).then((r) => {
      const item = r.data.items.find((i) => i.offering_id === offering_id);
      toast.success(item?.status === 'waitlisted' ? `Waitlisted (position ${item.waitlist?.position ?? '?'})` : 'Added to the cart');
    }).catch((e) => toast.error(getApiError(e)));
  const inCart = (offeringId: string) => live.find((i) => i.offering_id === offeringId);

  const courseRow = (course: CatalogCourse, type = 'regular') => [
    <div key="c">
      <div className="font-medium">{course.code} {course.mandatory && <span className="text-xs text-muted-foreground">(mandatory)</span>}</div>
      <div className="text-xs text-muted-foreground">{course.title} · {course.credits} cr</div>
      {course.requisites.map((r, k) => (
        <div key={k} className={cn('text-xs', r.met ? 'text-muted-foreground' : 'text-status-rejected')}>{label(r.relation)}: {r.course_code} {r.met ? '✓' : '✗'}</div>
      ))}
    </div>,
    <div key="o" className="space-y-1">
      {course.offerings.length === 0 && <span className="text-xs text-muted-foreground">No open section</span>}
      {course.offerings.map((o) => {
        const item = inCart(o.offering_id);
        return (
          <div key={o.offering_id} className="flex flex-wrap items-center gap-2">
            <span className="text-sm">Sec {o.section_code}{o.targeted ? ' ★' : ''}</span>
            <span className="text-xs text-muted-foreground">{o.faculty.join(', ')}</span>
            <Seats o={o} />
            {item ? (
              <>
                <StatusBadge status={item.status} />
                {editable && <Button size="sm" variant="ghost" onClick={() => remove.mutateAsync(item.id).then(() => toast.success('Dropped')).catch((e) => toast.error(getApiError(e)))}>Drop</Button>}
              </>
            ) : (
              editable && !course.in_cart && <Button size="sm" variant="outline" disabled={add.isPending} onClick={() => doAdd(o.offering_id, type)}>{o.seats_left !== null && o.seats_left <= 0 ? 'Join waitlist' : 'Add'}</Button>
            )}
          </div>
        );
      })}
    </div>,
  ];

  if (catalog.isError && !reg) {
    return (
      <div className="space-y-4">
        <PageHeader title="Course registration" />
        <Card><CardContent className="pt-6 text-sm">{getApiError(catalog.error)}</CardContent></Card>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <PageHeader
        title="Course registration"
        description={c ? `${c.term.name} · term ${c.structure_term?.term_number ?? ''}${c.window ? ` · ${c.window.name} open until ${new Date(c.window.ends_at).toLocaleDateString()}` : ''}` : undefined}
        actions={<Link className="text-sm text-primary hover:underline" to="/student/registrations">History</Link>}
      />
      {c?.holds.length ? (
        <div className="flex items-center gap-2 rounded-md border border-status-rejected/40 bg-status-rejected/10 p-3 text-sm"><AlertTriangle className="h-4 w-4" /> Registration hold: {c.hold_details.map((h) => h.reason).join('; ')} — submission is blocked until the hold is released.</div>
      ) : null}
      {c?.undertakings_pending.length ? (
        <div className="rounded-md border border-status-pending/40 bg-status-pending/10 p-3 text-sm">Accept the pending undertakings first: {c.undertakings_pending.join(', ')} — <Link className="underline" to="/student/undertakings">open undertakings</Link></div>
      ) : null}
      {reg && (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-4 pt-6 text-sm">
            <StatusBadge status={reg.status} />
            {limits && (
              <div className="min-w-60 flex-1">
                <div className="mb-1 flex justify-between text-xs"><span>Credits {credits}</span><span>min {limits.min} · normal {limits.normal} · max {limits.max}</span></div>
                <div className="h-2 rounded bg-muted"><div className={cn('h-2 rounded', over ? 'bg-status-rejected' : under ? 'bg-status-pending' : 'bg-status-approved')} style={{ width: `${Math.min(100, (credits / Math.max(1, limits.max)) * 100)}%` }} /></div>
              </div>
            )}
            {reg.advisor_comment && <div className="text-xs">Advisor: {reg.advisor_comment}</div>}
            {c && <div className="text-xs">Fee preview: {rupees(c.fee_preview.total_paise)}</div>}
            {['draft', 'changes_requested', 'rejected'].includes(reg.status) && (
              <Button disabled={blocked || over || under || !live.length} onClick={() => setConfirm(true)}>Submit</Button>
            )}
          </CardContent>
        </Card>
      )}
      {reg && reg.items.some((i) => i.waitlist?.status === 'offered') && (
        <Card>
          <CardHeader><CardTitle>Seat offers</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {reg.items.filter((i) => i.waitlist?.status === 'offered').map((i) => (
              <div key={i.id} className="flex items-center gap-2">{i.course_code} — accept before {new Date(i.waitlist!.offered_until!).toLocaleString()}
                <Button size="sm" onClick={() => accept.mutateAsync(i.waitlist!.id).then(() => toast.success('Seat accepted')).catch((e) => toast.error(getApiError(e)))}>Accept</Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
      {c && (
        <>
          <Card>
            <CardHeader><CardTitle>Curriculum courses</CardTitle></CardHeader>
            <CardContent><SimpleTable head={['Course', 'Sections']} rows={c.curriculum.map((x) => courseRow(x))} empty="No curriculum courses for this term." /></CardContent>
          </Card>
          {c.baskets.map((b) => <BasketCard key={b.basket_id} basket={b} termId={c.term.id} />)}
          {c.arrears.length > 0 && (
            <Card>
              <CardHeader><CardTitle>Arrears</CardTitle></CardHeader>
              <CardContent>
                <SimpleTable head={['Course', 'Sections']} rows={c.arrears.map((a) => courseRow({ course_id: a.course_id, code: a.code, title: `${a.title} (attempt ${a.attempts + 1})`, credits: a.credits, course_type: null, mandatory: false, requisites: [], prerequisites_met: true, offerings: a.offerings, in_cart: a.in_cart }, 'arrear'))} />
              </CardContent>
            </Card>
          )}
        </>
      )}
      <Modal open={confirm} onOpenChange={setConfirm} title="Submit registration?" footer={
        <Button disabled={submit.isPending} onClick={() => submit.mutateAsync(undefined).then((r) => { toast.success(`Submitted — ${label(r.data.status)}`); setConfirm(false); setIdemKey(crypto.randomUUID()); }).catch((e) => toast.error(getApiError(e)))}>Submit</Button>
      }>
        <p className="text-sm">{live.length} course(s), {credits} credits. Your class advisor reviews the registration; you can change it again only if it is sent back.</p>
      </Modal>
    </div>
  );
}

function BasketCard({ basket, termId }: { basket: CatalogBasket; termId: string }) {
  const [order, setOrder] = useState<string[]>(() => (basket.choice_form?.choices.length ? basket.choice_form.choices.map((c) => c.course_id) : basket.courses.map((c) => c.course_id)));
  const save = useRegistrationMutation(() =>
    registrationApi.saveChoices(basket.basket_id, { term_id: termId, choices: order.map((course_id, i) => ({ course_id, priority: i + 1 })) }, !!basket.choice_form),
  );
  const move = (i: number, d: number) => {
    const next = [...order];
    const j = i + d;
    if (j < 0 || j >= next.length) return;
    [next[i], next[j]] = [next[j], next[i]];
    setOrder(next);
  };
  const locked = basket.choice_form && !['submitted', 'unallocated'].includes(basket.choice_form.status);
  return (
    <Card>
      <CardHeader><CardTitle>{basket.code} — {basket.name} {basket.choice_form && <StatusBadge status={basket.choice_form.status} />}</CardTitle></CardHeader>
      <CardContent className="space-y-2 text-sm">
        {basket.choice_form?.allocated_course_code && <div>Allocated: <b>{basket.choice_form.allocated_course_code}</b></div>}
        <p className="text-xs text-muted-foreground">Rank your choices; the allocation run walks them in order.</p>
        <ol className="space-y-1">
          {order.map((id, i) => {
            const course = basket.courses.find((c) => c.course_id === id);
            return (
              <li key={id} className="flex items-center gap-2">
                <span className="w-5 text-right">{i + 1}.</span>
                <span className="flex-1">{course?.code} {course?.title}</span>
                {!locked && <Button size="icon" variant="ghost" aria-label="Move up" onClick={() => move(i, -1)}><ArrowUp className="h-3 w-3" /></Button>}
                {!locked && <Button size="icon" variant="ghost" aria-label="Move down" onClick={() => move(i, 1)}><ArrowDown className="h-3 w-3" /></Button>}
              </li>
            );
          })}
        </ol>
        {!locked && <Button size="sm" disabled={save.isPending} onClick={() => save.mutateAsync(undefined).then(() => toast.success('Choices saved')).catch((e) => toast.error(getApiError(e)))}>{basket.choice_form ? 'Update choices' : 'Submit choices'}</Button>}
      </CardContent>
    </Card>
  );
}

/** /student/registrations — registration history. */
export function StudentRegistrationsHistory() {
  const history = useMyHistory();
  return (
    <div className="space-y-4">
      <PageHeader title="My registrations" />
      {(history.data?.data ?? []).map((r) => (
        <Card key={r.id}>
          <CardHeader><CardTitle>{r.term_name} · term {r.term_number} <StatusBadge status={r.status} /></CardTitle></CardHeader>
          <CardContent>
            <SimpleTable head={['Course', 'Credits', 'Type', 'Status']} rows={r.items.map((i) => [`${i.course_code} — ${i.course_title}`, i.credits, label(i.registration_type), <StatusBadge key="s" status={i.status} />])} />
          </CardContent>
        </Card>
      ))}
      {!history.isLoading && !(history.data?.data ?? []).length && <p className="text-sm text-muted-foreground">No registrations yet.</p>}
    </div>
  );
}

/** /faculty/offerings — the faculty member's offerings of the current term with roster links. */
export function FacultyOfferingsPage() {
  const offerings = useMyOfferings();
  return (
    <div className="space-y-4">
      <PageHeader title="My offerings" />
      <SimpleTable
        head={['Course', 'Section', 'Seats', 'Status', '']}
        rows={(offerings.data?.data ?? []).map((o) => [
          `${o.course_code} — ${o.course_title}`,
          o.section_code,
          `${o.enrolled_count}/${o.max_seats ?? '∞'}`,
          <StatusBadge key="s" status={o.status} />,
          <Link key="r" className="text-primary hover:underline" to={`/faculty/offerings/${o.id}`}>Roster</Link>,
        ])}
        empty={offerings.isLoading ? 'Loading…' : 'No offerings allocated to you.'}
      />
    </div>
  );
}
