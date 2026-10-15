import { useState, type CSSProperties } from 'react';
import { Send } from 'lucide-react';
import { getApiError, getApiErrorDetails } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { Switch } from '@/components/ui/Switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { BRAND_RAMPS, type ThemeName } from '@/styles/themes';
import { titleCase } from '@/utils/formatters';
import { institutionApi } from '../api';
import { useInstMutation, useSettings } from '../hooks';
import type { SettingItem } from '../types';

type Draft = Record<string, unknown>;
const k = (s: SettingItem) => `${s.category}.${s.key}`;

function SettingInput({ item, value, onChange, disabled, invalid }: { item: SettingItem; value: unknown; onChange: (v: unknown) => void; disabled: boolean; invalid?: boolean }) {
  const a11y = { id: `setting-${k(item)}`, 'aria-invalid': invalid || undefined, 'aria-describedby': invalid ? `setting-${k(item)}-error` : undefined };
  switch (item.value_type) {
    case 'bool':
      return <Switch {...a11y} checked={value === true} disabled={disabled} onCheckedChange={onChange} />;
    case 'int':
      return <Input {...a11y} type="number" className="w-40" disabled={disabled} value={value == null ? '' : String(value)} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />;
    case 'enum':
      return <Select {...a11y} className="w-56" disabled={disabled} value={String(value ?? '')} options={item.choices.map((c) => ({ value: c, label: c }))} onChange={(e) => onChange(e.target.value)} />;
    case 'list':
      return <Input {...a11y} disabled={disabled} placeholder="comma separated" value={Array.isArray(value) ? value.join(', ') : ''} onChange={(e) => onChange(e.target.value ? e.target.value.split(',').map((s) => s.trim()).filter(Boolean) : null)} />;
    case 'json':
      return <JsonInput {...a11y} value={value} onChange={onChange} disabled={disabled} />;
    default:
      return <Input {...a11y} disabled={disabled} value={value == null ? '' : String(value)} onChange={(e) => onChange(e.target.value || null)} />;
  }
}

function JsonInput({ value, onChange, disabled, ...rest }: { value: unknown; onChange: (v: unknown) => void; disabled: boolean; id?: string }) {
  const [text, setText] = useState(() => (value == null ? '' : JSON.stringify(value, null, 2)));
  const [error, setError] = useState<string | null>(null);
  return (
    <div>
      <Textarea
        {...rest}
        rows={3}
        className="font-mono text-xs"
        disabled={disabled}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          try {
            onChange(e.target.value ? JSON.parse(e.target.value) : null);
            setError(null);
          } catch {
            setError('Invalid JSON');
          }
        }}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

/** Theme / table-style live preview, scoped to this box (the app theme stays the viewer's own until saved):
 * re-declares the brand ramp and the tokens derived from it, and sets data-table-style for the sample table. */
