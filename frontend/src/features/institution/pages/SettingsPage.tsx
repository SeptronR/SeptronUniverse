import { useEffect, useState } from 'react';
import { Send } from 'lucide-react';
import { getApiError } from '@/api/axios';
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
import { titleCase } from '@/utils/formatters';
import { institutionApi } from '../api';
import { useInstMutation, useSettings } from '../hooks';
import type { SettingItem } from '../types';

type Draft = Record<string, unknown>;
const k = (s: SettingItem) => `${s.category}.${s.key}`;

function SettingInput({ item, value, onChange, disabled }: { item: SettingItem; value: unknown; onChange: (v: unknown) => void; disabled: boolean }) {
  switch (item.value_type) {
    case 'bool':
      return <Switch checked={value === true} disabled={disabled} onCheckedChange={onChange} aria-label={item.key} />;
    case 'int':
      return <Input type="number" className="w-40" disabled={disabled} value={value == null ? '' : String(value)} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />;
    case 'enum':
      return <Select className="w-56" disabled={disabled} value={String(value ?? '')} options={item.choices.map((c) => ({ value: c, label: c }))} onChange={(e) => onChange(e.target.value)} />;
    case 'list':
      return <Input disabled={disabled} placeholder="comma separated" value={Array.isArray(value) ? value.join(', ') : ''} onChange={(e) => onChange(e.target.value ? e.target.value.split(',').map((s) => s.trim()).filter(Boolean) : null)} />;
    case 'json':
      return <JsonInput value={value} onChange={onChange} disabled={disabled} />;
    default:
      return <Input disabled={disabled} value={value == null ? '' : String(value)} onChange={(e) => onChange(e.target.value || null)} />;
  }
}

function JsonInput({ value, onChange, disabled }: { value: unknown; onChange: (v: unknown) => void; disabled: boolean }) {
  const [text, setText] = useState(() => (value == null ? '' : JSON.stringify(value, null, 2)));
  const [error, setError] = useState<string | null>(null);
  return (
    <div>
      <Textarea
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

/** Theme / table-style live preview: applies the picked values to <html> without saving. */
function ThemePreview({ theme, tableStyle }: { theme: unknown; tableStyle: unknown }) {
  useEffect(() => {
    const root = document.documentElement;
    const prev = { theme: root.dataset.theme, table: root.dataset.tableStyle };
    if (theme) root.dataset.theme = String(theme);
    if (tableStyle) root.dataset.tableStyle = String(tableStyle);
    return () => {
      if (prev.theme) root.dataset.theme = prev.theme;
      if (prev.table) root.dataset.tableStyle = prev.table;
    };
  }, [theme, tableStyle]);
  return (
    <div className="rounded-md border p-3">
      <p className="mb-2 text-xs text-muted-foreground">Live preview</p>
      <div className="flex items-center gap-2">
        <Button size="sm">Primary</Button>
        <Badge>Badge</Badge>
        <table className="text-xs">
          <tbody>
            <tr><td className="border px-2">Row 1</td><td className="border px-2">A</td></tr>
            <tr><td className="border px-2">Row 2</td><td className="border px-2">B</td></tr>
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
        onSuccess: () => { toast.success('Settings saved'); setDraft({}); },
        onError: (e) => toast.error(getApiError(e)),
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
              {titleCase(c.category)}
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
                      <p className="flex items-center gap-2 text-sm font-medium">
                        {s.label ?? titleCase(s.key)}
                        {s.is_public && <Badge variant="info">public</Badge>}
                        {!s.is_default && <Badge variant="outline">customised</Badge>}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {k(s)} · {s.value_type}
                        {s.default != null ? ` · default ${JSON.stringify(s.default)}` : ''}
                      </p>
                    </div>
                    <SettingInput item={s} value={valueOf(s)} disabled={locked} onChange={(v) => setDraft({ ...draft, [k(s)]: v })} />
                  </div>
                );
              })}
            </div>
            {c.category === 'communication' && manage && (
              <div className="flex flex-wrap items-center gap-2 rounded-md border p-3">
                <Input className="w-64" placeholder="+91… or email" value={to} onChange={(e) => setTo(e.target.value)} />
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
