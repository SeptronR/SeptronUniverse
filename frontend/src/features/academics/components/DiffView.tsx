import { Minus, Pencil, Plus } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { useDiff } from '../hooks';
import { label, num } from '../types';

const show = (v: unknown) => (typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v ?? '—'));

/** Diff tab — courses added / removed / changed and rules changed vs the predecessor regulation. */
export function DiffView({ regulationId, active }: { regulationId: string; active: boolean }) {
  const diff = useDiff(regulationId, active);
  const d = diff.data?.data;
  if (!d) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!d.predecessor_id) return <p className="text-sm text-muted-foreground">No predecessor — every course of {d.regulation_code} is new ({d.added.length}).</p>;
  return (
    <div className="space-y-3">
      <p className="text-sm">
        {d.regulation_code} vs <span className="font-medium">{d.predecessor_code}</span>: {d.added.length} added, {d.removed.length} removed, {d.changed.length} changed,{' '}
        {d.unchanged_count} unchanged.
      </p>
      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Plus className="h-4 w-4 text-status-approved" /> Added
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {d.added.map((c) => (
              <p key={c.code} className="rounded bg-status-approved/10 px-2 py-1">
                {c.code} · {c.title} ({label(c.course_type)}, {num(c.credits)})
              </p>
            ))}
            {d.added.length === 0 && <p className="text-muted-foreground">None.</p>}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Minus className="h-4 w-4 text-status-rejected" /> Removed
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 text-sm">
            {d.removed.map((c) => (
              <p key={c.code} className="rounded bg-status-rejected/10 px-2 py-1 line-through">
                {c.code} · {c.title}
              </p>
            ))}
            {d.removed.length === 0 && <p className="text-muted-foreground">None.</p>}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Pencil className="h-4 w-4 text-status-pending" /> Changed courses
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          {d.changed.map((c) => (
            <div key={c.code} className="rounded-md border border-status-pending/40 p-2">
              <p className="font-medium">
                {c.code} · {c.title}
              </p>
              <table className="mt-1 w-full text-xs">
                <tbody>
                  {Object.entries(c.fields).map(([f, v]) => (
                    <tr key={f}>
                      <td className="w-40 text-muted-foreground">{label(f)}</td>
                      <td className="bg-status-rejected/10 px-1 line-through">{show(v.old)}</td>
                      <td className="bg-status-approved/10 px-1">{show(v.new)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          {d.changed.length === 0 && <p className="text-muted-foreground">None.</p>}
        </CardContent>
      </Card>
      {Object.keys(d.rules_changed).length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Rules changed</CardTitle>
          </CardHeader>
          <CardContent className="text-xs">
            {Object.entries(d.rules_changed).map(([k, v]) => (
              <p key={k}>
                <span className="font-medium">{label(k)}</span>: <span className="line-through">{show(v.old)}</span> → {show(v.new)}
              </p>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
