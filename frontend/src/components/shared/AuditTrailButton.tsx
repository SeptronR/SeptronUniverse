import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { History } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { auditApi } from '@/features/audit/api';
import { usePermission } from '@/hooks/usePermission';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const CONFIDENTIAL = ['student', 'students', 'staff', 'health_visit', 'grievance', 'answer_script'];

/**
 * `<AuditTrailButton recordType recordId>` — the record timeline (audit rows + domain events + workflow steps) of any
 * record page, with a "Who viewed" tab on confidential records (Prompts/37 §37.9). Hidden without `audit_logs:view`.
 */
export function AuditTrailButton({ recordType, recordId, label = 'Audit trail' }: { recordType: string; recordId?: string; label?: string }) {
  const { can, canAny } = usePermission();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<'timeline' | 'viewed'>('timeline');
  const enabled = open && !!recordId;
  const tl = useQuery({ queryKey: ['audit', 'timeline', recordType, recordId], queryFn: () => auditApi.timeline(recordType, recordId!), enabled, retry: false });
  const wv = useQuery({ queryKey: ['audit', 'viewed', recordType, recordId], queryFn: () => auditApi.whoViewed(recordType, recordId!), enabled: enabled && tab === 'viewed', retry: false });
  if (!recordId || !canAny([['audit_logs', 'view'], ['audit_logs', 'view_all']])) return null;
  const showViewed = CONFIDENTIAL.includes(recordType) && can('audit_logs', 'view_all');
  const rows: Any[] = (tab === 'timeline' ? tl.data?.data : wv.data?.data) ?? [];
  const q = tab === 'timeline' ? tl : wv;
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        <History className="mr-1 h-4 w-4" /> {label}
      </Button>
      <Modal open={open} onOpenChange={setOpen} title={label} description={`${recordType} · ${recordId}`} size="lg">
        <div className="mb-3 flex gap-2">
          <Button size="sm" variant={tab === 'timeline' ? 'default' : 'outline'} onClick={() => setTab('timeline')}>Timeline</Button>
          {showViewed && <Button size="sm" variant={tab === 'viewed' ? 'default' : 'outline'} onClick={() => setTab('viewed')}>Who viewed</Button>}
        </div>
        {q.isError && <p className="text-sm text-destructive">{getApiError(q.error)}</p>}
        <ol className="max-h-[60vh] space-y-2 overflow-y-auto text-sm">
          {rows.map((r, i) => (
            <li key={i} className="rounded border p-2">
              <div className="flex justify-between gap-2 text-xs text-muted-foreground">
                <span>{new Date(r.at).toLocaleString()}</span>
                <span>{r.source ?? r.action}</span>
              </div>
              <div className="font-medium">{r.summary ?? r.action}</div>
              <div className="text-xs">{r.actor?.name ?? r.user?.name ?? '—'}{r.fields_unmasked?.length ? ` · unmasked ${r.fields_unmasked.join(', ')}` : ''}</div>
            </li>
          ))}
          {!rows.length && !q.isLoading && <li className="text-muted-foreground">Nothing recorded.</li>}
        </ol>
      </Modal>
    </>
  );
}
