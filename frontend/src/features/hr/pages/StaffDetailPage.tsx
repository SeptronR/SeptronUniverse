import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { LogOut } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { hrApi } from '../api';
import { SimpleTable } from '../components/shared';
import { useHrMutation, useStaff } from '../hooks';
import { MONTHS, inr, label, num, type StaffDetail } from '../types';

const ENTRY_TYPES = ['joining', 'promotion', 'increment', 'transfer', 'award', 'disciplinary', 'leave_without_pay', 'exit'];

/** Bank details arrive as JSON text when unmasked (``********`` when masked). */
function bank(raw: string | null): string | null {
  if (!raw || raw.startsWith('*')) return raw;
  try {
    const b = JSON.parse(raw) as { account_no?: string; ifsc?: string; bank?: string };
    return [b.bank, b.account_no, b.ifsc].filter(Boolean).join(' · ');
  } catch {
    return raw;
  }
}

function Field({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{k}</dt>
      <dd className="break-words text-sm">{v ?? '—'}</dd>
    </div>
  );
}

function Profile({ s }: { s: StaffDetail }) {
  return (
    <dl className="grid gap-3 sm:grid-cols-3">
      <Field k="Employee id" v={s.employee_id} />
      <Field k="Username" v={s.username} />
      <Field k="Department" v={s.department_code} />
      <Field k="Designation" v={s.designation_name} />
      <Field k="Cadre" v={label(s.cadre)} />
      <Field k="Employment" v={label(s.employment_type)} />
      <Field k="Joined" v={s.joining_date} />
      <Field k="Phone" v={s.phone} />
      <Field k="E-mail" v={s.email} />
      <Field k="Date of birth" v={s.dob} />
      <Field k="PAN" v={s.pan} />
      <Field k="Aadhaar" v={s.aadhaar} />
      <Field k="Bank details" v={bank(s.bank_details)} />
      <Field k="UAN" v={s.uan} />
      <Field k="PF number" v={s.pf_number} />
      <Field k="Reports to" v={s.reports_to_name} />
      {s.hourly_rate_paise != null && <Field k="Hourly rate" v={inr(s.hourly_rate_paise)} />}
      {s.exit_date && <Field k="Exited" v={`${s.exit_date} — ${s.exit_reason ?? ''}`} />}
    </dl>
  );
}

/** /admin/hr/staff/:id — tabs Profile | Faculty profile | Qualifications | Documents | Service book | Leaves |
 *  Attendance | Payroll | Workload; exit dialog (hr:manage). */
