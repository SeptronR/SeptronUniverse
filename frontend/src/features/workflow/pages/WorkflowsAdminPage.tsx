import { useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { usePermission } from '@/hooks/usePermission';
import { workflowApi } from '../api';
import { useDefinitions, useWorkflowMutation } from '../hooks';
import type { StepSpec, WorkflowDefinition } from '../types';

const TYPES = [
  { value: 'role', label: 'Role (in the request scope)' },
  { value: 'scope_rule', label: 'Scope rule' },
  { value: 'user', label: 'Specific user (id)' },
];

/** /admin/workflows — definitions list and step editor (approver type/role/scope rule/user, mode, SLA, escalation). */
export default function WorkflowsAdminPage() {
  const { can } = usePermission();
  const defs = useDefinitions();
  const [editing, setEditing] = useState<WorkflowDefinition | null>(null);
  const [steps, setSteps] = useState<StepSpec[]>([]);
  const save = useWorkflowMutation(() => workflowApi.saveDefinition(editing!.id, { steps }));
  if (defs.isLoading) return <PageSkeleton />;
  const manage = can('settings', 'manage');
  const set = (i: number, patch: Partial<StepSpec>) => setSteps(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  return (
    <div className="space-y-4">
      <PageHeader title="Workflows" description="Approval chains. Saving creates a new version; running requests keep theirs." />
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="p-2">Workflow</th>
            <th className="p-2">Module</th>
            <th className="p-2">Steps</th>
            <th className="p-2">Version</th>
            <th />
          </tr>
        </thead>
        <tbody className="divide-y">
          {(defs.data?.data ?? []).map((d) => (
            <tr key={d.id}>
              <td className="p-2">
                <p className="font-medium">{d.name}</p>
                <p className="font-mono text-xs text-muted-foreground">{d.key}</p>
              </td>
              <td className="p-2">{d.module}</td>
              <td className="p-2 text-xs">
                {[...new Set(d.steps.map((s) => s.order))].map((o) => (
                  <span key={o} className="mr-1 inline-block">
                    {o}. {d.steps.filter((s) => s.order === o).map((s) => s.approver.value).join(' + ')}
                  </span>
                ))}
              </td>
              <td className="p-2">
                v{d.version} {!d.is_active && <Badge variant="outline">inactive</Badge>}
              </td>
              <td className="p-2 text-right">
                {manage && (
                  <Button size="sm" variant="ghost" onClick={() => { setEditing(d); setSteps(d.steps.map((s) => ({ ...s }))); }}>
                    Edit
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Modal
        open={editing !== null}
        onOpenChange={(o) => !o && setEditing(null)}
        size="xl"
        title={editing?.name ?? ''}
        description={editing ? `${editing.key} · saving creates v${editing.version + 1}` : undefined}
        footer={
          <Button loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: (r) => { toast.success(`Saved v${r.data.version}`); setEditing(null); }, onError: (e) => toast.error(getApiError(e)) })}>
            Save new version
          </Button>
        }
      >
        <div className="space-y-2">
          {steps.map((s, i) => (
            <div key={i} className="grid items-end gap-2 rounded-md border p-2 sm:grid-cols-[4rem_10rem_1fr_8rem_6rem_1fr_auto]">
              <label className="text-xs">
                Order
                <Input type="number" min={1} value={s.order} onChange={(e) => set(i, { order: Number(e.target.value) })} />
              </label>
              <label className="text-xs">
                Approver
                <Select value={s.approver.type} options={TYPES} onChange={(e) => set(i, { approver: { ...s.approver, type: e.target.value as StepSpec['approver']['type'] } })} />
              </label>
              <label className="text-xs">
                Value
                <Input value={s.approver.value} placeholder="hod / entity.department.hod / user id" onChange={(e) => set(i, { approver: { ...s.approver, value: e.target.value } })} />
              </label>
              <label className="text-xs">
                Mode
                <Select value={s.mode ?? 'sequential'} options={[{ value: 'sequential', label: 'sequential' }, { value: 'parallel', label: 'parallel' }]} onChange={(e) => set(i, { mode: e.target.value as 'sequential' | 'parallel' })} />
              </label>
              <label className="text-xs">
                SLA (h)
                <Input type="number" min={0} step="0.5" value={s.sla_hours ?? ''} onChange={(e) => set(i, { sla_hours: e.target.value ? Number(e.target.value) : null })} />
              </label>
              <label className="text-xs">
                Escalate to role
                <Input value={s.escalate_to?.value ?? ''} onChange={(e) => set(i, { escalate_to: e.target.value ? { type: 'role', value: e.target.value } : null })} />
              </label>
              <Button size="icon" variant="ghost" aria-label="Remove step" onClick={() => setSteps(steps.filter((_, j) => j !== i))}>
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setSteps([...steps, { order: Math.max(0, ...steps.map((s) => s.order)) + 1, approver: { type: 'role', value: '' }, mode: 'sequential', sla_hours: 48 }])}
          >
            <Plus className="h-4 w-4" /> Add step
          </Button>
        </div>
      </Modal>
    </div>
  );
}
