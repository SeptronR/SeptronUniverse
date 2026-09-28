import { useState } from 'react';
import { getApiError } from '@/api/axios';
import { StaffPicker } from '@/features/institution/components/StaffPicker';
import { Button } from '@/components/ui/Button';
import { Textarea } from '@/components/ui/Input';
import { toast } from '@/components/ui/Toaster';
import { workflowApi } from '../api';
import { useWorkflowMutation } from '../hooks';
import type { WorkflowInstance } from '../types';

/** Approve / reject (comment required) / delegate for the current step. */
export function ActPanel({ instance, onDone }: { instance: WorkflowInstance; onDone?: () => void }) {
  const [comment, setComment] = useState('');
  const [delegating, setDelegating] = useState(false);
  const act = useWorkflowMutation((b: { decision: 'approve' | 'reject' | 'delegate'; comment?: string; delegate_to?: string }) =>
    workflowApi.act(instance.id, b),
  );
  const run = (decision: 'approve' | 'reject' | 'delegate', delegate_to?: string) =>
    act.mutate(
      { decision, comment: comment || undefined, delegate_to },
      {
        onSuccess: () => {
          toast.success(decision === 'approve' ? 'Approved' : decision === 'reject' ? 'Rejected' : 'Delegated');
          onDone?.();
        },
        onError: (e) => toast.error(getApiError(e)),
      },
    );
  if (!instance.can_act) return null;
  return (
    <div className="space-y-2">
      <Textarea rows={2} placeholder="Comment (required to reject)" value={comment} onChange={(e) => setComment(e.target.value)} />
      <div className="flex flex-wrap gap-2">
        <Button loading={act.isPending} onClick={() => run('approve')}>
          Approve
        </Button>
        <Button variant="destructive" disabled={!comment.trim()} onClick={() => run('reject')}>
          Reject
        </Button>
        <Button variant="outline" onClick={() => setDelegating((v) => !v)}>
          Delegate…
        </Button>
      </div>
      {delegating && <StaffPicker onPick={(id) => run('delegate', id)} />}
    </div>
  );
}
