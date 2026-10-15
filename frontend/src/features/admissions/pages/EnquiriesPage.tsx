import { useEffect, useState, type DragEvent } from 'react';
import { MoreHorizontal, Phone, Plus } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { useAuthStore } from '@/store/authStore';
import { admissionsApi } from '../api';
import { useAdmissionsMutation, useEnquiries, useEnquiryStats } from '../hooks';
import { ENQUIRY_STAGES, label, type Enquiry } from '../types';

const PHONE = /^\+?[0-9 -]{8,20}$/;

/** /admin/admissions/enquiries — CRM kanban by stage (drag or "Move to…"), assignment, follow-ups, notes, convert. */
export default function EnquiriesPage() {
  const { can } = usePermission();
  const me = useAuthStore((s) => s.currentUser);
  const [mine, setMine] = useState(false);
  const list = useEnquiries({ page_size: 200, scope: mine ? 'self' : undefined });
  const stats = useEnquiryStats();
  const [open, setOpen] = useState<Enquiry | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: '', phone: '', source: 'walk_in', follow_up_on: '', note: '' });
  const [note, setNote] = useState('');
  const [convertNo, setConvertNo] = useState('');
  const update = useAdmissionsMutation((v: { id: string; body: Record<string, unknown> }) => admissionsApi.updateEnquiry(v.id, v.body));
  const create = useAdmissionsMutation(() =>
    admissionsApi.createEnquiry({ name: form.name, phone: form.phone || undefined, source: form.source, follow_up_on: form.follow_up_on || undefined, note: form.note || undefined }),
  );
  const assign = useAdmissionsMutation((id: string) => admissionsApi.assignEnquiry(id, me!.id));
  const convert = useAdmissionsMutation((id: string) => admissionsApi.convertEnquiry(id, convertNo ? { application_number: convertNo } : {}));
  useEffect(() => {
    document.title = 'Enquiries';
  }, []);
  const rows = list.data?.data ?? [];
  const move = async (id: string, stage: string) => {
    try {
      await update.mutateAsync({ id, body: { stage } });
      toast.success(`Moved to ${label(stage)}`);
    } catch (e) {
      toast.error(getApiError(e));
    }
  };
  const onDrop = (stage: string) => (e: DragEvent) => {
    const id = e.dataTransfer.getData('text/plain');
    if (id) move(id, stage);
  };
  const writable = can('admissions', 'create') || can('admissions', 'update');
  return (
    <div className="space-y-4">
      <PageHeader
        title="Enquiries"
        description="Leads from the website, walk-ins, calls and events."
        actions={writable && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New enquiry</Button>}
      />
      {stats.data && (
        <div className="flex flex-wrap gap-2 text-xs">
          {stats.data.data.funnel.map((f) => (
            <Badge key={f.stage} variant="outline">{label(f.stage)} ≥ {f.count} ({f.pct}%)</Badge>
          ))}
          <Badge variant="outline">Lost {stats.data.data.by_stage.lost ?? 0}</Badge>
        </div>
      )}
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Assigned to me</label>
      <div className="grid gap-3 overflow-x-auto md:grid-cols-3 xl:grid-cols-6">
        {ENQUIRY_STAGES.map((stage) => (
          <div key={stage} className="min-h-40 rounded-md bg-muted/40 p-2" onDragOver={(e) => e.preventDefault()} onDrop={onDrop(stage)}>
            <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">{label(stage)} · {rows.filter((r) => r.stage === stage).length}</div>
            <div className="space-y-2">
              {rows.filter((r) => r.stage === stage).map((r) => (
                <Card key={r.id} draggable={writable} onDragStart={(e) => e.dataTransfer.setData('text/plain', r.id)} className="cursor-grab">
                  <CardContent className="space-y-1 p-2 sm:p-2">
                    <div className="flex items-start justify-between gap-1">
                      <button type="button" className="text-left text-sm font-medium hover:underline" onClick={() => setOpen(r)}>{r.name}</button>
                      {writable && (
                        <Select aria-label={`Move ${r.name} to…`} className="h-7 w-8 px-1 text-xs" value="" options={ENQUIRY_STAGES.filter((s) => s !== r.stage).map((s) => ({ value: s, label: label(s) }))} placeholder="⋯" onChange={(e) => e.target.value && move(r.id, e.target.value)} />
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">{label(r.source)} · {(r.program_interest ?? []).join(', ') || '—'}</div>
                    {r.phone && <a className="inline-flex items-center gap-1 text-xs" href={`tel:${r.phone}`}><Phone className="h-3 w-3" />{r.phone}</a>}
                    <div className="text-xs">{r.assigned_name ? `→ ${r.assigned_name}` : <span className="text-amber-600">unassigned</span>}{r.follow_up_on ? ` · follow up ${r.follow_up_on}` : ''}</div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        ))}
      </div>
      <Modal open={!!open} onOpenChange={(o) => !o && setOpen(null)} title={open?.name ?? ''} size="lg">
        {open && (
          <div className="space-y-3 text-sm">
            <p>{label(open.source)} · stage {label(open.stage)} · {open.assigned_name ? `assigned to ${open.assigned_name}` : 'unassigned'}{open.application_number ? ` · applicant ${open.application_number}` : ''}</p>
            <ul className="space-y-1">{open.notes.map((n, i) => <li key={i} className="rounded bg-muted/50 px-2 py-1"><span className="text-xs text-muted-foreground">{new Date(n.at).toLocaleString()}</span> {n.text}</li>)}</ul>
            {writable && (
              <>
                <Textarea rows={2} placeholder="Add a note" value={note} onChange={(e) => setNote(e.target.value)} />
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" disabled={!note} onClick={async () => { await update.mutateAsync({ id: open.id, body: { note } }); setNote(''); setOpen(null); toast.success('Note added'); }}>Add note</Button>
                  {can('admissions', 'update') && <Button size="sm" variant="outline" onClick={async () => { try { await assign.mutateAsync(open.id); toast.success('Assigned to you'); setOpen(null); } catch (e) { toast.error(getApiError(e)); } }}>Assign to me</Button>}
                  <Input className="h-8 w-44" placeholder="Application no. (optional)" value={convertNo} onChange={(e) => setConvertNo(e.target.value)} />
                  <Button size="sm" variant="outline" onClick={async () => { try { await convert.mutateAsync(open.id); toast.success('Linked to the applicant'); setOpen(null); } catch (e) { toast.error(getApiError(e)); } }}><MoreHorizontal className="h-4 w-4" /> Convert</Button>
                </div>
              </>
            )}
          </div>
        )}
      </Modal>
      <Modal open={creating} onOpenChange={setCreating} title="New enquiry"
        footer={<Button disabled={form.name.trim().length < 2 || (!!form.phone && !PHONE.test(form.phone))} onClick={async () => { try { await create.mutateAsync(undefined); toast.success('Enquiry recorded'); setCreating(false); } catch (e) { toast.error(getApiError(e)); } }}>Save</Button>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Name" required value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          <FormField label="Phone" error={form.phone && !PHONE.test(form.phone) ? 'Enter a valid phone' : undefined} value={form.phone} onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))} />
          <Select aria-label="Source" options={['walk_in', 'web', 'phone', 'referral', 'event', 'agent'].map((s) => ({ value: s, label: label(s) }))} value={form.source} onChange={(e) => setForm((f) => ({ ...f, source: e.target.value }))} />
          <FormField label="Follow up on" type="date" value={form.follow_up_on} onChange={(e) => setForm((f) => ({ ...f, follow_up_on: e.target.value }))} />
          <Textarea className="sm:col-span-2" rows={2} placeholder="Note" value={form.note} onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))} />
        </div>
      </Modal>
    </div>
  );
}
