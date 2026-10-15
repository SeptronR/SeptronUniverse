import { CheckCircle2, CircleDashed, Clock, Forward, SkipForward, TriangleAlert, XCircle } from 'lucide-react';
import { cn } from '@/utils/cn';
import { formatDateTime, formatRelative } from '@/utils/formatters';
import type { WorkflowInstance, WorkflowStep } from '../types';

const ICON: Record<string, typeof Clock> = {
  approved: CheckCircle2,
  rejected: XCircle,
  pending: Clock,
  escalated: TriangleAlert,
  delegated: Forward,
  skipped: SkipForward,
};

function who(s: WorkflowStep) {
  return s.approver_name ?? (s.approver_role_slug ? `any ${s.approver_role_slug.replace(/_/g, ' ')}` : 'approver');
}

/**
 * Step timeline of a workflow instance (Prompts/04 §04.9) — reused inside entity pages (leave, registration, …):
 * one row per approver with status, actor (and "on behalf of" when a delegate acted), comment, SLA and escalation.
 */
export function WorkflowTimeline({ instance, className }: { instance: WorkflowInstance; className?: string }) {
  const orders = Array.from({ length: instance.total_steps }, (_, i) => i + 1);
  return (
    <ol className={cn('space-y-3', className)} aria-label="Approval timeline">
      {orders.map((order) => {
        const steps = instance.steps.filter((s) => s.order === order);
        const future = steps.length === 0;
        return (
          <li key={order} className="flex gap-3">
            <div className="flex flex-col items-center">
              <span
                className={cn(
                  'flex h-7 w-7 items-center justify-center rounded-full border text-xs font-semibold',
                  order === instance.current_step && ['pending', 'escalated'].includes(instance.status) && 'border-primary text-primary',
                )}
              >
                {order}
              </span>
              {order < instance.total_steps && <span className="mt-1 w-px flex-1 bg-border" />}
            </div>
            <div className="min-w-0 flex-1 space-y-1 pb-2">
              {future && (
                <p className="flex items-center gap-2 text-sm text-muted-foreground">
                  <CircleDashed className="h-4 w-4" /> Waiting for earlier steps
                </p>
              )}
              {steps.map((s) => {
                const Icon = ICON[s.status] ?? Clock;
                return (
                  <div key={s.id} className="rounded-md border p-2 text-sm">
                    <p className="flex flex-wrap items-center gap-2">
                      <Icon className={cn('h-4 w-4', s.status === 'approved' && 'text-status-approved', s.status === 'rejected' && 'text-status-rejected')} />
                      <span className="font-medium">{who(s)}</span>
                      <span className="text-xs text-muted-foreground">{s.status}</span>
                    </p>
                    {s.acted_by && (
                      <p className="text-xs text-muted-foreground">
                        by {s.acted_by_name ?? 'someone'}
                        {s.delegated_from ? ` on behalf of ${s.approver_name ?? 'the approver'}` : ''}
                        {s.acted_at && (
                          <>
                            {' · '}
                            <time dateTime={s.acted_at} title={formatDateTime(s.acted_at)}>
                              {formatDateTime(s.acted_at)} ({formatRelative(s.acted_at)})
                            </time>
                          </>
                        )}
                      </p>
                    )}
                    {s.comment && <p className="mt-1 italic">“{s.comment}”</p>}
                    {s.sla_due_at && ['pending', 'escalated'].includes(s.status) && (
                      <p className="text-xs text-muted-foreground">
                        SLA due <time dateTime={s.sla_due_at} title={formatDateTime(s.sla_due_at)}>{formatRelative(s.sla_due_at)}</time>
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