export default function StaffDetailPage() {
  const { id = '' } = useParams();
  const { can } = usePermission();
  const staff = useStaff(id);
  const [tab, setTab] = useState('profile');
  const [exitOpen, setExitOpen] = useState(false);
  const [exitForm, setExitForm] = useState({ exit_date: '', exit_reason: '' });
  const [entry, setEntry] = useState({ entry_type: 'award', effective_date: '', note: '' });
  const profileOn = useFeature('hr.faculty_profiles');
  const sbOn = useFeature('hr.service_book');
  const fp = useQuery({ queryKey: ['staff', id, 'fp'], queryFn: () => hrApi.facultyProfile(id), enabled: tab === 'faculty' });
  const quals = useQuery({ queryKey: ['staff', id, 'quals'], queryFn: () => hrApi.qualifications(id), enabled: tab === 'quals' });
  const docs = useQuery({ queryKey: ['staff', id, 'docs'], queryFn: () => hrApi.documents(id), enabled: tab === 'docs' });
  const sb = useQuery({ queryKey: ['staff', id, 'sb'], queryFn: () => hrApi.serviceBook(id), enabled: tab === 'sb' });
  const leaves = useQuery({ queryKey: ['leaves', { staff_id: id }], queryFn: () => hrApi.leaves({ staff_id: id, scope: 'all', page_size: 50 }), enabled: tab === 'leaves' });
  const att = useQuery({ queryKey: ['staff-attendance', { staff_id: id }], queryFn: () => hrApi.summary({ staff_id: id, scope: 'all' }), enabled: tab === 'att' });
  const pay = useQuery({ queryKey: ['payroll', { staff_id: id }], queryFn: () => hrApi.payroll({ staff_id: id, scope: 'all', page_size: 24 }), enabled: tab === 'pay' });
  const structures = useQuery({ queryKey: ['payroll', 'structures', id], queryFn: () => hrApi.structures(id), enabled: tab === 'pay' && (can('payroll', 'manage') || can('payroll', 'view_all')) });
  const wl = useQuery({ queryKey: ['workload', id], queryFn: () => hrApi.myWorkload(id), enabled: tab === 'wl', retry: false });
  const exit = useHrMutation(() => hrApi.exitStaff(id, exitForm), ['staff']);
  const addEntry = useHrMutation(() => hrApi.addServiceEntry(id, { entry_type: entry.entry_type, effective_date: entry.effective_date, details: { note: entry.note } }), ['staff']);

  if (staff.isLoading || !staff.data) return <PageSkeleton />;
  const s = staff.data.data;
  return (
    <div className="space-y-4">
      <PageHeader
        title={s.full_name}
        description={`${s.employee_id} · ${s.designation_name ?? label(s.staff_category)} · ${s.department_code ?? 'office'}`}
        breadcrumbs={[{ label: 'Staff', to: '/admin/hr/staff' }, { label: s.employee_id }]}
        actions={
          <div className="flex items-center gap-2">
            <StatusBadge status={s.status} />
            {can('hr', 'manage') && s.status !== 'exited' && (
              <Button variant="destructive" onClick={() => setExitOpen(true)}>
                <LogOut className="h-4 w-4" /> Exit
              </Button>
            )}
          </div>
        }
      />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="profile">Profile</TabsTrigger>
          {profileOn && s.staff_category === 'teaching' && <TabsTrigger value="faculty">Faculty profile</TabsTrigger>}
          {profileOn && <TabsTrigger value="quals">Qualifications</TabsTrigger>}
          <TabsTrigger value="docs">Documents</TabsTrigger>
          {sbOn && <TabsTrigger value="sb">Service book</TabsTrigger>}
          <TabsTrigger value="leaves">Leaves</TabsTrigger>
          <TabsTrigger value="att">Attendance</TabsTrigger>
          <TabsTrigger value="pay">Payroll</TabsTrigger>
          {s.staff_category === 'teaching' && <TabsTrigger value="wl">Workload</TabsTrigger>}
        </TabsList>
        <Card className="mt-3">
          <CardContent className="pt-4">
            <TabsContent value="profile"><Profile s={s} /></TabsContent>
            <TabsContent value="faculty">
              {fp.data?.data ? (
                <dl className="grid gap-3 sm:grid-cols-3">
                  <Field k="Cadre" v={label(fp.data.data.cadre)} />
                  <Field k="Highest qualification" v={fp.data.data.highest_qualification} />
                  <Field k="PhD" v={fp.data.data.is_phd ? `Yes (${fp.data.data.phd_year ?? '—'})` : 'No'} />
                  <Field k="PhD guide" v={fp.data.data.is_phd_guide ? `Yes · ${fp.data.data.guide_recognition_no}` : 'No'} />
                  <Field k="Max scholars" v={fp.data.data.max_scholars} />
                  <Field k="ORCID" v={fp.data.data.orcid} />
                  <Field k="Scopus" v={fp.data.data.scopus_id} />
                  <Field k="AICTE id" v={fp.data.data.aicte_faculty_id} />
                  <Field k="Teaching experience" v={`${fp.data.data.experience_teaching_months} months`} />
                </dl>
              ) : (
                <p className="text-sm text-muted-foreground">No faculty profile.</p>
              )}
            </TabsContent>
            <TabsContent value="quals">
              <SimpleTable head={['Degree', 'Discipline', 'University', 'Year', '']} rows={(quals.data?.data ?? []).map((q) => [q.degree, q.discipline, q.university, q.year, q.is_highest ? 'highest' : ''])} />
            </TabsContent>
            <TabsContent value="docs">
              <SimpleTable head={['Type', 'File', 'Expires', 'Verified']} rows={(docs.data?.data ?? []).map((d) => [d.doc_type, <a key={d.id} className="text-primary underline" href={d.file_url} target="_blank" rel="noreferrer">open</a>, d.expires_on ?? '—', d.verified_at ? 'yes' : 'no'])} />
            </TabsContent>
            <TabsContent value="sb">
              <SimpleTable head={['Date', 'Entry', 'Details']} rows={(sb.data?.data ?? []).map((e) => [e.effective_date, label(e.entry_type), <span key={e.id} className="text-xs text-muted-foreground">{Object.entries(e.details ?? {}).filter(([k, v]) => v != null && !k.endsWith("_id")).map(([k, v]) => `${label(k)}: ${k.endsWith("_paise") ? inr(Number(v)) : String(v)}`).join(" · ")}</span>])} />
              {(can('hr', 'service_book') || can('hr', 'manage')) && (
                <div className="mt-3 flex flex-wrap items-end gap-2">
                  <Select aria-label="Entry type" className="w-44" options={ENTRY_TYPES.map((t) => ({ value: t, label: label(t) }))} value={entry.entry_type} onChange={(e) => setEntry({ ...entry, entry_type: e.target.value })} />
                  <FormField aria-label="Effective date" type="date" value={entry.effective_date} onChange={(e) => setEntry({ ...entry, effective_date: e.target.value })} />
                  <FormField aria-label="Note" placeholder="Note" value={entry.note} onChange={(e) => setEntry({ ...entry, note: e.target.value })} />
                  <Button disabled={!entry.effective_date} onClick={() => addEntry.mutate(undefined, { onSuccess: () => { toast.success('Entry added'); sb.refetch(); }, onError: (e) => toast.error(getApiError(e)) })}>Add entry</Button>
                </div>
              )}
            </TabsContent>
            <TabsContent value="leaves">
              <SimpleTable head={['Type', 'From', 'To', 'Days', 'Status']} rows={(leaves.data?.data ?? []).map((l) => [l.leave_type_code, l.from_date, l.to_date, num(l.days_count), <StatusBadge key={l.id} status={l.status} />])} />
            </TabsContent>
            <TabsContent value="att">
              <SimpleTable head={['Present', 'Absent', 'On leave', 'Holiday', 'Week off', 'LOP', 'Unmarked']} rows={(att.data?.data ?? []).map((a) => [a.present, a.absent, a.on_leave, a.holiday, a.week_off, a.lop_days, a.unmarked])} />
            </TabsContent>
            <TabsContent value="pay">
              {structures.data && (
                <>
                  <h3 className="mb-2 text-sm font-semibold">Salary structures</h3>
                  <SimpleTable head={['From', 'To', 'Level', 'Basic', 'Monthly gross']} rows={structures.data.data.map((x) => [x.effective_from, x.effective_to ?? 'open', x.pay_level, inr(x.basic_paise), inr(x.monthly_gross_paise)])} />
                </>
              )}
              <h3 className="mb-2 mt-4 text-sm font-semibold">Payroll runs</h3>
              <SimpleTable head={['Period', 'Gross', 'Deductions', 'Net', 'Status']} rows={(pay.data?.data ?? []).map((p) => [`${MONTHS[p.month - 1]} ${p.year}`, inr(p.gross_paise), inr(p.deductions_paise), inr(p.net_paise), <StatusBadge key={p.id} status={p.status} />])} />
            </TabsContent>
            <TabsContent value="wl">
              {wl.data ? (
                <dl className="grid gap-3 sm:grid-cols-4">
                  <Field k="Theory h/week" v={wl.data.data.theory_hours} />
                  <Field k="Lab h/week" v={wl.data.data.lab_hours} />
                  <Field k="Admin h/week" v={wl.data.data.admin_hours} />
                  <Field k="Total vs norm" v={`${wl.data.data.total_hours} / ${wl.data.data.norm_hours ?? '—'} (${wl.data.data.load_status})`} />
                </dl>
              ) : (
                <p className="text-sm text-muted-foreground">{wl.error ? getApiError(wl.error) : 'Loading…'}</p>
              )}
            </TabsContent>
          </CardContent>
        </Card>
      </Tabs>

      <Modal
        open={exitOpen}
        onOpenChange={setExitOpen}
        title={`Exit ${s.full_name}`}
        description="Deactivates the account and revokes its sessions. Blocked while leaves are pending or payroll is unpaid."
        footer={<Button variant="destructive" loading={exit.isPending} disabled={!exitForm.exit_date || exitForm.exit_reason.length < 3} onClick={() => exit.mutate(undefined, { onSuccess: () => { toast.success('Exit recorded'); setExitOpen(false); }, onError: (e) => toast.error(getApiError(e)) })}>Confirm exit</Button>}
      >
        <div className="space-y-3">
          <FormField label="Exit date" type="date" value={exitForm.exit_date} onChange={(e) => setExitForm({ ...exitForm, exit_date: e.target.value })} />
          <label className="block space-y-1.5 text-sm font-medium">
            Reason
            <Textarea aria-label="Exit reason" value={exitForm.exit_reason} onChange={(e) => setExitForm({ ...exitForm, exit_reason: e.target.value })} />
          </label>
        </div>
      </Modal>
    </div>
  );
}
