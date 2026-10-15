import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowDown, ArrowUp, Check } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Input, Select } from '@/components/ui/Input';
import { toast } from '@/components/ui/Toaster';
import { useLogin } from '@/features/auth/hooks';
import { useAuthStore } from '@/store/authStore';
import { admissionsApi } from '../api';
import { useAdmissionsMutation, useMyApplication } from '../hooks';
import { label, rupees, type Applicant, type PublicCycle } from '../types';
import { useInstitutionSlug } from '../institution';

const PHONE = /^\+?[0-9 -]{8,20}$/;
const STEPS = ['personal', 'qualifications', 'preferences', 'documents', 'review', 'pay'] as const;
type Step = (typeof STEPS)[number];

/** Account step: send the OTP, verify it (creates the applicant account + draft), sign in. */
function AccountStep({ cycle, institution }: { cycle: PublicCycle; institution: string }) {
  const login = useLogin();
  const [f, setF] = useState({ first_name: '', last_name: '', phone: '', email: '', password: '', otp: '' });
  const [sent, setSent] = useState(false);
  const [devOtp, setDevOtp] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [signIn, setSignIn] = useState({ identifier: '', password: '' });
  const valid = f.first_name.trim() && PHONE.test(f.phone) && f.password.length >= 8;
  const send = async () => {
    setBusy(true);
    try {
      const r = await admissionsApi.start(institution, cycle.slug, { first_name: f.first_name, last_name: f.last_name || undefined, phone: f.phone, email: f.email || undefined, password: f.password });
      setSent(true);
      setDevOtp(r.data.dev_otp);
      toast.success('Code sent to your phone');
    } catch (e) {
      toast.error(getApiError(e));
    } finally {
      setBusy(false);
    }
  };
  const verify = async () => {
    setBusy(true);
    try {
      const r = await admissionsApi.start(institution, cycle.slug, { first_name: f.first_name, last_name: f.last_name || undefined, phone: f.phone, email: f.email || undefined, password: f.password, otp_code: f.otp });
      toast.success(`Application ${r.data.application_number} started — keep this number`);
      await login.mutateAsync({ identifier: r.data.username!, password: f.password });
    } catch (e) {
      toast.error(getApiError(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card>
        <CardHeader><CardTitle className="text-base">Create your application account</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <FormField label="First name" required value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} />
          <FormField label="Last name" value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} />
          <FormField label="Mobile" required error={f.phone && !PHONE.test(f.phone) ? 'Enter a valid mobile number' : undefined} value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
          <FormField label="E-mail" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
          <FormField label="Password" type="password" required hint="At least 8 characters" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
          {!sent ? (
            <Button disabled={!valid || busy} onClick={send}>Send verification code</Button>
          ) : (
            <div className="space-y-2">
              <FormField label="Verification code" inputMode="numeric" value={f.otp} onChange={(e) => setF({ ...f, otp: e.target.value.replace(/\D/g, '').slice(0, 6) })} hint={devOtp ? `Development code: ${devOtp}` : undefined} />
              <Button disabled={f.otp.length !== 6 || busy} onClick={verify}>Verify &amp; continue</Button>
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="text-base">Already applied?</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <FormField label="Application number / mobile" value={signIn.identifier} onChange={(e) => setSignIn({ ...signIn, identifier: e.target.value })} />
          <FormField label="Password" type="password" value={signIn.password} onChange={(e) => setSignIn({ ...signIn, password: e.target.value })} />
          <Button variant="outline" disabled={!signIn.identifier || !signIn.password || login.isPending} onClick={() => login.mutateAsync(signIn).catch((e) => toast.error(getApiError(e)))}>Sign in</Button>
        </CardContent>
      </Card>
    </div>
  );
}

function PersonalStep({ a, cycle, next }: { a: Applicant; cycle: PublicCycle; next: () => void }) {
  const save = useAdmissionsMutation((b: Record<string, unknown>) => admissionsApi.updateMe(b));
  const [f, setF] = useState({
    dob: a.dob ?? '', gender: a.gender ?? '', category: a.category ?? '', is_pwd: a.is_pwd, quota_claimed: a.quota_claimed ?? '',
    domicile_state: a.domicile_state ?? '', email: a.contact?.email ?? '', address: a.contact?.address ?? '',
    guardian_name: a.contact?.guardian_name ?? '', guardian_relation: a.contact?.guardian_relation ?? 'father', guardian_phone: a.contact?.guardian_phone ?? '',
  });
  const ok = f.dob && f.gender && f.category && (!f.guardian_phone || PHONE.test(f.guardian_phone));
  const submit = async () => {
    try {
      await save.mutateAsync({
        dob: f.dob, gender: f.gender, category: f.category, is_pwd: f.is_pwd, quota_claimed: f.quota_claimed || undefined, domicile_state: f.domicile_state || undefined,
        contact: { email: f.email || undefined, address: f.address || undefined, guardian_name: f.guardian_name || undefined, guardian_relation: f.guardian_relation, guardian_phone: f.guardian_phone || undefined },
      });
      next();
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <FormField label="Date of birth" type="date" required value={f.dob} onChange={(e) => setF({ ...f, dob: e.target.value })} />
      <div className="space-y-1.5"><label className="text-sm font-medium" htmlFor="g">Gender</label><Select id="g" placeholder="Select…" options={[{ value: 'M', label: 'Male' }, { value: 'F', label: 'Female' }, { value: 'O', label: 'Other' }]} value={f.gender} onChange={(e) => setF({ ...f, gender: e.target.value })} /></div>
      <div className="space-y-1.5"><label className="text-sm font-medium" htmlFor="c">Category</label><Select id="c" placeholder="Select…" options={cycle.categories.map((c) => ({ value: c.code, label: c.name }))} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} /></div>
      <div className="space-y-1.5"><label className="text-sm font-medium" htmlFor="q">Quota claimed</label><Select id="q" placeholder="—" options={cycle.quotas.map((c) => ({ value: c.code, label: c.name }))} value={f.quota_claimed} onChange={(e) => setF({ ...f, quota_claimed: e.target.value })} /></div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_pwd} onChange={(e) => setF({ ...f, is_pwd: e.target.checked })} /> Person with disability</label>
      <FormField label="Domicile state" value={f.domicile_state} onChange={(e) => setF({ ...f, domicile_state: e.target.value })} />
      <FormField label="E-mail" type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
      <FormField label="Address" value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} />
      <FormField label="Parent / guardian name" value={f.guardian_name} onChange={(e) => setF({ ...f, guardian_name: e.target.value })} />
      <FormField label="Parent / guardian mobile" error={f.guardian_phone && !PHONE.test(f.guardian_phone) ? 'Enter a valid mobile' : undefined} value={f.guardian_phone} onChange={(e) => setF({ ...f, guardian_phone: e.target.value })} />
      <div className="sm:col-span-2"><Button disabled={!ok || save.isPending} onClick={submit}>Save &amp; continue</Button></div>
    </div>
  );
}

function QualificationsStep({ a, next }: { a: Applicant; next: () => void }) {
  const save = useAdmissionsMutation((b: Record<string, unknown>) => admissionsApi.updateMe(b));
  const q = a.qualifying_exams?.[0] ?? {};
  const [f, setF] = useState({ level: q.level ?? '12', board: q.board ?? '', year: String(q.year ?? ''), pct: String(q.pct ?? ''), subjects: (q.subjects ?? []).join(', '), exam: String(a.entrance?.exam ?? ''), score: String(a.entrance?.score ?? ''), max_score: String(a.entrance?.max_score ?? ''), roll_no: String(a.entrance?.roll_no ?? '') });
  const pctOk = Number(f.pct) > 0 && Number(f.pct) <= 100;
  const submit = async () => {
    try {
      await save.mutateAsync({
        qualifying_exams: [{ level: f.level, board: f.board, year: Number(f.year) || undefined, pct: Number(f.pct), subjects: f.subjects.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean) }],
        entrance: f.score ? { exam: f.exam, score: Number(f.score), max_score: Number(f.max_score) || undefined, roll_no: f.roll_no || undefined } : undefined,
      });
      next();
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <FormField label="Qualifying level" value={f.level} onChange={(e) => setF({ ...f, level: e.target.value })} />
      <FormField label="Board / university" value={f.board} onChange={(e) => setF({ ...f, board: e.target.value })} />
      <FormField label="Year of passing" value={f.year} onChange={(e) => setF({ ...f, year: e.target.value })} />
      <FormField label="Percentage" required error={f.pct && !pctOk ? '0–100' : undefined} value={f.pct} onChange={(e) => setF({ ...f, pct: e.target.value })} />
      <FormField label="Subjects (codes, comma separated)" className="sm:col-span-2" value={f.subjects} onChange={(e) => setF({ ...f, subjects: e.target.value })} />
      <FormField label="Entrance exam" value={f.exam} onChange={(e) => setF({ ...f, exam: e.target.value })} />
      <FormField label="Roll number" value={f.roll_no} onChange={(e) => setF({ ...f, roll_no: e.target.value })} />
      <FormField label="Score" value={f.score} onChange={(e) => setF({ ...f, score: e.target.value })} />
      <FormField label="Maximum score" value={f.max_score} onChange={(e) => setF({ ...f, max_score: e.target.value })} />
      <div className="sm:col-span-2"><Button disabled={!pctOk || save.isPending} onClick={submit}>Save &amp; continue</Button></div>
    </div>
  );
}

function PreferencesStep({ a, cycle, next }: { a: Applicant; cycle: PublicCycle; next: () => void }) {
  const [order, setOrder] = useState<string[]>(a.preferences.map((p) => p.program_id));
  const save = useAdmissionsMutation(() => admissionsApi.myPreferences(order.map((program_id) => ({ program_id }))));
  const elig = useQuery({ queryKey: ['admissions', 'me', 'eligibility', a.preferences.length], queryFn: admissionsApi.myEligibility });
  const max = Number((cycle as unknown as { form_config?: { max_preferences?: number } }).form_config?.max_preferences ?? 5);
  const offered = cycle.programs.filter((p) => a.entry_type !== 'lateral' || p.lateral_intake > 0);
  const move = (i: number, d: number) => setOrder((o) => { const n = [...o]; [n[i], n[i + d]] = [n[i + d], n[i]]; return n; });
  const name = (id: string) => cycle.programs.find((p) => p.program_id === id);
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">Order matters: seats are allotted in your preference order (up to {max}).</p>
      <ol className="space-y-2">
        {order.map((id, i) => {
          const p = name(id);
          const e = elig.data?.data.find((x) => x.program_code === p?.code);
          return (
            <li key={id} className="flex items-center gap-2 rounded-md border p-2 text-sm">
              <span className="w-6 font-semibold">{i + 1}</span>
              <span className="flex-1">{p?.code} — {p?.name} {e && (e.eligible ? <Badge variant="success">eligible</Badge> : <Badge variant="warning" title={e.reasons.join('; ')}>{e.reasons.join('; ')}</Badge>)}</span>
              <Button size="sm" variant="ghost" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp className="h-4 w-4" /></Button>
              <Button size="sm" variant="ghost" aria-label="Move down" disabled={i === order.length - 1} onClick={() => move(i, 1)}><ArrowDown className="h-4 w-4" /></Button>
              <Button size="sm" variant="ghost" onClick={() => setOrder((o) => o.filter((x) => x !== id))}>Remove</Button>
            </li>
          );
        })}
      </ol>
      <Select aria-label="Add a programme" placeholder="Add a programme…" value="" options={offered.filter((p) => !order.includes(p.program_id)).map((p) => ({ value: p.program_id, label: `${p.code} — ${p.name}` }))} disabled={order.length >= max} onChange={(e) => e.target.value && setOrder((o) => [...o, e.target.value])} />
      <Button disabled={!order.length || save.isPending} onClick={async () => { try { await save.mutateAsync(undefined); next(); } catch (e) { toast.error(getApiError(e)); } }}>Save &amp; continue</Button>
    </div>
  );
}

