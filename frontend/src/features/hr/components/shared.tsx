import { useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { Button } from '@/components/ui/Button';
import { Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { workflowApi } from '@/features/workflow/api';
import { WorkflowTimeline } from '@/features/workflow/components/WorkflowTimeline';
import { hrApi } from '../api';
import { useHrMutation, useLeaveTypes } from '../hooks';

/** Loads a workflow instance and renders its timeline (leave / appraisal / CAS / loan approvals). */
export function WorkflowPanel({ instanceId }: { instanceId: string | null | undefined }) {
  const q = useQuery({ queryKey: ['workflow', 'instance', instanceId], queryFn: () => workflowApi.instance(instanceId!), enabled: !!instanceId });
  if (!instanceId) return <p className="text-sm text-muted-foreground">No workflow.</p>;
  if (!q.data) return <p className="text-sm text-muted-foreground">Loading approval trail…</p>;
  return <WorkflowTimeline instance={q.data.data} />;
}

/** Plain responsive table for small HR lists (registers, summaries, items). */
export function SimpleTable({ head, rows, empty = 'Nothing to show.' }: { head: ReactNode[]; rows: ReactNode[][]; empty?: string }) {
  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-sm">
        <thead className="bg-muted/50 text-left text-xs uppercase text-muted-foreground">
          <tr>{head.map((h, i) => <th key={i} className="px-3 py-2 font-medium">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t">
              {r.map((c, j) => <td key={j} className="px-3 py-2">{c}</td>)}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={head.length} className="px-3 py-6 text-center text-muted-foreground">{empty}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/** Apply-for-leave dialog (validation: dates in order, a reason; the API checks overlap, balance and documents). */
export function LeaveApplyModal({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const types = useLeaveTypes();
  const [form, setForm] = useState({ leave_type_id: '', from_date: '', to_date: '', half_day: '', reason: '', document_url: '' });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const apply = useHrMutation((body: Record<string, unknown>) => hrApi.applyLeave(body), ['leaves']);
  const selected = types.data?.data.find((t) => t.id === form.leave_type_id);
  const submit = () => {
    const e: Record<string, string> = {};
    if (!form.leave_type_id) e.leave_type_id = 'Choose a leave type';
    if (!form.from_date) e.from_date = 'Required';
    if (!form.to_date) e.to_date = 'Required';
    if (form.from_date && form.to_date && form.to_date < form.from_date) e.to_date = 'Must not be before the start';
    if (form.half_day && form.from_date !== form.to_date) e.half_day = 'A half day covers one date';
    if (form.reason.trim().length < 3) e.reason = 'Give a reason';
    setErrors(e);
    if (Object.keys(e).length) return;
    apply.mutate(
      { ...form, half_day: form.half_day || undefined, document_url: form.document_url || undefined },
      {
        onSuccess: (r) => {
          toast.success(`Applied: ${r.data.days_count} day(s) — awaiting approval`);
          onOpenChange(false);
          setForm({ leave_type_id: '', from_date: '', to_date: '', half_day: '', reason: '', document_url: '' });
        },
        onError: (err) => toast.error(getApiError(err)),
      },
    );
  };
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Apply for leave" description="Holidays and weekly offs inside the range are not counted." footer={<Button loading={apply.isPending} onClick={submit}>Apply</Button>}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1.5 text-sm font-medium sm:col-span-2">
          Leave type
          <Select aria-label="Leave type" placeholder="Select…" options={(types.data?.data ?? []).map((t) => ({ value: t.id, label: `${t.code} · ${t.name}` }))} value={form.leave_type_id} onChange={(e) => setForm({ ...form, leave_type_id: e.target.value })} />
          {errors.leave_type_id && <span role="alert" className="block text-xs text-destructive">{errors.leave_type_id}</span>}
        </label>
        <FormField label="From" type="date" value={form.from_date} error={errors.from_date} onChange={(e) => setForm({ ...form, from_date: e.target.value, to_date: form.to_date || e.target.value })} />
        <FormField label="To" type="date" value={form.to_date} error={errors.to_date} onChange={(e) => setForm({ ...form, to_date: e.target.value })} />
        <label className="space-y-1.5 text-sm font-medium">
          Half day
          <Select aria-label="Half day" placeholder="Full day(s)" options={[{ value: 'first_half', label: 'First half' }, { value: 'second_half', label: 'Second half' }]} value={form.half_day} onChange={(e) => setForm({ ...form, half_day: e.target.value })} />
          {errors.half_day && <span role="alert" className="block text-xs text-destructive">{errors.half_day}</span>}
        </label>
        <FormField label={selected?.requires_document ? 'Document URL (required above 3 days)' : 'Document URL'} value={form.document_url} onChange={(e) => setForm({ ...form, document_url: e.target.value })} />
        <label className="space-y-1.5 text-sm font-medium sm:col-span-2">
          Reason
          <Textarea aria-label="Reason" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          {errors.reason && <span role="alert" className="block text-xs text-destructive">{errors.reason}</span>}
        </label>
      </div>
    </Modal>
  );
}
