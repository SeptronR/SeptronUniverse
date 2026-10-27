import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Ban, CreditCard, FileUp, RefreshCw, Send } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { EmptyState } from '@/components/shared/EmptyState';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Avatar } from '@/components/ui/Avatar';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { Switch } from '@/components/ui/Switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { downloadBlob } from '@/features/hr/download';
import { SimpleTable, WorkflowPanel } from '@/features/hr/components/shared';
import { formatDate, formatDateTime } from '@/utils/formatters';
import { studentsApi } from '../api';
import { AuditTrailButton } from '@/components/shared/AuditTrailButton';
import { Field, HoldBanner, HoldsBadge, StandingChip } from '../components/shared';
import { useStudent, useStudentMutation } from '../hooks';
import { HOLD_TYPES, TRANSFER_TYPES, addressLine, label, type StudentDetail } from '../types';

const LATER = [
  ['attendance', 'Attendance', 'Phase 10'],
  ['marks', 'Marks', 'Phase 14'],
  ['fees', 'Fees', 'Phase 17'],
  ['hostel', 'Hostel', 'Phase 20'],
  ['library', 'Library', 'Phase 21'],
] as const;

function Profile({ s }: { s: StudentDetail }) {
  return (
    <dl className="grid gap-3 sm:grid-cols-3">
      <Field k="Registration no." v={<span className="font-mono">{s.registration_number}</span>} />
      <Field k="Enrolment no." v={s.enrolment_number} />
      <Field k="Username" v={s.username} />
      <Field k="Date of birth" v={s.dob ? `${formatDate(s.dob)}${s.is_adult ? '' : ' (minor)'}` : null} />
      <Field k="Gender" v={s.gender} />
      <Field k="Blood group" v={s.blood_group} />
      <Field k="Category" v={[s.category, s.sub_category].filter(Boolean).join(' / ')} />
      <Field k="PwD" v={s.is_pwd ? `Yes${s.pwd_pct ? ` (${s.pwd_pct}%)` : ''}` : 'No'} />
      <Field k="Nationality" v={s.nationality} />
      <Field k="Phone" v={s.phone} />
      <Field k="E-mail" v={s.email} />
      <Field k="Aadhaar" v={s.aadhaar} />
      <Field k="APAAR" v={s.apaar_id} />
      <Field k="ABC id" v={s.abc_id} />
      <Field k="Bank details" v={s.bank_details} />
      <Field k="Admission" v={[s.admission_date && formatDate(s.admission_date), s.admission_quota, s.admission_mode].filter(Boolean).join(' · ')} />
      <Field k="Permanent address" v={addressLine(s.permanent_address)} />
      <Field k="Current address" v={addressLine(s.current_address)} />
      <Field k="Emergency contact" v={s.emergency_contact ? `${s.emergency_contact.name ?? ''} ${s.emergency_contact.phone ?? ''}` : null} />
    </dl>
  );
}

/** /admin/students/:id — 360°: header (photo, reg no, status, standing, holds) + tabs; status dialog offers only the
 *  allowed transitions; holds, guardians consent, documents, transfers and credit transfers act in place. */
