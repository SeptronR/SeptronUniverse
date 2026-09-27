import { useState } from 'react';
import { Eye, Plus } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { toast } from '@/components/ui/Toaster';
import { institutionApi } from '../api';
import { useColleges, useInstMutation, useSequences } from '../hooks';
import type { NumberSequence } from '../types';

const TOKENS = ['{yy}', '{yyyy}', '{mm}', '{college_code}', '{prog_code}', '{term}', '{seq:4}'];

/** /admin/number-sequences — pattern editor with token chips and a live preview (nothing is consumed). */
export default function NumberSequencesPage() {
  const seqs = useSequences({ page_size: 100 });
  const colleges = useColleges({ scope: 'all', page_size: 200 });
  const [editing, setEditing] = useState<NumberSequence | 'new' | null>(null);
  const [form, setForm] = useState({ scope_key: '', pattern: '', padding: 4, next_value: 1, reset_policy: 'never', college_id: '' });
  const [preview, setPreview] = useState<string[] | null>(null);
  const create = useInstMutation((b: Record<string, unknown>) => institutionApi.createSequence(b), ['number-sequences']);
  const update = useInstMutation(({ id, ...b }: Record<string, unknown>) => institutionApi.updateSequence(String(id), b), ['number-sequences']);
  if (seqs.isLoading) return <PageSkeleton />;
  const onErr = (e: unknown) => toast.error(getApiError(e));

  const open = (s: NumberSequence | 'new') => {
    setEditing(s);
    setPreview(null);
    setForm(
      s === 'new'
        ? { scope_key: '', pattern: '{college_code}{yy}{seq:4}', padding: 4, next_value: 1, reset_policy: 'yearly', college_id: '' }
        : { scope_key: s.scope_key, pattern: s.pattern, padding: s.padding, next_value: s.next_value, reset_policy: s.reset_policy, college_id: s.college_id ?? '' },
    );
  };
  const save = () => {
    const done = { onSuccess: () => { toast.success('Sequence saved'); setEditing(null); }, onError: onErr };
    if (editing === 'new') create.mutate({ ...form, college_id: form.college_id || null }, done);
    else if (editing) update.mutate({ id: editing.id, pattern: form.pattern, padding: form.padding, next_value: form.next_value, reset_policy: form.reset_policy }, done);
  };
  const runPreview = async () => {
    if (!editing || editing === 'new') return;
    try {
      const r = await institutionApi.previewSequence(editing.id, { count: 3 });
      setPreview(r.data.values);
    } catch (e) {
      onErr(e);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Number sequences"
        description="Formats for register numbers, receipts, hall tickets and certificates. Values are reserved atomically."
        actions={<Button onClick={() => open('new')}><Plus className="h-4 w-4" /> New sequence</Button>}
      />
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="p-2">Scope key</th>
            <th className="p-2">Pattern</th>
            <th className="p-2">Next</th>
            <th className="p-2">Sample</th>
            <th className="p-2">Reset</th>
            <th />
          </tr>
        </thead>
        <tbody className="divide-y">
          {(seqs.data?.data ?? []).map((s) => (
            <tr key={s.id}>
              <td className="p-2 font-mono text-xs">
                {s.scope_key} {s.college_id && <Badge variant="outline">college</Badge>}
              </td>
              <td className="p-2 font-mono text-xs">{s.pattern}</td>
              <td className="p-2">{s.next_value}</td>
              <td className="p-2 font-mono">{s.sample}</td>
              <td className="p-2">{s.reset_policy}</td>
              <td className="p-2 text-right">
                <Button size="sm" variant="ghost" onClick={() => open(s)}>Edit</Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Modal
        open={editing !== null}
        onOpenChange={(o) => !o && setEditing(null)}
        title={editing === 'new' ? 'New sequence' : 'Edit sequence'}
        footer={
          <>
            {editing !== 'new' && (
              <Button variant="outline" onClick={runPreview}>
                <Eye className="h-4 w-4" /> Preview
              </Button>
            )}
            <Button loading={create.isPending || update.isPending} onClick={save}>Save</Button>
          </>
        }
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Scope key" disabled={editing !== 'new'} value={form.scope_key} onChange={(e) => setForm({ ...form, scope_key: e.target.value })} />
          <FormField label="Pattern" value={form.pattern} onChange={(e) => setForm({ ...form, pattern: e.target.value })} />
          <div className="sm:col-span-2 flex flex-wrap gap-1">
            {TOKENS.map((t) => (
              <button key={t} type="button" className="rounded border px-2 py-0.5 font-mono text-xs hover:bg-accent" onClick={() => setForm({ ...form, pattern: form.pattern + t })}>
                {t}
              </button>
            ))}
          </div>
          <FormField label="Next value" type="number" min={1} value={form.next_value} onChange={(e) => setForm({ ...form, next_value: Number(e.target.value) })} />
          <FormField label="Padding" type="number" min={1} max={12} value={form.padding} onChange={(e) => setForm({ ...form, padding: Number(e.target.value) })} />
          <label className="space-y-1.5 text-sm font-medium">
            Reset
            <Select value={form.reset_policy} options={['never', 'yearly', 'per_term'].map((v) => ({ value: v, label: v }))} onChange={(e) => setForm({ ...form, reset_policy: e.target.value })} />
          </label>
          {editing === 'new' && (
            <label className="space-y-1.5 text-sm font-medium">
              College
              <Select placeholder="Institution-wide" value={form.college_id} options={(colleges.data?.data ?? []).map((c) => ({ value: c.id, label: c.code }))} onChange={(e) => setForm({ ...form, college_id: e.target.value })} />
            </label>
          )}
        </div>
        {preview && <p className="mt-3 font-mono text-sm">Next: {preview.join(' · ')}</p>}
      </Modal>
    </div>
  );
}