function DocumentsStep({ a, cycle, next }: { a: Applicant; cycle: PublicCycle; next: () => void }) {
  const up = useAdmissionsMutation((v: { t: string; f: File }) => admissionsApi.myDocument(v.t, v.f));
  const docs = cycle.required_documents.filter((d) => !d.entry_types || d.entry_types.includes(a.entry_type));
  return (
    <div className="space-y-2">
      {docs.map((d) => {
        const have = a.documents.find((x) => x.doc_type === d.doc_type);
        return (
          <div key={d.doc_type} className="flex flex-wrap items-center gap-2 rounded-md border p-2 text-sm">
            <span className="flex-1">{d.label ?? label(d.doc_type)} {d.required !== false && <span className="text-destructive">*</span>}</span>
            {have ? <StatusBadge status={have.status} /> : <Badge variant="outline">not uploaded</Badge>}
            {have?.remarks && <span className="text-xs text-amber-700">{have.remarks}</span>}
            {have?.status !== 'verified' && (
              <Input type="file" accept="image/*,application/pdf" capture="environment" aria-label={`Upload ${d.doc_type}`} className="w-60" onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; try { await up.mutateAsync({ t: d.doc_type, f }); toast.success('Uploaded'); } catch (err) { toast.error(getApiError(err)); } }} />
            )}
          </div>
        );
      })}
      <Button onClick={next}>Continue</Button>
    </div>
  );
}