function ThemePreview({ theme, tableStyle }: { theme: unknown; tableStyle: unknown }) {
  const ramp = BRAND_RAMPS[(String(theme) as ThemeName)]?.ramp ?? BRAND_RAMPS.indigo.ramp;
  const dark = document.documentElement.classList.contains('dark');
  const vars = {
    ...Object.fromEntries(Object.entries(ramp).map(([step, rgb]) => [`--brand-${step}`, rgb])),
    '--primary': dark ? 'var(--brand-500)' : 'var(--brand-600)',
    '--accent': dark ? '30 41 59' : 'var(--brand-50)',
    '--accent-foreground': dark ? 'var(--brand-200)' : 'var(--brand-900)',
    '--ring': dark ? 'var(--brand-400)' : 'var(--brand-500)',
  } as CSSProperties;
  return (
    <div className="rounded-md border p-3" style={vars} data-table-style={String(tableStyle ?? 'default')} data-testid="theme-preview">
      <p className="mb-2 text-xs text-muted-foreground">Live preview</p>
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm">Primary</Button>
        <Badge>Badge</Badge>
        <span className="rounded bg-accent px-2 py-0.5 text-xs text-accent-foreground">Accent</span>
        <table className="data-table w-auto text-xs">
          <thead><tr><th>Name</th><th>Value</th></tr></thead>
          <tbody>
            <tr><td>Row 1</td><td>A</td></tr>
            <tr><td>Row 2</td><td>B</td></tr>
            <tr><td>Row 3</td><td>C</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** /admin/settings — tabbed by category with typed inputs, theme/table-style preview and provider test buttons. */
export default function SettingsPage() {
  const { can } = usePermission();
  const themesOn = useFeature('institution.themes');
  const settings = useSettings();
  const save = useInstMutation((items: { category: string; key: string; value: unknown }[]) => institutionApi.updateSettings(items), ['settings']);
  const test = useInstMutation(({ channel, to }: { channel: string; to: string }) => institutionApi.testProvider(channel, to), []);
  const [draft, setDraft] = useState<Draft>({});
  const [to, setTo] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const manage = can('settings', 'manage');

  if (settings.isLoading) return <PageSkeleton />;
  const cats = settings.data?.data ?? [];
  const valueOf = (s: SettingItem) => (k(s) in draft ? draft[k(s)] : s.value);
  const dirty = Object.keys(draft).length > 0;

  const onSave = () =>
    save.mutate(
      Object.entries(draft).map(([full, value]) => {
        const [category, ...rest] = full.split('.');
        return { category, key: rest.join('.'), value };
      }),
      {
        onSuccess: () => { toast.success('Settings saved'); setDraft({}); setFieldErrors({}); },
        onError: (e) => {
          const errs = (getApiErrorDetails(e).errors ?? []) as { field: string; reason: string }[];
          setFieldErrors(Object.fromEntries(errs.map((x) => [x.field, x.reason])));
          toast.error(errs.length ? `${getApiError(e)}: ${errs.map((x) => `${x.field} ${x.reason}`).join('; ')}` : getApiError(e));
        },
      },
    );

  return (
    <div className="space-y-4">
      <PageHeader
        title="Settings"
        description="Institution configuration by category. Public keys are exposed to the login page and website."
        actions={manage && <Button disabled={!dirty} loading={save.isPending} onClick={onSave}>Save changes</Button>}
      />
      <Tabs defaultValue={cats[0]?.category}>
        <TabsList className="flex-wrap h-auto">
          {cats.map((c) => (
            <TabsTrigger key={c.category} value={c.category}>
              {titleCase(c.category)}{c.items.some((s) => fieldErrors[k(s)]) && <span className="ml-1 text-destructive" aria-label="has errors">•</span>}
            </TabsTrigger>
          ))}
        </TabsList>
        {cats.map((c) => (
          <TabsContent key={c.category} value={c.category} className="space-y-3">
            {c.category === 'general' && <ThemePreview theme={valueOf(c.items.find((i) => i.key === 'theme')!)} tableStyle={valueOf(c.items.find((i) => i.key === 'table_style')!)} />}
            <div className="divide-y rounded-md border">
              {c.items.map((s) => {
                const locked = !manage || (!!s.feature && s.feature === 'institution.themes' && !themesOn);
                return (
                  <div key={k(s)} className="grid gap-2 p-3 sm:grid-cols-[1fr_minmax(0,22rem)] sm:items-center">
                    <div>
                      <label htmlFor={`setting-${k(s)}`} className="flex items-center gap-2 text-sm font-medium">
                        {s.label || titleCase(s.key)}
                        {s.is_public && <Badge variant="info">public</Badge>}
                        {!s.is_default && <Badge variant="outline">customised</Badge>}
                      </label>
                      <p className="text-xs text-muted-foreground">
                        {k(s)} · {s.value_type}
                        {s.default != null ? ` · default ${JSON.stringify(s.default)}` : ''}
                      </p>
                    </div>
                    <div>
                      <SettingInput
                        item={s}
                        value={valueOf(s)}
                        disabled={locked}
                        invalid={!!fieldErrors[k(s)]}
                        onChange={(v) => {
                          setDraft({ ...draft, [k(s)]: v });
                          if (fieldErrors[k(s)]) setFieldErrors(({ [k(s)]: _, ...rest }) => rest);
                        }}
                      />
                      {fieldErrors[k(s)] && <p id={`setting-${k(s)}-error`} role="alert" className="mt-1 text-xs text-destructive">{fieldErrors[k(s)]}</p>}
                    </div>
                  </div>
                );
              })}
            </div>
            {c.category === 'communication' && manage && (
              <div className="flex flex-wrap items-center gap-2 rounded-md border p-3">
                <Input className="w-64" aria-label="Test recipient (phone or email)" placeholder="+91… or email" value={to} onChange={(e) => setTo(e.target.value)} />
                {['sms', 'email', 'whatsapp', 'push'].map((ch) => (
                  <Button
                    key={ch}
                    size="sm"
                    variant="outline"
                    disabled={!to}
                    onClick={() =>
                      test.mutate(
                        { channel: ch, to },
                        {
                          onSuccess: (r) => toast.success(`${ch}: ${r.data.status} via ${r.data.provider}`),
                          onError: (e) => toast.error(getApiError(e)),
                        },
                      )
                    }
                  >
                    <Send className="h-4 w-4" /> Test {ch}
                  </Button>
                ))}
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}
