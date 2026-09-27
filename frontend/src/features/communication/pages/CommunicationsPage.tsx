import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { BarChart3, Plus, Send } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { DataTable } from '@/components/shared/DataTable';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input, Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Checkbox } from '@/components/ui/Switch';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { formatRelative } from '@/utils/formatters';
import { commsApi } from '../api';
import { AudienceBuilder } from '../components/AudienceBuilder';
import { RichTextEditor } from '../components/RichTextEditor';
import { useAnnouncements, useCommsMutation, useLogs, useTemplates } from '../hooks';
import { CHANNELS, EMPTY_AUDIENCE, type AudienceRules, type Channel, type MessageLog, type NotificationTemplate } from '../types';

const onErr = (e: unknown) => toast.error(getApiError(e));

function ChannelToggles({ value, onChange }: { value: Channel[]; onChange: (v: Channel[]) => void }) {
  return (
    <div className="flex flex-wrap gap-3 text-sm">
      {CHANNELS.map((c) => (
        <label key={c} className="flex items-center gap-1">
          <Checkbox checked={value.includes(c)} onCheckedChange={(on) => onChange(on ? [...value, c] : value.filter((x) => x !== c))} />
          {c}
        </label>
      ))}
    </div>
  );
}

// ---- Templates ---------------------------------------------------------------------------------------------------------
function TemplatesTab() {
  const { can } = usePermission();
  const [event, setEvent] = useState('');
  const list = useTemplates({ event_trigger: event || undefined });
  const [editing, setEditing] = useState<NotificationTemplate | null>(null);
  const [draft, setDraft] = useState({ name: '', subject_template: '', body_template: '', channels: [] as Channel[], variables: '', dlt_template_id: '', whatsapp_template_name: '' });
  const [context, setContext] = useState('{}');
  const [preview, setPreview] = useState<{ subject: string | null; body: string; missing_variables: string[] } | null>(null);
  const save = useCommsMutation(
    () => {
      const body = {
        name: draft.name,
        subject_template: draft.subject_template || null,
        body_template: draft.body_template,
        channels: draft.channels,
        variables: draft.variables.split(',').map((s) => s.trim()).filter(Boolean),
        dlt_template_id: draft.dlt_template_id || null,
        whatsapp_template_name: draft.whatsapp_template_name || null,
      };
      return editing!.is_platform
        ? commsApi.createTemplate({ ...body, event_trigger: editing!.event_trigger, language: editing!.language })
        : commsApi.updateTemplate(editing!.id, body);
    },
    ['comm-templates'],
  );
  const activate = useCommsMutation((id: string) => commsApi.activateTemplate(id), ['comm-templates']);
  const open = (t: NotificationTemplate) => {
    setEditing(t);
    setPreview(null);
    setContext(JSON.stringify(Object.fromEntries((t.variables ?? []).map((v) => [v, `<${v}>`])), null, 2));
    setDraft({
      name: t.name,
      subject_template: t.subject_template ?? '',
      body_template: t.body_template,
      channels: t.channels,
      variables: (t.variables ?? []).join(', '),
      dlt_template_id: t.dlt_template_id ?? '',
      whatsapp_template_name: t.whatsapp_template_name ?? '',
    });
  };
  const runPreview = async () => {
    try {
      const r = await commsApi.previewTemplate(editing!.id, JSON.parse(context || '{}'));
      setPreview(r.data);
    } catch (e) {
      onErr(e);
    }
  };
  const manage = can('communication', 'template_manage');
  return (
    <div className="space-y-3">
      <Input className="w-72" placeholder="Filter by event (e.g. fees.payment_received)" value={event} onChange={(e) => setEvent(e.target.value)} />
      <table className="w-full text-sm">
        <thead className="text-left text-muted-foreground">
          <tr>
            <th className="p-2">Event</th>
            <th className="p-2">Name</th>
            <th className="p-2">Lang</th>
            <th className="p-2">Channels</th>
            <th className="p-2">Version</th>
            <th />
          </tr>
        </thead>
        <tbody className="divide-y">
          {(list.data?.data ?? []).map((t) => (
            <tr key={t.id}>
              <td className="p-2 font-mono text-xs">{t.event_trigger}</td>
              <td className="p-2">
                {t.name} {t.is_platform ? <Badge variant="outline">platform</Badge> : <Badge variant="info">institution</Badge>}
              </td>
              <td className="p-2">{t.language}</td>
              <td className="p-2 text-xs">{t.channels.join(', ')}</td>
              <td className="p-2">v{t.version}</td>
              <td className="p-2 text-right">
                <Button size="sm" variant="ghost" onClick={() => open(t)}>
                  {manage ? (t.is_platform ? 'Override' : 'Edit') : 'View'}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Modal
        open={editing !== null}
        onOpenChange={(o) => !o && setEditing(null)}
        size="xl"
        title={editing ? `${editing.event_trigger} (${editing.language})` : ''}
        description={editing?.is_platform ? 'Platform default — saving creates an institution override.' : 'Saving creates a new version.'}
        footer={
          <>
            {editing && !editing.is_platform && !editing.is_active && manage && (
              <Button variant="outline" onClick={() => activate.mutate(editing.id, { onSuccess: () => toast.success('Activated'), onError: onErr })}>
                Activate this version
              </Button>
            )}
            <Button variant="outline" onClick={runPreview}>
              Preview
            </Button>
            {manage && (
              <Button loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => { toast.success('Saved'); setEditing(null); }, onError: onErr })}>
                Save
              </Button>
            )}
          </>
        }
      >
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="space-y-3">
            <FormField label="Name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            <FormField label="Subject" value={draft.subject_template} onChange={(e) => setDraft({ ...draft, subject_template: e.target.value })} />
            <label className="block space-y-1 text-sm font-medium">
              Body (Jinja2 — {'{{ variable }}'})
              <Textarea rows={6} className="font-mono text-xs" value={draft.body_template} onChange={(e) => setDraft({ ...draft, body_template: e.target.value })} />
            </label>
            <div className="flex flex-wrap gap-1">
              {draft.variables.split(',').map((v) => v.trim()).filter(Boolean).map((v) => (
                <button key={v} type="button" className="rounded border px-2 py-0.5 font-mono text-xs hover:bg-accent" onClick={() => setDraft({ ...draft, body_template: `${draft.body_template}{{ ${v} }}` })}>
                  {v}
                </button>
              ))}
            </div>
            <FormField label="Variables (comma separated)" value={draft.variables} onChange={(e) => setDraft({ ...draft, variables: e.target.value })} />
            <ChannelToggles value={draft.channels} onChange={(channels) => setDraft({ ...draft, channels })} />
            <div className="grid grid-cols-2 gap-2">
              <FormField label="DLT template id" value={draft.dlt_template_id} onChange={(e) => setDraft({ ...draft, dlt_template_id: e.target.value })} />
              <FormField label="WhatsApp template" value={draft.whatsapp_template_name} onChange={(e) => setDraft({ ...draft, whatsapp_template_name: e.target.value })} />
            </div>
          </div>
          <div className="space-y-2">
            <label className="block space-y-1 text-sm font-medium">
              Sample context (JSON)
              <Textarea rows={6} className="font-mono text-xs" value={context} onChange={(e) => setContext(e.target.value)} />
            </label>
            {preview && (
              <div className="rounded-md border p-3 text-sm">
                {preview.subject && <p className="font-semibold">{preview.subject}</p>}
                <p className="whitespace-pre-wrap">{preview.body}</p>
                {preview.missing_variables.length > 0 && <p className="mt-2 text-xs text-destructive">Missing: {preview.missing_variables.join(', ')}</p>}
              </div>
            )}
          </div>
        </div>
      </Modal>
    </div>
  );
}

