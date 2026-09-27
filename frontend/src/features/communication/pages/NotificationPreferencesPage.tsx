import { useEffect, useState } from 'react';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select } from '@/components/ui/Input';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { Checkbox } from '@/components/ui/Switch';
import { toast } from '@/components/ui/Toaster';
import { titleCase } from '@/utils/formatters';
import { commsApi } from '../api';
import { useCommsMutation, usePreferences } from '../hooks';
import type { Channel, PreferenceItem } from '../types';

const EXTERNAL: Channel[] = ['sms', 'whatsapp', 'email', 'push'];

/** /profile/notifications — categories × channels, quiet hours, digest (Prompts/04 §04.9). */
export default function NotificationPreferencesPage() {
  const prefs = usePreferences();
  const [items, setItems] = useState<PreferenceItem[]>([]);
  const save = useCommsMutation((v: PreferenceItem[]) => commsApi.savePreferences(v), ['notification-preferences']);
  useEffect(() => {
    if (prefs.data) setItems(prefs.data.data.items);
  }, [prefs.data]);
  if (prefs.isLoading) return <PageSkeleton />;
  const set = (i: number, patch: Partial<PreferenceItem>) => setItems(items.map((it, j) => (j === i ? { ...it, ...patch } : it)));
  return (
    <div className="space-y-4">
      <PageHeader
        title="Notification preferences"
        description="In-app notifications are always kept. Security and emergency messages cannot be switched off."
        actions={<Button loading={save.isPending} onClick={() => save.mutate(items, { onSuccess: () => toast.success('Preferences saved'), onError: (e) => toast.error(getApiError(e)) })}>Save</Button>}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-muted-foreground">
            <tr>
              <th className="p-2">Category</th>
              {EXTERNAL.map((c) => (
                <th key={c} className="p-2 text-center">{c}</th>
              ))}
              <th className="p-2">Quiet hours</th>
              <th className="p-2">Digest</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {items.map((it, i) => (
              <tr key={it.category}>
                <td className="p-2">
                  {titleCase(it.category)} {it.mandatory && <Badge variant="outline">mandatory</Badge>}
                </td>
                {EXTERNAL.map((c) => (
                  <td key={c} className="p-2 text-center">
                    <Checkbox
                      disabled={it.mandatory}
                      checked={it.channels.includes(c)}
                      aria-label={`${it.category} ${c}`}
                      onCheckedChange={(on) => set(i, { channels: on ? [...it.channels, c] : it.channels.filter((x) => x !== c) })}
                    />
                  </td>
                ))}
                <td className="p-2">
                  <div className="flex items-center gap-1">
                    <Input type="time" className="w-28" disabled={it.mandatory} value={it.quiet_hours?.from ?? ''} onChange={(e) => set(i, { quiet_hours: e.target.value ? { from: e.target.value, to: it.quiet_hours?.to ?? '08:00' } : null })} />
                    –
                    <Input type="time" className="w-28" disabled={it.mandatory || !it.quiet_hours} value={it.quiet_hours?.to ?? ''} onChange={(e) => it.quiet_hours && set(i, { quiet_hours: { from: it.quiet_hours.from, to: e.target.value } })} />
                  </div>
                </td>
                <td className="p-2">
                  <Select className="w-28" disabled={it.mandatory} value={it.digest} options={['none', 'daily', 'weekly'].map((d) => ({ value: d, label: d }))} onChange={(e) => set(i, { digest: e.target.value as PreferenceItem['digest'] })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
