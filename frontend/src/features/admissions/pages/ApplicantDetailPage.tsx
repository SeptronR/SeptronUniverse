import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { academicsApi } from '@/features/academics/api';
import { SimpleTable } from '@/features/hr/components/shared';
import { admissionsApi } from '../api';
import { DocumentReview } from '../components/workspace';
import { useAdmissionsMutation, useApplicant, useApplicantTimeline } from '../hooks';
import { label, rupees, type Offer, type TimelineEntry } from '../types';

export function Timeline({ entries }: { entries: TimelineEntry[] }) {
  return (
    <ol className="space-y-2 border-l pl-4">
      {entries.map((t, i) => (
        <li key={i} className="text-sm">
          <span className="text-xs text-muted-foreground">{new Date(t.at).toLocaleString()}</span>{' '}
          <span className="font-medium">{t.status_to ? label(t.status_to) : label(t.action)}</span>
          {t.by && <span className="text-muted-foreground"> · {t.by}</span>}
          {t.remarks && <div className="text-xs text-muted-foreground">{t.remarks}</div>}
        </li>
      ))}
      {!entries.length && <li className="text-sm text-muted-foreground">No events yet.</li>}
    </ol>
  );
}

/** /admin/admissions/applicants/:id — profile, preferences, documents, timeline; status change, offer, admit. */
export default function ApplicantDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { can } = usePermission();
  const q = useApplicant(id);
  const tl = useApplicantTimeline(id);
  const offersOn = useFeature('admissions.offers');
  const [dialog, setDialog] = useState<'status' | 'offer' | 'admit' | null>(null);
  const [st, setSt] = useState({ status: '', reason: '' });
  const [offer, setOffer] = useState<Offer | null>(null);
  const [offerType, setOfferType] = useState('provisional');
  const [section, setSection] = useState('');
  const a = q.data?.data;
  const sections = useQuery({
    queryKey: ['batch-sections-for', a?.allotment?.program_id],
    queryFn: () => academicsApi.batches({ program_id: a!.allotment!.program_id, page_size: 50 }),
    enabled: dialog === 'admit' && !!a?.allotment,
  });
  const changeStatus = useAdmissionsMutation(() => admissionsApi.changeStatus(id!, st.status, st.reason));
  const issue = useAdmissionsMutation(() => admissionsApi.offer(id!, { offer_type: offerType }));
  const admit = useAdmissionsMutation(() => admissionsApi.admit(id!, { section_id: section || undefined }));
  useEffect(() => {
    document.title = a ? `${a.application_number} — applicant` : 'Applicant';
  }, [a]);
  if (!a) return <p className="text-sm text-muted-foreground">{q.isError ? getApiError(q.error) : 'Loading…'}</p>;
  const manage = can('admissions', 'manage');
  const run = async (p: Promise<unknown>, msg: string) => {
    try {
      await p;
      toast.success(msg);
      return true;
    } catch (e) {
      toast.error(getApiError(e));
      return false;
    }
  };
  return (
    <div className="space-y-4">
      <PageHeader
        title={`${a.name} · ${a.application_number}`}
        description={`${a.cycle_name ?? ''} · ${label(a.entry_type)} entry · source ${label(a.source)}`}
        breadcrumbs={[{ label: 'Applicants', to: '/admin/admissions/applicants' }, { label: a.application_number }]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={a.status} />
            {manage && a.allowed_transitions.length > 0 && <Button size="sm" variant="outline" onClick={() => setDialog('status')}>Change status</Button>}
            {manage && offersOn && <Button size="sm" variant="outline" onClick={() => setDialog('offer')}>Offer</Button>}
            {can('admissions', 'admit') && ['accepted', 'provisionally_admitted', 'verified'].includes(a.status) && (
              <Button size="sm" onClick={() => setDialog('admit')}>Admit</Button>
            )}
            {a.admitted_student_id && <Button size="sm" variant="outline" onClick={() => navigate(`/admin/students/${a.admitted_student_id}`)}>Student record</Button>}
          </div>
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle className="text-base">Application</CardTitle></CardHeader>
          <CardContent className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            <div>DOB: {a.dob ?? '—'} · Gender: {a.gender ?? '—'}</div>
            <div>Category: {a.category ?? '—'} {a.is_pwd && <Badge variant="outline">PwD</Badge>} · Quota: {a.quota_claimed ?? '—'}</div>
            <div>Phone: {a.phone ?? '—'}</div>
            <div>E-mail: {a.email ?? '—'}</div>
            <div>Guardian: {a.contact?.guardian_name ?? '—'} {a.contact?.guardian_phone ? `(${a.contact.guardian_phone})` : ''}</div>
            <div>Entrance: {a.entrance ? `${String(a.entrance.exam ?? '')} ${String(a.entrance.score ?? '')}` : '—'} · Merit score {a.merit_score ?? '—'}</div>
            <div className="sm:col-span-2">Qualifying: {(a.qualifying_exams ?? []).map((e) => `${e.level ?? ''} ${e.pct ?? ''}%`).join(', ') || '—'}</div>
            <div className="sm:col-span-2">
              <SimpleTable head={['#', 'Programme']} rows={a.preferences.map((p) => [p.priority, `${p.program_code} — ${p.program_name}`])} empty="No preferences." />
            </div>
            <div className="sm:col-span-2 text-xs text-muted-foreground">
              Payments: {Object.entries(a.payments).map(([k, p]) => `${label(k)} ${rupees(p.amount_paise)} ${p.status}`).join(' · ') || 'none'}
            </div>
            {a.allotment && (
              <div className="sm:col-span-2 rounded-md border p-2">
                Allotment (round {a.allotment.round_number}): <b>{a.allotment.program_code}</b> · {a.allotment.quota} / {a.allotment.category} · <StatusBadge status={a.allotment.status} />
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-base">Timeline</CardTitle></CardHeader>
          <CardContent><Timeline entries={tl.data?.data ?? []} /></CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader><CardTitle className="text-base">Documents</CardTitle></CardHeader>
        <CardContent><DocumentReview applicant={a} canVerify={can('admissions', 'verify')} /></CardContent>
      </Card>

      <Modal open={dialog === 'status'} onOpenChange={(o) => setDialog(o ? 'status' : null)} title="Change status"
        footer={<Button disabled={!st.status || st.reason.length < 3} onClick={async () => { if (await run(changeStatus.mutateAsync(undefined), 'Status changed')) setDialog(null); }}>Save</Button>}>
        <div className="space-y-3">
          <Select aria-label="New status" placeholder="Select…" options={a.allowed_transitions.filter((s) => s !== 'admitted').map((s) => ({ value: s, label: label(s) }))} value={st.status} onChange={(e) => setSt((x) => ({ ...x, status: e.target.value }))} />
          <Textarea rows={3} placeholder="Reason (required)" value={st.reason} onChange={(e) => setSt((x) => ({ ...x, reason: e.target.value }))} />
        </div>
      </Modal>
      <Modal open={dialog === 'offer'} onOpenChange={(o) => { setDialog(o ? 'offer' : null); setOffer(null); }} title="Offer letter" size="lg"
        footer={!offer && <Button onClick={async () => { try { const r = await issue.mutateAsync(undefined); setOffer(r.data); toast.success('Offer issued'); } catch (e) { toast.error(getApiError(e)); } }}>Issue offer</Button>}>
        {offer ? (
          // Offer letters are generated server-side from plain fields (escaped names) — rendered as text blocks here
          <div className="space-y-2 rounded-md border p-4 text-sm">
            <h3 className="font-semibold">{label(offer.offer_type)} offer of admission</h3>
            <p>Dear {offer.applicant_name}, you are offered admission to {offer.program_code} under application {offer.application_number}.</p>
            <p>Valid until {offer.valid_until}.</p>
          </div>
        ) : (
          <div className="space-y-3">
            <Select aria-label="Offer type" options={[{ value: 'provisional', label: 'Provisional' }, { value: 'confirmed', label: 'Confirmed' }]} value={offerType} onChange={(e) => setOfferType(e.target.value)} />
            <p className="text-sm text-muted-foreground">The offer is for the held allotment's programme (else the first preference); a previous open offer is withdrawn.</p>
          </div>
        )}
      </Modal>
      <Modal open={dialog === 'admit'} onOpenChange={(o) => setDialog(o ? 'admit' : null)} title="Admit applicant"
        description="Creates the student, enrolment, registration number and student / guardian accounts."
        footer={<Button disabled={admit.isPending} onClick={async () => { try { const r = await admit.mutateAsync(undefined); toast.success(`Admitted — ${r.data.registration_number}`); navigate(`/admin/students/${r.data.student_id}`); } catch (e) { toast.error(getApiError(e)); } }}>Admit</Button>}>
        <div className="space-y-3">
          <p className="text-sm">Programme: <b>{a.allotment?.program_code ?? a.preferences[0]?.program_code}</b></p>
          <label className="text-sm font-medium" htmlFor="sec">Section</label>
          <Select
            id="sec"
            placeholder="Least-filled section (default)"
            options={(sections.data?.data ?? [])
              .filter((b) => b.entry_type === (a.entry_type === 'lateral' ? 'lateral' : 'regular'))
              .flatMap((b) => b.sections.map((x) => ({ value: x.id, label: `${b.code} · ${x.name}` })))}
            value={section}
            onChange={(e) => setSection(e.target.value)}
          />
        </div>
      </Modal>
    </div>
  );
}