// ---- Logs --------------------------------------------------------------------------------------------------------------
function LogsTab() {
  const [params, setParams] = useState<{ page: number; page_size: number; channel?: string; status?: string; recipient?: string }>({ page: 1, page_size: 25 });
  const logs = useLogs(params);
  const [detail, setDetail] = useState<MessageLog | null>(null);
  const columns = useMemo<ColumnDef<MessageLog, unknown>[]>(
    () => [
      { accessorKey: 'created_at', header: 'When', cell: ({ getValue }) => formatRelative(String(getValue())) },
      { accessorKey: 'channel', header: 'Channel' },
      { accessorKey: 'recipient', header: 'Recipient' },
      { accessorKey: 'event_type', header: 'Event' },
      { accessorKey: 'provider', header: 'Provider' },
      { accessorKey: 'status', header: 'Status', cell: ({ getValue }) => <StatusBadge status={String(getValue())} /> },
    ],
    [],
  );
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <Select className="w-40" placeholder="All channels" options={CHANNELS.map((c) => ({ value: c, label: c }))} onChange={(e) => setParams({ ...params, channel: e.target.value || undefined, page: 1 })} />
        <Select className="w-40" placeholder="All statuses" options={['queued', 'deferred', 'sent', 'delivered', 'failed', 'bounced', 'read'].map((s) => ({ value: s, label: s }))} onChange={(e) => setParams({ ...params, status: e.target.value || undefined, page: 1 })} />
        <Input className="w-56" placeholder="Recipient contains…" onChange={(e) => setParams({ ...params, recipient: e.target.value || undefined, page: 1 })} />
      </div>
      <DataTable
        columns={columns}
        data={logs.data?.data ?? []}
        isLoading={logs.isLoading}
        pagination={logs.data?.meta.pagination}
        onPageChange={(page) => setParams({ ...params, page })}
        onPageSizeChange={(page_size) => setParams({ ...params, page_size, page: 1 })}
        onRowClick={setDetail}
        rowKey={(r) => r.id}
      />
      <Modal open={detail !== null} onOpenChange={(o) => !o && setDetail(null)} title="Message" description={detail?.id}>
        {detail && (
          <dl className="grid grid-cols-3 gap-2 text-sm">
            {(['channel', 'recipient', 'status', 'provider', 'provider_message_id', 'subject', 'body_preview', 'error', 'sent_at', 'delivered_at', 'cost_paise'] as const).map((k) => (
              <div key={k} className="contents">
                <dt className="text-muted-foreground">{k}</dt>
                <dd className="col-span-2 break-words">{String(detail[k] ?? '—')}</dd>
              </div>
            ))}
          </dl>
        )}
      </Modal>
    </div>
  );
}

