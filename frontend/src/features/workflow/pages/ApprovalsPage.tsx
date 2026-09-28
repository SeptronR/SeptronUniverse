import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Inbox, Trash2 } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DateField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatusBadge, Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { StaffPicker } from '@/features/institution/components/StaffPicker';
import { useFeature } from '@/hooks/useFeature';
import { formatRelative } from '@/utils/formatters';
import { workflowApi } from '../api';
import { ActPanel } from '../components/ActPanel';
import { WorkflowTimeline } from '../components/WorkflowTimeline';
import { useDelegations, useInbox, useInstances, useWorkflowMutation } from '../hooks';
import type { InboxItem } from '../types';

/** /approvals — inbox grouped by module with an act drawer, my requests, delegations (Prompts/04 §04.9). */
export default function ApprovalsPage() {
  const inbox = useInbox();
  const [params] = useSearchParams();
  const [open, setOpen] = useState<InboxItem | null>(null);
  const mine = useInstances({ mine: true, page_size: 50 });
  const delegationsOn = useFeature('workflow.delegation');
  if (inbox.isLoading) return <PageSkeleton />;
  const items = inbox.data?.data ?? [];
  const groups = new Map<string, InboxItem[]>();
  for (const it of items) groups.set(it.instance.module, [...(groups.get(it.instance.module) ?? []), it]);
  const focus = params.get('instance');

  return (
    <div className="space-y-4">
      <PageHeader title="Approvals" description="Requests waiting for your decision, your own requests and delegations." />
      <Tabs defaultValue="inbox">
        <TabsList>
          <TabsTrigger value="inbox">
            Inbox {items.length > 0 && <Badge className="ml-1">{items.length}</Badge>}
          </TabsTrigger>
          <TabsTrigger value="mine">My requests</TabsTrigger>
          {delegationsOn && <TabsTrigger value="delegations">Delegations</TabsTrigger>}
        </TabsList>
        <TabsContent value="inbox" className="space-y-4">
          {items.length === 0 && (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Inbox className="h-4 w-4" /> Nothing is waiting for you.
            </p>
          )}
          {[...groups.entries()].map(([module, rows]) => (
            <section key={module}>
              <h2 className="mb-2 text-sm font-semibold uppercase text-muted-foreground">{module.replace(/_/g, ' ')}</h2>
              <div className="grid gap-2 md:grid-cols-2">
                {rows.map((it) => (
                  <Card key={it.step_id} className={focus === it.instance.id ? 'ring-2 ring-primary' : undefined}>
                    <CardContent className="space-y-1 p-3">
                      <div className="flex items-start justify-between gap-2">
                        <button type="button" className="text-left font-medium hover:underline" onClick={() => setOpen(it)}>
                          {it.entity_summary ?? it.instance.title}
                        </button>
                        <StatusBadge status={it.instance.status} />
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {it.instance.started_by_name ?? 'someone'} · {formatRelative(it.instance.started_at)} · step {it.instance.current_step}/
                        {it.instance.total_steps}
                        {it.via !== 'direct' && ` · via ${it.via}`}
                      </p>
                      <Button size="sm" variant="outline" onClick={() => setOpen(it)}>
                        Review
                      </Button>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </section>
          ))}
        </TabsContent>
        <TabsContent value="mine">
          <ul className="divide-y rounded-md border">
            {(mine.data?.data ?? []).map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-2 p-3 text-sm">
                <Link to={`/approvals/instances/${i.id}`} className="font-medium hover:underline">
                  {i.title}
                </Link>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  {formatRelative(i.started_at)} <StatusBadge status={i.status} />
                </span>
              </li>
            ))}
            {(mine.data?.data ?? []).length === 0 && <li className="p-3 text-sm text-muted-foreground">No requests.</li>}
          </ul>
        </TabsContent>
        {delegationsOn && (
          <TabsContent value="delegations">
            <Delegations />
          </TabsContent>
        )}
      </Tabs>
      <Modal open={open !== null} onOpenChange={(o) => !o && setOpen(null)} size="lg" title={open?.instance.title ?? ''} description={open?.entity_summary ?? undefined}>
        {open && (
          <div className="space-y-4">
            <WorkflowTimeline instance={open.instance} />
            <ActPanel instance={open.instance} onDone={() => setOpen(null)} />
          </div>
        )}
      </Modal>
    </div>
  );
}

function Delegations() {
  const list = useDelegations();
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<{ to: string; toName: string; module: string; from_on: string; to_on: string }>({
    to: '',
    toName: '',
    module: '',
    from_on: new Date().toISOString().slice(0, 10),
    to_on: new Date().toISOString().slice(0, 10),
  });
  const create = useWorkflowMutation(() =>
    workflowApi.delegate({ to_user_id: draft.to, module: draft.module || null, from_on: draft.from_on, to_on: draft.to_on }),
  );
  const revoke = useWorkflowMutation((id: string) => workflowApi.revokeDelegation(id));
  return (
    <div className="space-y-3">
      <Button onClick={() => setAdding(true)}>Delegate my approvals</Button>
      <ul className="divide-y rounded-md border">
        {(list.data?.data ?? []).map((d) => (
          <li key={d.id} className="flex items-center justify-between p-3 text-sm">
            <span>
              {d.from_user_name} → <b>{d.to_user_name}</b> · {d.module ?? 'all modules'} · {d.from_on} → {d.to_on}
            </span>
            <Button size="icon" variant="ghost" aria-label="Revoke" onClick={() => revoke.mutate(d.id, { onError: (e) => toast.error(getApiError(e)) })}>
              <Trash2 className="h-4 w-4" />
            </Button>
          </li>
        ))}
      </ul>
      <Modal
        open={adding}
        onOpenChange={setAdding}
        title="Delegate approvals"
        footer={
          <Button
            disabled={!draft.to}
            loading={create.isPending}
            onClick={() => create.mutate(undefined, { onSuccess: () => { toast.success('Delegation saved'); setAdding(false); }, onError: (e) => toast.error(getApiError(e)) })}
          >
            Save
          </Button>
        }
      >
        <div className="space-y-3">
          {draft.to ? <p className="text-sm">Delegate: <b>{draft.toName}</b></p> : <StaffPicker onPick={(id, name) => setDraft({ ...draft, to: id, toName: name })} />}
          <Input placeholder="Module (empty = all), e.g. leaves" value={draft.module} onChange={(e) => setDraft({ ...draft, module: e.target.value })} />
          <div className="grid grid-cols-2 gap-2">
            <DateField label="From" value={draft.from_on} onChange={(v) => setDraft({ ...draft, from_on: v ?? '' })} />
            <DateField label="To" value={draft.to_on} onChange={(v) => setDraft({ ...draft, to_on: v ?? '' })} />
          </div>
        </div>
      </Modal>
    </div>
  );
}
