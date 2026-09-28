import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Input, Textarea } from '@/components/ui/Input';
import type { SyllabusUnit } from '../types';

/** Syllabus units editor: unit number, title, hours and one topic per line. */
export function SyllabusEditor({ value, onChange, disabled }: { value: SyllabusUnit[]; onChange: (v: SyllabusUnit[]) => void; disabled?: boolean }) {
  const set = (i: number, patch: Partial<SyllabusUnit>) => onChange(value.map((u, j) => (j === i ? { ...u, ...patch } : u)));
  return (
    <div className="space-y-2">
      {value.map((u, i) => (
        <div key={i} className="grid gap-2 rounded-md border p-2 sm:grid-cols-[60px_1fr_80px_auto]">
          <Input aria-label="Unit" type="number" disabled={disabled} value={u.unit} onChange={(e) => set(i, { unit: Number(e.target.value) })} />
          <Input aria-label="Unit title" disabled={disabled} value={u.title} placeholder="Unit title" onChange={(e) => set(i, { title: e.target.value })} />
          <Input aria-label="Hours" type="number" disabled={disabled} value={u.hours ?? ''} placeholder="hours" onChange={(e) => set(i, { hours: e.target.value ? Number(e.target.value) : null })} />
          {!disabled && (
            <Button type="button" size="sm" variant="ghost" aria-label={`Remove unit ${u.unit}`} onClick={() => onChange(value.filter((_, j) => j !== i))}>
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
          <Textarea
            aria-label="Topics"
            className="sm:col-span-4"
            rows={2}
            disabled={disabled}
            placeholder="One topic per line"
            value={u.topics.join('\n')}
            onChange={(e) => set(i, { topics: e.target.value.split('\n').map((t) => t.trim()).filter(Boolean) })}
          />
        </div>
      ))}
      {!disabled && (
        <Button type="button" size="sm" variant="outline" onClick={() => onChange([...value, { unit: value.length + 1, title: '', topics: [], hours: null }])}>
          <Plus className="h-4 w-4" /> Unit
        </Button>
      )}
    </div>
  );
}