// ---- Announcements (admin) ---------------------------------------------------------------------------------------------
function AnnouncementsTab() {
  const list = useAnnouncements({ scope: 'all', page_size: 50 });
  const [composing, setComposing] = useState(false);
  const [draft, setDraft] = useState({ title: '', body: '', requires_ack: false, is_pinned: false, audience: EMPTY_AUDIENCE as AudienceRules, channels: ['in_app', 'push'] as Channel[] });
  const create = useCommsMutation(async () => {
    const a = await commsApi.createAnnouncement({ title: draft.title, body: draft.body, requires_ack: draft.requires_ack, is_pinned: draft.is_pinned, audience_rules: draft.audience });
    return commsApi.publishAnnouncement(a.data.id, draft.channels);
  }, ['announcements']);
  return (
    <div className="space-y-3">
      <Button onClick={() => setComposing(true)}>
        <Plus className="h-4 w-4" /> New announcement
      </Button>
      <ul className="divide-y rounded-md border">
        {(list.data?.data ?? []).map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-2 p-3 text-sm">
            <span>
              <b>{a.title}</b> {a.is_pinned && <Badge variant="info">pinned</Badge>} {a.requires_ack && <Badge variant="outline">ack</Badge>}
            </span>
            <span className="flex items-center gap-2">
              <StatusBadge status={a.status} />
              <StatsButton id={a.id} />
            </span>
          </li>
        ))}
      </ul>
      <Modal
        open={composing}
        onOpenChange={setComposing}
        size="xl"
        title="New announcement"
        footer={
          <Button loading={create.isPending} disabled={!draft.title || !draft.body} onClick={() => create.mutate(undefined, { onSuccess: () => { toast.success('Published'); setComposing(false); }, onError: onErr })}>
            Publish
          </Button>
        }
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="space-y-3">
            <FormField label="Title" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
            <RichTextEditor value={draft.body} onChange={(body) => setDraft({ ...draft, body })} />
            <div className="flex gap-4 text-sm">
              <label className="flex items-center gap-2">
                <Checkbox checked={draft.requires_ack} onCheckedChange={(c) => setDraft({ ...draft, requires_ack: c === true })} /> Requires acknowledgement
              </label>
              <label className="flex items-center gap-2">
                <Checkbox checked={draft.is_pinned} onCheckedChange={(c) => setDraft({ ...draft, is_pinned: c === true })} /> Pinned
              </label>
            </div>
            <ChannelToggles value={draft.channels} onChange={(channels) => setDraft({ ...draft, channels })} />
          </div>
          <AudienceBuilder value={draft.audience} onChange={(audience) => setDraft({ ...draft, audience })} />
        </div>
      </Modal>
    </div>
  );
}