function ReviewStep({ a, cycle, next }: { a: Applicant; cycle: PublicCycle; next: () => void }) {
  const submit = useAdmissionsMutation(() => admissionsApi.submit());
  const [problems, setProblems] = useState<string[]>([]);
  const go = async () => {
    try {
      await submit.mutateAsync(undefined);
      toast.success('Application submitted');
      next();
    } catch (e) {
      const err = e as { response?: { data?: { error?: { details?: { missing?: string[]; missing_fields?: string[]; preferences?: { program_code: string; reasons: string[] }[] } } } } };
      const d = err.response?.data?.error?.details;
      setProblems([...(d?.missing_fields ?? []).map((x) => `Missing: ${label(x)}`), ...(d?.missing ?? []).map((x) => `Document: ${label(x)}`), ...(d?.preferences ?? []).map((p) => `${p.program_code}: ${p.reasons.join('; ')}`)]);
      toast.error(getApiError(e));
    }
  };
  return (
    <div className="space-y-3 text-sm">
      <p><b>{a.name}</b> · {a.application_number} · {a.category} · DOB {a.dob}</p>
      <p>Preferences: {a.preferences.map((p) => p.program_code).join(' › ') || '—'}</p>
      <p>Documents: {a.documents.length} uploaded{a.missing_documents.length ? ` · missing ${a.missing_documents.map(label).join(', ')}` : ''}</p>
      <p>Application fee: {rupees(cycle.application_fee_paise)}</p>
      {problems.length > 0 && <ul className="list-disc pl-5 text-destructive">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      {a.status === 'draft' ? <Button disabled={submit.isPending} onClick={go}>Submit application</Button> : <Button onClick={next}>Continue</Button>}
    </div>
  );
}

function PayStep({ a }: { a: Applicant }) {
  const navigate = useNavigate();
  const pay = useAdmissionsMutation(() => admissionsApi.pay('application'));
  const p = a.payments.application;
  if (!p) return <p className="text-sm">Submit the application first.</p>;
  return (
    <div className="space-y-3 text-sm">
      <p>Application fee {rupees(p.amount_paise)} — <StatusBadge status={p.status} /></p>
      {p.status !== 'paid' ? (
        <Button disabled={pay.isPending} onClick={async () => { try { await pay.mutateAsync(undefined); toast.success('Payment received (test mode)'); } catch (e) { toast.error(getApiError(e)); } }}>Pay {rupees(p.amount_paise)} (test gateway)</Button>
      ) : (
        <Button onClick={() => navigate('/apply')}><Check className="h-4 w-4" /> Done — track your application</Button>
      )}
    </div>
  );
}

/** Public /apply/:cycle — multi-step application: account (OTP) → personal → qualifications → preferences →
 * documents → review → pay → done. Works on a phone (single column, camera capture for documents). */
export default function ApplyPage() {
  const { cycle: slug } = useParams();
  const institution = useInstitutionSlug();
  const user = useAuthStore((s) => s.currentUser);
  const isApplicant = !!user?.role_slugs.includes('applicant');
  const cycle = useQuery({ queryKey: ['public-cycle', institution, slug], queryFn: () => admissionsApi.publicCycle(institution, slug!), retry: false });
  const me = useMyApplication(isApplicant);
  const [step, setStep] = useState<Step>('personal');
  useEffect(() => {
    document.title = cycle.data ? `Apply — ${cycle.data.data.name}` : 'Apply';
  }, [cycle.data]);
  useEffect(() => {
    if (me.data && me.data.data.status !== 'draft' && step === 'personal') setStep('pay');
  }, [me.data, step]);
  const c = cycle.data?.data;
  if (cycle.isError) return <main className="p-6 text-sm">{getApiError(cycle.error)}</main>;
  if (!c) return <main className="p-6 text-sm text-muted-foreground">Loading…</main>;
  const a = me.data?.data;
  const next = () => setStep(STEPS[Math.min(STEPS.indexOf(step) + 1, STEPS.length - 1)]);
  return (
    <main className="mx-auto max-w-3xl space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-semibold">{c.name}</h1>
        <p className="text-sm text-muted-foreground">{c.institution.name} · {c.is_open ? `apply by ${c.closes_at ? new Date(c.closes_at).toLocaleDateString() : '—'}` : 'applications closed'}</p>
      </div>
      {!isApplicant || !a ? (
        c.is_open ? <AccountStep cycle={c} institution={institution} /> : <p className="text-sm">Applications are closed. <Link className="underline" to="/apply">Track an application</Link></p>
      ) : (
        <>
          <div className="flex flex-wrap gap-1 text-xs">
            {STEPS.map((s, i) => (
              <button key={s} type="button" onClick={() => setStep(s)} className={`rounded-full border px-2.5 py-1 ${s === step ? 'border-primary bg-primary text-primary-foreground' : ''}`}>{i + 1}. {label(s)}</button>
            ))}
          </div>
          <Card>
            <CardHeader><CardTitle className="flex items-center justify-between text-base">{label(step)} <span className="font-mono text-xs">{a.application_number}</span></CardTitle></CardHeader>
            <CardContent>
              {a.status !== 'draft' && a.status !== 'doc_rejected' && step !== 'pay' && step !== 'documents' ? (
                <p className="text-sm">Your application is <StatusBadge status={a.status} />. <Link className="underline" to="/apply">Track it here</Link>.</p>
              ) : (
                <>
                  {step === 'personal' && <PersonalStep a={a} cycle={c} next={next} />}
                  {step === 'qualifications' && <QualificationsStep a={a} next={next} />}
                  {step === 'preferences' && <PreferencesStep a={a} cycle={c} next={next} />}
                  {step === 'documents' && <DocumentsStep a={a} cycle={c} next={next} />}
                  {step === 'review' && <ReviewStep a={a} cycle={c} next={next} />}
                  {step === 'pay' && <PayStep a={a} />}
                </>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </main>
  );
}
