import { useState } from 'react';
import { Input } from '@/components/ui/Input';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
export type SettingKind = 'bool' | 'int' | 'str' | 'enum' | 'json' | 'list' | 'money' | 'duration';

/**
 * Type-aware control for one setting (Prompts/37 §37.9 `SettingsField` library) — bool / int / string / enum / json /
 * list / money (paise, edited in ₹) / duration (minutes). Module settings pages reuse it; validation stays on the API.
 */
export function SettingsField({ type, value, choices = [], min, max, disabled, onChange }: {
  type: SettingKind | string;
  value: Any;
  choices?: string[];
  min?: number | null;
  max?: number | null;
  disabled?: boolean;
  onChange: (v: Any) => void;
}) {
  const [text, setText] = useState(() => (type === 'json' || type === 'list' ? JSON.stringify(value ?? (type === 'list' ? [] : {}), null, 1) : ''));
  const [bad, setBad] = useState(false);
  const cls = 'h-9 rounded-md border bg-background px-2 text-sm';
  if (type === 'bool') return <input type="checkbox" className="h-4 w-4" checked={!!value} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />;
  if (type === 'enum')
    return (
      <select className={cls} value={value ?? ''} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {choices.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    );
  if (type === 'int' || type === 'duration')
    return <Input type="number" className="w-32" value={value ?? ''} min={min ?? undefined} max={max ?? undefined} disabled={disabled} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />;
  if (type === 'money')
    return <Input type="number" className="w-40" step="0.01" value={value == null ? '' : Number(value) / 100} disabled={disabled} onChange={(e) => onChange(e.target.value === '' ? null : Math.round(Number(e.target.value) * 100))} />;
  if (type === 'json' || type === 'list')
    return (
      <div className="w-full">
        <textarea
          className={`min-h-[72px] w-full rounded-md border bg-background p-2 font-mono text-xs ${bad ? 'border-destructive' : ''}`}
          value={text}
          disabled={disabled}
          onChange={(e) => {
            setText(e.target.value);
            try {
              const v = JSON.parse(e.target.value);
              setBad(type === 'list' && !Array.isArray(v));
              onChange(v);
            } catch {
              setBad(true);
            }
          }}
        />
        {bad && <p className="text-xs text-destructive">{type === 'list' ? 'Must be a JSON array' : 'Invalid JSON'}</p>}
      </div>
    );
  return <Input value={value ?? ''} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
}