function StatsButton({ id }: { id: string }) {
  const [stats, setStats] = useState<{ total: number; read: number; acknowledged: number } | null>(null);
  return stats ? (
    <span className="text-xs text-muted-foreground">
      {stats.read}/{stats.total} read · {stats.acknowledged} ack
    </span>
  ) : (
    <Button size="icon" variant="ghost" aria-label="Stats" onClick={async () => setStats((await commsApi.announcementStats(id)).data)}>
      <BarChart3 className="h-4 w-4" />
    </Button>
  );
}

// ---- DLT / WhatsApp ----------------------------------------------------------------------------------------------------
function RegistriesTab() {
  const smsOn = useFeature('comms.sms');
  const waOn = useFeature('comms.whatsapp');
  const [dlt, setDlt] = useState({ sender_id: '', template_id: '', template_text: '' });
  const [wa, setWa] = useState({ name: '', body: '' });
  const [dltRows, setDltRows] = useState<{ id: string; template_id: string; sender_id: string; status: string }[] | null>(null);
  const [waRows, setWaRows] = useState<{ id: string; name: string; status: string }[] | null>(null);
  const load = useCallback(async () => {
    if (smsOn) setDltRows((await commsApi.dlt()).data);
    if (waOn) setWaRows((await commsApi.whatsapp()).data);
  }, [smsOn, waOn]);
  useEffect(() => {
    void load();
  }, [load]);
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="space-y-2">
        <h3 className="font-semibold">DLT templates (India SMS)</h3>
        {!smsOn && <p className="text-sm text-muted-foreground">SMS is disabled for the institution.</p>}
        {smsOn && (
          <>
            <ul className="divide-y rounded-md border text-sm">
              {(dltRows ?? []).map((d) => (
                <li key={d.id} className="flex justify-between p-2">
                  <span className="font-mono">{d.template_id}</span>
                  <span>
                    {d.sender_id} <StatusBadge status={d.status} />
                  </span>
                </li>
              ))}
            </ul>
            <div className="grid gap-2 sm:grid-cols-2">
              <Input placeholder="Sender id" value={dlt.sender_id} onChange={(e) => setDlt({ ...dlt, sender_id: e.target.value })} />
              <Input placeholder="DLT template id" value={dlt.template_id} onChange={(e) => setDlt({ ...dlt, template_id: e.target.value })} />
              <Textarea className="sm:col-span-2" rows={2} placeholder="Registered text with {#var#}" value={dlt.template_text} onChange={(e) => setDlt({ ...dlt, template_text: e.target.value })} />
            </div>
            <Button size="sm" onClick={async () => { try { await commsApi.createDlt(dlt); toast.success('Registered'); await load(); } catch (e) { onErr(e); } }}>
              Register
            </Button>
          </>
        )}
      </section>
      <section className="space-y-2">
        <h3 className="font-semibold">WhatsApp templates</h3>
        {!waOn && <p className="text-sm text-muted-foreground">WhatsApp is disabled for the institution.</p>}
        {waOn && (
          <>
            <ul className="divide-y rounded-md border text-sm">
              {(waRows ?? []).map((w) => (
                <li key={w.id} className="flex items-center justify-between p-2">
                  <span className="font-mono">{w.name}</span>
                  <span className="flex items-center gap-2">
                    <StatusBadge status={w.status} />
                    <Button size="sm" variant="ghost" onClick={async () => { await commsApi.syncWhatsapp(w.id); await load(); }}>
                      Sync
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
            <Input placeholder="name_in_snake_case" value={wa.name} onChange={(e) => setWa({ ...wa, name: e.target.value })} />
            <Textarea rows={2} placeholder="Body with {{1}} placeholders" value={wa.body} onChange={(e) => setWa({ ...wa, body: e.target.value })} />
            <Button size="sm" onClick={async () => { try { await commsApi.createWhatsapp({ ...wa, category: 'utility' }); toast.success('Submitted'); await load(); } catch (e) { onErr(e); } }}>
              Submit for approval
            </Button>
          </>
        )}
      </section>
    </div>
  );
}

// ---- Send --------------------------------------------------------------------------------------------------------------
function SendTab() {
  const [event, setEvent] = useState('announcement.published');
  const [context, setContext] = useState('{"title": "Notice", "summary": "…"}');
  const [audience, setAudience] = useState<AudienceRules>(EMPTY_AUDIENCE);
  const [channels, setChannels] = useState<Channel[]>(['in_app']);
  const send = useCommsMutation(
    () =>
      commsApi.send({
        event_type: event,
        context: JSON.parse(context || '{}'),
        channels,
        audience: { roles: audience.roles, user_ids: audience.user_ids, college_id: audience.college_ids[0], department_id: audience.department_ids[0] },
      }),
    ['comm-logs'],
  );
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="space-y-3">
        <FormField label="Event" value={event} onChange={(e) => setEvent(e.target.value)} />
        <label className="block space-y-1 text-sm font-medium">
          Context (JSON)
          <Textarea rows={5} className="font-mono text-xs" value={context} onChange={(e) => setContext(e.target.value)} />
        </label>
        <ChannelToggles value={channels} onChange={setChannels} />
        <Button loading={send.isPending} onClick={() => send.mutate(undefined, { onSuccess: () => toast.success('Queued'), onError: onErr })}>
          <Send className="h-4 w-4" /> Send
        </Button>
      </div>
      <AudienceBuilder value={audience} onChange={setAudience} />
    </div>
  );
}

/** /admin/communications — Templates · Logs · Announcements · DLT / WhatsApp · Send (Prompts/04 §04.9). */
export default function CommunicationsPage() {
  const { can } = usePermission();
  return (
    <div className="space-y-4">
      <PageHeader title="Communications" description="Templates, delivery logs, announcements, provider registries and ad-hoc sends." />
      <Tabs defaultValue="templates">
        <TabsList className="h-auto flex-wrap">
          <TabsTrigger value="templates">Templates</TabsTrigger>
          {can('communication', 'view_all') && <TabsTrigger value="logs">Logs</TabsTrigger>}
          {can('communication', 'create') && <TabsTrigger value="announcements">Announcements</TabsTrigger>}
          {can('communication', 'template_manage') && <TabsTrigger value="registries">DLT / WhatsApp</TabsTrigger>}
          {can('communication', 'send') && <TabsTrigger value="send">Send</TabsTrigger>}
        </TabsList>
        <TabsContent value="templates">
          <TemplatesTab />
        </TabsContent>
        <TabsContent value="logs">
          <LogsTab />
        </TabsContent>
        <TabsContent value="announcements">
          <AnnouncementsTab />
        </TabsContent>
        <TabsContent value="registries">
          <RegistriesTab />
        </TabsContent>
        <TabsContent value="send">
          <SendTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
