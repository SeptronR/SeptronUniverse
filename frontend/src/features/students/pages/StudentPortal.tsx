import { useState, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { QRCodeSVG } from 'qrcode.react';
import { BookOpen, CheckCircle2, CreditCard, Download, FileSignature, GraduationCap, Repeat, UserRound } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { EmptyState } from '@/components/shared/EmptyState';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Avatar } from '@/components/ui/Avatar';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Select } from '@/components/ui/Input';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { academicsApi } from '@/features/academics/api';
import { downloadBlob } from '@/features/hr/download';
import { SimpleTable } from '@/features/hr/components/shared';
import { formatDate, formatDateTime } from '@/utils/formatters';
import { studentsApi } from '../api';
import { Field, HoldBanner, StandingChip } from '../components/shared';
import { useStudentDashboard, useStudentMutation } from '../hooks';
import { CT_SOURCES, label, type StudentDashboard as Dashboard, type UndertakingStatus } from '../types';

const ICONS: Record<string, ReactNode> = {
  profile: <UserRound className="h-5 w-5" />,
  undertakings: <FileSignature className="h-5 w-5" />,
  id_card: <CreditCard className="h-5 w-5" />,
  curriculum: <BookOpen className="h-5 w-5" />,
  credit_transfers: <Repeat className="h-5 w-5" />,
};