export default function StudentDetailPage() {
  const { id = '' } = useParams();
  const { can } = usePermission();
  const student = useStudent(id);
  const [tab, setTab] = useState('profile');
  const [statusOpen, setStatusOpen] = useState(false);
  const [statusForm, setStatusForm] = useState({ status: '', reason: '' });
  const [holdOpen, setHoldOpen] = useState(false);
  const [holdForm, setHoldForm] = useState({ hold_type: 'registration', reason: '' });
  const [release, setRelease] = useState<{ id: string; reason: string } | null>(null);
  const [transferOpen, setTransferOpen] = useState(false);
  const [transferForm, setTransferForm] = useState({ transfer_type: 'migration_out', reason: '', to: '' });
  const [doc, setDoc] = useState<{ doc_type: string; expires_on: string; file: File | null }>({ doc_type: '', expires_on: '', file: null });
  const holdsOn = useFeature('students.holds');
  const transfersOn = useFeature('students.transfers_migration');
  const ctOn = useFeature('academics.credit_transfer_mooc');
  const standingOn = useFeature('students.academic_standing');
  const enrol = useQuery({ queryKey: ['students', id, 'enrollments'], queryFn: () => studentsApi.enrollments(id), enabled: tab === 'enrolment' });
  const enrolmentId = student.data?.data.enrollment?.id;
  const terms = useQuery({ queryKey: ['students', id, 'terms', enrolmentId], queryFn: () => studentsApi.termRecords(enrolmentId!), enabled: tab === 'enrolment' && !!enrolmentId });
  const standing = useQuery({ queryKey: ['students', id, 'standing'], queryFn: () => studentsApi.standing(id), enabled: tab === 'enrolment' && standingOn, retry: false });
  const holds = useQuery({ queryKey: ['student-holds', 'of', id], queryFn: () => studentsApi.holds(id), enabled: tab === 'holds' });
  const transfers = useQuery({ queryKey: ['student-transfers', 'of', id], queryFn: () => studentsApi.transfers(id), enabled: tab === 'transfers' });
  const cts = useQuery({ queryKey: ['credit-transfers', 'of', id], queryFn: () => studentsApi.studentCreditTransfers(id), enabled: tab === 'ct' });
  const roots = ['students', 'student-holds', 'student-transfers', 'credit-transfers'];
  const changeStatus = useStudentMutation(() => studentsApi.changeStatus(id, statusForm), roots);
  const placeHold = useStudentMutation(() => studentsApi.placeHold(id, holdForm), roots);
  const releaseHold = useStudentMutation((r: { id: string; reason: string }) => studentsApi.releaseHold(r.id, r.reason), roots);
  const consent = useStudentMutation((c: boolean) => studentsApi.guardianConsent(id, c), roots);
  const verifyDoc = useStudentMutation((docId: string) => studentsApi.verifyDocument(docId), roots);
  const addDoc = useStudentMutation(() => studentsApi.addDocument(id, doc.file!, { doc_type: doc.doc_type, expires_on: doc.expires_on || undefined }), roots);
  const requestTransfer = useStudentMutation(
    () => studentsApi.requestTransfer(id, { transfer_type: transferForm.transfer_type, reason: transferForm.reason, to_ref: transferForm.to ? { name: transferForm.to } : undefined }),
    roots,
  );
  const transferAction = useStudentMutation((a: { id: string; action: 'approve' | 'reject' | 'complete' }) => studentsApi.transferAction(a.id, a.action), roots);
  const done = (msg: string, after?: () => void) => ({ onSuccess: () => { toast.success(msg); after?.(); }, onError: (e: unknown) => toast.error(getApiError(e)) });

  if (student.isLoading || !student.data) return student.error ? <EmptyState title="Student not found" description={getApiError(student.error)} /> : <PageSkeleton />;
  const s = student.data.data;
  const e = s.enrollment;
  const idCard = async () => {
    try {
      downloadBlob(await studentsApi.idCardPdf(id), `${s.registration_number}-id-card.pdf`, true);
    } catch (err) {
      toast.error(getApiError(err));
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title={s.full_name}
        breadcrumbs={[{ label: 'Students', to: '/admin/students' }, { label: s.registration_number }]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <AuditTrailButton recordType="student" recordId={s.id} />
            {can('students', 'id_card') && <Button variant="outline" onClick={idCard}><CreditCard className="h-4 w-4" /> ID card</Button>}
            {holdsOn && (can('students', 'holds') || can('library', 'manage') || can('hostel', 'manage')) && (
              <Button variant="outline" onClick={() => setHoldOpen(true)}><Ban className="h-4 w-4" /> Place hold</Button>
            )}
            {can('students', 'update') && s.allowed_transitions.length > 0 && (
              <Button onClick={() => { setStatusForm({ status: s.allowed_transitions[0], reason: '' }); setStatusOpen(true); }}><RefreshCw className="h-4 w-4" /> Change status</Button>
            )}
          </div>
        }
      />
      <Card>
        <CardContent className="flex flex-wrap items-center gap-4 pt-4 sm:pt-4">
          <Avatar name={s.full_name} src={s.photo_url} size="lg" />
          <div className="min-w-0 flex-1 space-y-1">
            <p className="font-mono text-sm">{s.registration_number}</p>
            <p className="text-sm text-muted-foreground">
              {e ? `${e.program_code} · ${e.batch_code}${e.section_name ? ` · section ${e.section_name}` : ''} · term ${e.current_term_number ?? '—'} · ${e.regulation_code ?? ''}` : 'No open enrolment'}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={s.status} />
              <StandingChip standing={s.academic_standing} />
              <HoldsBadge count={s.open_holds} />
              {e && <span className="text-xs text-muted-foreground">CGPA {e.cgpa ?? '—'} · {e.credits_earned} credits</span>}
            </div>
          </div>
        </CardContent>
      </Card>
      <HoldBanner holds={s.holds} />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="guardians">Guardians</TabsTrigger>
          <TabsTrigger value="documents">Documents</TabsTrigger>
          <TabsTrigger value="undertakings">Undertakings</TabsTrigger>
          <TabsTrigger value="enrolment">Enrolment &amp; terms</TabsTrigger>
          {holdsOn && <TabsTrigger value="holds">Holds</TabsTrigger>}
          {transfersOn && <TabsTrigger value="transfers">Transfers</TabsTrigger>}
          {ctOn && <TabsTrigger value="ct">Credit transfers</TabsTrigger>}
          {LATER.map(([k, l]) => <TabsTrigger key={k} value={k}>{l}</TabsTrigger>)}
        </TabsList>
        <Card className="mt-3">
          <CardContent className="pt-4 sm:pt-4">
            <TabsContent value="profile"><Profile s={s} /></TabsContent>
            <TabsContent value="guardians">
              <div className="mb-3 flex items-center gap-2 text-sm">
                <Switch
                  aria-label="Guardian portal consent"
                  checked={s.guardian_portal_consent}
                  disabled={!can('students', 'update') || consent.isPending}
                  onCheckedChange={(c) => consent.mutate(c, done(c ? 'Guardians can see this student' : 'Guardian portal access withdrawn'))}
                />
                Guardians may view this student in the parent portal {s.is_adult && <span className="text-muted-foreground">(adult — the student decides)</span>}
              </div>
              <SimpleTable
                head={['Relation', 'Name', 'Phone', 'E-mail', 'Portal user', '']}
                rows={s.guardians.map((g) => [label(g.relation), g.name, g.phone ?? '—', g.email ?? '—', g.username ?? (g.portal_access ? 'pending' : 'no'), g.is_primary ? 'primary' : ''])}
                empty="No guardians recorded."
              />
            </TabsContent>
            <TabsContent value="documents">
              <SimpleTable
                head={['Type', 'File', 'Uploaded', 'Expires', 'Verified', '']}
                rows={s.documents.map((d) => [
                  d.doc_type,
                  <a key="f" className="text-primary underline" href={d.file_url} target="_blank" rel="noreferrer">open</a>,
                  formatDate(d.uploaded_at),
                  d.expires_on ? <span key="x" className={d.is_expired ? 'text-destructive' : ''}>{formatDate(d.expires_on)}</span> : '—',
                  d.is_verified ? `yes · ${formatDate(d.verified_at)}` : 'no',
                  !d.is_verified && can('students', 'update') ? <Button key="v" size="sm" variant="outline" onClick={() => verifyDoc.mutate(d.id, done('Document verified'))}>Verify</Button> : null,
                ])}
                empty="No documents."
              />
              {can('students', 'update') && (
                <div className="mt-3 flex flex-wrap items-end gap-2">
                  <FormField label="Type" placeholder="e.g. tc" value={doc.doc_type} onChange={(ev) => setDoc({ ...doc, doc_type: ev.target.value })} />
                  <FormField label="Expires on" type="date" value={doc.expires_on} onChange={(ev) => setDoc({ ...doc, expires_on: ev.target.value })} />
                  <input type="file" aria-label="Document file" accept=".pdf,image/*" onChange={(ev) => setDoc({ ...doc, file: ev.target.files?.[0] ?? null })} />
                  <Button disabled={!doc.doc_type || !doc.file} loading={addDoc.isPending} onClick={() => addDoc.mutate(undefined, done('Document uploaded', () => setDoc({ doc_type: '', expires_on: '', file: null })))}>
                    <FileUp className="h-4 w-4" /> Upload
                  </Button>
                </div>
              )}
            </TabsContent>
            <TabsContent value="undertakings">
              <SimpleTable
                head={['Undertaking', 'Required', 'Accepted']}
                rows={s.undertakings.map((u) => [u.name, u.required ? 'yes' : 'no', u.accepted ? formatDateTime(u.accepted_at) : <span key="p" className="text-status-pending">pending</span>])}
              />
            </TabsContent>
            <TabsContent value="enrolment">
              <SimpleTable
                head={['Programme', 'Batch', 'Regulation', 'Entry', 'Status', 'Credits', 'CGPA']}
                rows={(enrol.data?.data ?? []).map((x) => [x.program_code, x.batch_code, x.regulation_code, `${label(x.entry_type)} @ term ${x.entry_term_number}`, <StatusBadge key="s" status={x.status} />, x.credits_earned, x.cgpa ?? '—'])}
              />
              <h3 className="mb-2 mt-4 text-sm font-semibold">Term records</h3>
              <SimpleTable
                head={['Term', 'Academic year', 'Section', 'Status', 'Registered', 'Earned', 'SGPA', 'CGPA']}
                rows={(terms.data?.data ?? []).map((t) => [t.term_number, t.academic_year_name ?? '—', t.section_name ?? '—', <StatusBadge key="s" status={t.status} />, t.credits_registered, t.credits_earned, t.sgpa ?? '—', t.cgpa ?? '—'])}
              />
              {standing.data && (
                <>
                  <h3 className="mb-2 mt-4 text-sm font-semibold">Standing history</h3>
                  <SimpleTable
                    head={['When', 'From', 'To', 'CGPA', 'Term']}
                    rows={standing.data.data.history.map((h) => [formatDateTime(h.at), label(h.from_standing), <StandingChip key="t" standing={h.to_standing} />, h.cgpa ?? '—', h.term_number ?? '—'])}
                    empty="No standing changes."
                  />
                </>
              )}
            </TabsContent>
            <TabsContent value="holds">
              <SimpleTable
                head={['Type', 'Reason', 'Placed', 'Released', '']}
                rows={(holds.data?.data ?? []).map((h) => [
                  label(h.hold_type),
                  h.reason,
                  `${formatDateTime(h.placed_at)} · ${h.placed_by_name ?? ''}`,
                  h.released_at ? `${formatDateTime(h.released_at)} · ${h.release_reason ?? ''}` : '—',
                  h.is_open && h.can_release ? <Button key="r" size="sm" variant="outline" onClick={() => setRelease({ id: h.id, reason: '' })}>Release</Button> : null,
                ])}
                empty="No holds."
              />
            </TabsContent>
            <TabsContent value="transfers">
              {can('students', 'transfer') && (
                <Button className="mb-3" variant="outline" onClick={() => setTransferOpen(true)}><Send className="h-4 w-4" /> Request transfer</Button>
              )}
              <SimpleTable
                head={['Type', 'Requested', 'Status', 'TC / migration no.', '']}
                rows={(transfers.data?.data ?? []).map((t) => [
                  label(t.transfer_type),
                  formatDate(t.requested_at),
                  <StatusBadge key="s" status={t.status} />,
                  [t.tc_no, t.migration_certificate_no].filter(Boolean).join(' · ') || '—',
                  <div key="a" className="flex gap-1">
                    {t.can_act && <Button size="sm" onClick={() => transferAction.mutate({ id: t.id, action: 'approve' }, done('Approved'))}>Approve</Button>}
                    {t.can_act && <Button size="sm" variant="outline" onClick={() => transferAction.mutate({ id: t.id, action: 'reject' }, done('Rejected'))}>Reject</Button>}
                    {t.status === 'approved' && can('students', 'transfer') && <Button size="sm" onClick={() => transferAction.mutate({ id: t.id, action: 'complete' }, done('Transfer completed'))}>Complete</Button>}
                  </div>,
                ])}
                empty="No transfer requests."
              />
              {(transfers.data?.data ?? [])[0]?.workflow_instance_id && (
                <div className="mt-3"><WorkflowPanel instanceId={transfers.data!.data[0].workflow_instance_id} /></div>
              )}
            </TabsContent>
            <TabsContent value="ct">
              <SimpleTable
                head={['Source', 'Course', 'Credits', 'Grade', 'Equivalent', 'Status']}
                rows={(cts.data?.data ?? []).map((c) => [label(c.source), `${c.source_course_code ?? ''} ${c.source_title}`, c.credits, c.letter_grade ?? c.source_grade ?? '—', c.equivalent_course ?? '—', <StatusBadge key="s" status={c.status} />])}
                empty="No credit transfers."
              />
            </TabsContent>
            {LATER.map(([k, l, phase]) => (
              <TabsContent key={k} value={k}>
                <EmptyState title={`${l} — coming with ${phase}`} description="This tab fills in when the module is installed." />
              </TabsContent>
            ))}
          </CardContent>
        </Card>
      </Tabs>

      <Modal
        open={statusOpen}
        onOpenChange={setStatusOpen}
        title="Change status"
        description={`Current: ${label(s.status)}. Only the transitions allowed from this status are offered; terminal statuses deactivate the account.`}
        footer={<Button loading={changeStatus.isPending} disabled={statusForm.reason.trim().length < 3} onClick={() => changeStatus.mutate(undefined, done('Status changed', () => setStatusOpen(false)))}>Change</Button>}
      >
        <div className="space-y-3">
          <Select aria-label="New status" options={s.allowed_transitions.map((t) => ({ value: t, label: label(t) }))} value={statusForm.status} onChange={(ev) => setStatusForm({ ...statusForm, status: ev.target.value })} />
          <Textarea aria-label="Reason" placeholder="Reason (audited)" value={statusForm.reason} onChange={(ev) => setStatusForm({ ...statusForm, reason: ev.target.value })} />
        </div>
      </Modal>

      <Modal
        open={holdOpen}
        onOpenChange={setHoldOpen}
        title="Place a hold"
        description="Blocks the matching gate (registration, exams, transcript, …) until released. The student and guardians are notified."
        footer={<Button loading={placeHold.isPending} disabled={holdForm.reason.trim().length < 3} onClick={() => placeHold.mutate(undefined, done('Hold placed', () => { setHoldOpen(false); setHoldForm({ hold_type: 'registration', reason: '' }); }))}>Place hold</Button>}
      >
        <div className="space-y-3">
          <Select aria-label="Hold type" options={HOLD_TYPES.map((t) => ({ value: t, label: label(t) }))} value={holdForm.hold_type} onChange={(ev) => setHoldForm({ ...holdForm, hold_type: ev.target.value })} />
          <Textarea aria-label="Hold reason" placeholder="Reason shown to the student" value={holdForm.reason} onChange={(ev) => setHoldForm({ ...holdForm, reason: ev.target.value })} />
        </div>
      </Modal>

      <Modal
        open={release !== null}
        onOpenChange={(o) => !o && setRelease(null)}
        title="Release hold"
        footer={<Button loading={releaseHold.isPending} disabled={(release?.reason.trim().length ?? 0) < 3} onClick={() => release && releaseHold.mutate(release, done('Hold released', () => setRelease(null)))}>Release</Button>}
      >
        <Textarea aria-label="Release reason" placeholder="Why is it released?" value={release?.reason ?? ''} onChange={(ev) => release && setRelease({ ...release, reason: ev.target.value })} />
      </Modal>

      <Modal
        open={transferOpen}
        onOpenChange={setTransferOpen}
        title="Request transfer / migration"
        description="Starts the approval workflow (registrar → dues check → principal)."
        footer={<Button loading={requestTransfer.isPending} disabled={transferForm.reason.trim().length < 3} onClick={() => requestTransfer.mutate(undefined, done('Transfer requested', () => setTransferOpen(false)))}>Submit</Button>}
      >
        <div className="space-y-3">
          <Select aria-label="Transfer type" options={TRANSFER_TYPES.map((t) => ({ value: t, label: label(t) }))} value={transferForm.transfer_type} onChange={(ev) => setTransferForm({ ...transferForm, transfer_type: ev.target.value })} />
          <FormField label="Destination (institution / programme)" value={transferForm.to} onChange={(ev) => setTransferForm({ ...transferForm, to: ev.target.value })} />
          <Textarea aria-label="Transfer reason" placeholder="Reason" value={transferForm.reason} onChange={(ev) => setTransferForm({ ...transferForm, reason: ev.target.value })} />
        </div>
      </Modal>
    </div>
  );
}