/** Dashboard body shared by the student portal and the parent portal's ward view. */
export function DashboardCards({ d, ward = false }: { d: Dashboard; ward?: boolean }) {
  const s = d.student;
  const e = d.enrollment;
  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-wrap items-center gap-4 pt-4 sm:pt-4">
          <Avatar name={s.full_name} src={s.photo_url} size="lg" />
          <div className="min-w-0 flex-1">
            <p className="font-semibold">{s.full_name}</p>
            <p className="font-mono text-xs text-muted-foreground">{s.registration_number}</p>
            <p className="text-sm text-muted-foreground">
              {e ? `${e.program_name ?? e.program_code} · ${e.batch_code}${e.section_name ? ` · section ${e.section_name}` : ''}` : 'No open enrolment'}
            </p>
          </div>
          <StatusBadge status={s.status} />
        </CardContent>
      </Card>
      <HoldBanner holds={d.holds} contact="Contact the office that placed the hold to have it released." />
      <div className="grid gap-3 sm:grid-cols-4">
        <Card><CardContent className="pt-4 sm:pt-4"><p className="text-xs text-muted-foreground">Current term</p><p className="text-xl font-semibold">{e?.current_term_number ?? '—'}</p><p className="text-xs text-muted-foreground">{d.current_term?.term_name ?? ''}</p></CardContent></Card>
        <Card><CardContent className="pt-4 sm:pt-4"><p className="text-xs text-muted-foreground">CGPA</p><p className="text-xl font-semibold">{e?.cgpa ?? '—'}</p><p className="text-xs text-muted-foreground">{e?.credits_earned ?? 0} credits earned</p></CardContent></Card>
        <Card><CardContent className="pt-4 sm:pt-4"><p className="text-xs text-muted-foreground">Standing</p><div className="mt-1"><StandingChip standing={d.standing} /></div></CardContent></Card>
        <Card><CardContent className="pt-4 sm:pt-4"><p className="text-xs text-muted-foreground">Credit transfers pending</p><p className="text-xl font-semibold">{d.credit_transfers_pending}</p></CardContent></Card>
      </div>
      {!ward && (
        <div className="grid gap-3 sm:grid-cols-3">
          {d.quick_links.map((l) => (
            <Link key={l.key} to={l.route} className="flex items-center gap-3 rounded-lg border bg-card p-4 text-sm font-medium hover:bg-muted">
              {ICONS[l.key] ?? <GraduationCap className="h-5 w-5" />} {l.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function UndertakingCard({ u, onDone }: { u: UndertakingStatus; onDone: () => void }) {
  const [agree, setAgree] = useState(false);
  const accept = useStudentMutation(() => studentsApi.acceptUndertaking({ undertaking_type: u.undertaking_type, template_id: u.template_id ?? undefined }));
  return (
    <Card>
      <CardContent className="space-y-3 pt-4 sm:pt-4">
        <p className="font-semibold">{u.name} {u.version && <span className="text-xs font-normal text-muted-foreground">v{u.version}</span>}</p>
        <div className="max-h-56 overflow-y-auto whitespace-pre-line rounded-md border bg-muted/30 p-3 text-sm">{u.body ?? '—'}</div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> I have read and accept this undertaking.</label>
        <Button disabled={!agree} loading={accept.isPending} onClick={() => accept.mutate(undefined, { onSuccess: () => { toast.success(`${u.name} accepted`); onDone(); }, onError: (e) => toast.error(getApiError(e)) })}>Accept</Button>
      </CardContent>
    </Card>
  );
}

/** Pending required undertakings block every portal action except the dashboard and the undertakings page. */
function UndertakingGate({ children }: { children: ReactNode }) {
  const d = useStudentDashboard();
  const { pathname } = useLocation();
  if (!d.data) return d.error ? <EmptyState title="Unavailable" description={getApiError(d.error)} /> : <PageSkeleton />;
  const pending = d.data.data.undertakings_pending.filter((u) => u.required);
  if (pending.length && !pathname.endsWith('/undertakings')) {
    return (
      <div className="space-y-4">
        <div role="alert" className="rounded-md border border-status-pending/40 bg-status-pending/10 p-3 text-sm">
          <p className="font-semibold">Accept your pending undertakings first</p>
          <p>{pending.map((u) => u.name).join(', ')} must be accepted for this academic year before you can continue (registration and hostel also require them).</p>
          <Link to="/student/undertakings" className="mt-2 inline-block font-medium text-primary underline">Review undertakings</Link>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}

/** /student — dashboard (profile card, enrolment, holds banner, pending undertakings banner, quick links). */
export default function StudentHomePage() {
  const d = useStudentDashboard();
  if (!d.data) return d.error ? <EmptyState title="No student record" description={getApiError(d.error)} /> : <PageSkeleton />;
  const pending = d.data.data.undertakings_pending;
  return (
    <div className="space-y-4">
      <PageHeader title={`Hello, ${d.data.data.student.first_name}`} />
      {pending.length > 0 && (
        <div role="alert" className="rounded-md border border-status-pending/40 bg-status-pending/10 p-3 text-sm">
          <span className="font-semibold">{pending.length} undertaking(s) pending:</span> {pending.map((u) => u.name).join(', ')}.{' '}
          <Link to="/student/undertakings" className="font-medium text-primary underline">Accept now</Link> — other portal actions stay locked until then.
        </div>
      )}
      <DashboardCards d={d.data.data} />
    </div>
  );
}

/** /student/undertakings — read and accept (records time, IP and device). */
export function StudentUndertakingsPage() {
  const q = useQuery({ queryKey: ['students', 'me', 'undertakings'], queryFn: studentsApi.pendingUndertakings });
  const me = useQuery({ queryKey: ['students', 'me'], queryFn: studentsApi.me });
  const pending = q.data?.data ?? [];
  const accepted = (me.data?.data.undertakings ?? []).filter((u) => u.accepted);
  return (
    <div className="space-y-4">
      <PageHeader title="Undertakings" breadcrumbs={[{ label: 'Home', to: '/student' }, { label: 'Undertakings' }]} />
      {pending.length === 0 && <p className="flex items-center gap-2 text-sm text-status-approved"><CheckCircle2 className="h-4 w-4" /> Nothing pending for this academic year.</p>}
      {pending.map((u) => <UndertakingCard key={u.undertaking_type} u={u} onDone={() => { q.refetch(); me.refetch(); }} />)}
      {accepted.length > 0 && (
        <SimpleTable head={['Accepted', 'When']} rows={accepted.map((u) => [u.name, formatDateTime(u.accepted_at)])} />
      )}
    </div>
  );
}

/** /student/profile — self-service fields only (phone, e-mail, current address, emergency contact, photo). */
export function StudentProfilePage() {
  const me = useQuery({ queryKey: ['students', 'me'], queryFn: studentsApi.me });
  const [form, setForm] = useState<{ phone: string; email: string; address: string; ec_name: string; ec_phone: string } | null>(null);
  const save = useStudentMutation((body: Record<string, unknown>) => studentsApi.updateMe(body));
  const photo = useStudentMutation((f: File) => studentsApi.photo(me.data!.data.id, f));
  if (!me.data) return <PageSkeleton />;
  const s = me.data.data;
  const f = form ?? {
    phone: s.phone ?? '',
    email: s.email ?? '',
    address: String(s.current_address?.line1 ?? ''),
    ec_name: s.emergency_contact?.name ?? '',
    ec_phone: s.emergency_contact?.phone ?? '',
  };
  const submit = () =>
    save.mutate(
      {
        phone: f.phone || undefined,
        email: f.email || undefined,
        current_address: f.address ? { ...(s.current_address ?? {}), line1: f.address } : undefined,
        emergency_contact: f.ec_name && f.ec_phone ? { name: f.ec_name, phone: f.ec_phone } : undefined,
      },
      { onSuccess: () => { toast.success('Profile updated'); setForm(null); }, onError: (e) => toast.error(getApiError(e)) },
    );
  return (
    <div className="space-y-4">
      <PageHeader title="My profile" breadcrumbs={[{ label: 'Home', to: '/student' }, { label: 'Profile' }]} />
      <Card>
        <CardContent className="space-y-4 pt-4 sm:pt-4">
          <div className="flex items-center gap-4">
            <Avatar name={s.full_name} src={s.photo_url} size="lg" />
            <label className="text-sm">
              <span className="mb-1 block font-medium">Photo</span>
              <input type="file" accept="image/*" aria-label="Photo" onChange={(e) => e.target.files?.[0] && photo.mutate(e.target.files[0], { onSuccess: () => toast.success('Photo updated'), onError: (er) => toast.error(getApiError(er)) })} />
            </label>
          </div>
          <dl className="grid gap-3 sm:grid-cols-3">
            <Field k="Name" v={s.full_name} />
            <Field k="Registration no." v={s.registration_number} />
            <Field k="Date of birth" v={formatDate(s.dob)} />
            <Field k="Programme" v={s.enrollment?.program_name ?? s.program_code} />
            <Field k="Batch" v={s.batch_code} />
            <Field k="Category" v={s.category} />
          </dl>
          <p className="text-xs text-muted-foreground">Name, date of birth, category and identity numbers are changed by the office.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <FormField label="Phone" value={f.phone} onChange={(e) => setForm({ ...f, phone: e.target.value })} />
            <FormField label="E-mail" type="email" value={f.email} onChange={(e) => setForm({ ...f, email: e.target.value })} />
            <FormField label="Current address" className="sm:col-span-2" value={f.address} onChange={(e) => setForm({ ...f, address: e.target.value })} />
            <FormField label="Emergency contact name" value={f.ec_name} onChange={(e) => setForm({ ...f, ec_name: e.target.value })} />
            <FormField label="Emergency contact phone" value={f.ec_phone} onChange={(e) => setForm({ ...f, ec_phone: e.target.value })} />
          </div>
          <Button disabled={!form} loading={save.isPending} onClick={submit}>Save</Button>
        </CardContent>
      </Card>
    </div>
  );
}

/** /student/id-card — digital ID card with a QR that opens the public /verify page. */
export function StudentIdCardPage() {
  const q = useQuery({ queryKey: ['students', 'me', 'id-card'], queryFn: studentsApi.myIdCard, retry: false });
  if (!q.data) return q.error ? <EmptyState title="ID card unavailable" description={getApiError(q.error)} /> : <PageSkeleton />;
  const c = q.data.data;
  const path = `/verify/${encodeURIComponent(c.token)}`;
  return (
    <div className="space-y-4">
      <PageHeader title="ID card" breadcrumbs={[{ label: 'Home', to: '/student' }, { label: 'ID card' }]} />
      <Card className="mx-auto max-w-sm">
        <CardContent className="space-y-3 pt-4 sm:pt-4 text-center">
          <p className="text-sm font-semibold">{c.institution}</p>
          <p className="text-xs text-muted-foreground">{c.college}</p>
          <Avatar name={c.name} src={c.photo_url} size="lg" className="mx-auto" />
          <p className="font-semibold">{c.name}</p>
          <p className="font-mono text-sm">{c.registration_number}</p>
          <p className="text-xs text-muted-foreground">{c.program} · {c.batch}{c.blood_group ? ` · ${c.blood_group}` : ''}</p>
          <Link to={path} className="inline-block rounded-md bg-white p-2" aria-label="Verify this ID card">
            <QRCodeSVG value={c.verify_url} size={140} />
          </Link>
          <p className="text-xs text-muted-foreground">Valid until {formatDate(c.valid_until)}</p>
          <Button variant="outline" onClick={async () => downloadBlob(await studentsApi.myIdCardPdf(), 'id-card.pdf', true)}>
            <Download className="h-4 w-4" /> PDF
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

/** /student/curriculum — the enrolled programme regulation's structure (read through the enrolment link). */
export function StudentCurriculumPage() {
  const me = useQuery({ queryKey: ['students', 'me'], queryFn: studentsApi.me });
  const prId = me.data?.data.enrollment?.program_regulation_id;
  const st = useQuery({ queryKey: ['structure', prId], queryFn: () => academicsApi.structure(prId!), enabled: !!prId });
  if (!st.data) return st.error ? <EmptyState title="Curriculum unavailable" description={getApiError(st.error)} /> : <PageSkeleton />;
  const s = st.data.data;
  const current = me.data?.data.enrollment?.current_term_number;
  return (
    <div className="space-y-4">
      <PageHeader title="My curriculum" description={`${me.data?.data.enrollment?.program_name ?? ''} · ${me.data?.data.enrollment?.regulation_code ?? ''} · ${s.total_credits_required} credits`} breadcrumbs={[{ label: 'Home', to: '/student' }, { label: 'Curriculum' }]} />
      {s.terms.map((t) => (
        <Card key={t.term_number} className={t.term_number === current ? 'border-primary' : ''}>
          <CardContent className="pt-4 sm:pt-4">
            <p className="mb-2 text-sm font-semibold">{t.name} {t.term_number === current && <span className="text-xs text-primary">(current)</span>} {t.is_exit_point && <span className="text-xs text-muted-foreground">· exit point: {t.exit_award}</span>}</p>
            <SimpleTable
              head={['Code', 'Course', 'Type', 'L-T-P-C', 'Credits']}
              rows={s.courses.filter((c) => c.term_number === t.term_number).map((c) => [c.course_code ?? (c.basket_code ? `basket ${c.basket_code}` : ''), c.course_title ?? '—', label(c.course_type), c.ltpc ?? '—', c.credits ?? '—'])}
            />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/** /student/credit-transfers — submit MOOC / ABC / prior-institution credits with the certificate. */
export function StudentCreditTransfersPage() {
  const q = useQuery({ queryKey: ['credit-transfers', 'me'], queryFn: studentsApi.myCreditTransfers });
  const blank = { source: 'nptel', source_course_code: '', source_title: '', source_institution: '', credits: '', source_grade: '', source_score_pct: '' };
  const [f, setF] = useState(blank);
  const [file, setFile] = useState<File | null>(null);
  const submit = useStudentMutation(async () => {
    const r = await studentsApi.submitCreditTransfer({
      source: f.source,
      source_title: f.source_title,
      source_course_code: f.source_course_code || undefined,
      source_institution: f.source_institution || undefined,
      credits: f.credits,
      source_grade: f.source_grade || undefined,
      source_score_pct: f.source_score_pct || undefined,
    });
    if (file) await studentsApi.attachCertificate(r.data.id, file);
    return r;
  }, ['credit-transfers', 'students']);
  return (
    <div className="space-y-4">
      <PageHeader title="Credit transfers" breadcrumbs={[{ label: 'Home', to: '/student' }, { label: 'Credit transfers' }]} />
      <Card>
        <CardContent className="space-y-3 pt-4 sm:pt-4">
          <p className="text-sm font-semibold">Submit a course</p>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="space-y-1.5 text-sm font-medium">
              Source
              <Select aria-label="Source" options={CT_SOURCES.map((s) => ({ value: s, label: label(s) }))} value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} />
            </label>
            <FormField label="Course code" value={f.source_course_code} onChange={(e) => setF({ ...f, source_course_code: e.target.value })} />
            <FormField label="Course title" required value={f.source_title} onChange={(e) => setF({ ...f, source_title: e.target.value })} />
            <FormField label="Institution / platform" value={f.source_institution} onChange={(e) => setF({ ...f, source_institution: e.target.value })} />
            <FormField label="Credits" required type="number" step="0.5" min="0.5" value={f.credits} onChange={(e) => setF({ ...f, credits: e.target.value })} />
            <FormField label="Score %" type="number" min="0" max="100" value={f.source_score_pct} onChange={(e) => setF({ ...f, source_score_pct: e.target.value })} />
            <FormField label="Grade (if any)" value={f.source_grade} onChange={(e) => setF({ ...f, source_grade: e.target.value })} />
            <label className="space-y-1.5 text-sm font-medium sm:col-span-2">
              Certificate (PDF / image)
              <input className="block" type="file" accept=".pdf,image/*" aria-label="Certificate" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </label>
          </div>
          <Button
            disabled={f.source_title.length < 2 || !f.credits}
            loading={submit.isPending}
            onClick={() => submit.mutate(undefined, { onSuccess: () => { toast.success('Submitted for verification'); setF(blank); setFile(null); }, onError: (e) => toast.error(getApiError(e)) })}
          >
            Submit
          </Button>
        </CardContent>
      </Card>
      <SimpleTable
        head={['Source', 'Course', 'Credits', 'Grade', 'Equivalent', 'Status']}
        rows={(q.data?.data ?? []).map((c) => [label(c.source), `${c.source_course_code ?? ''} ${c.source_title}`, c.credits, c.letter_grade ?? c.source_grade ?? '—', c.equivalent_course ?? '—', <StatusBadge key="s" status={c.status} />])}
        empty="No submissions yet."
      />
    </div>
  );
}

export { UndertakingGate };
