import { useState, type DragEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Plus, Send } from 'lucide-react';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { StaffPicker } from '@/features/institution/components/StaffPicker';
import { useDepartments } from '@/features/institution/hooks';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Select, Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { toast } from '@/components/ui/Toaster';
import { hrApi } from '../api';
import { useHrMutation } from '../hooks';
import { label, num, type Application, localDate } from '../types';

const STAGES = ['applied', 'screened', 'shortlisted', 'interviewed', 'selected', 'offered', 'joined'] as const;
// drag target → API action (+ the body each action needs)
const ACTION: Record<string, string> = { screened: 'screen', shortlisted: 'shortlist', selected: 'select', offered: 'offer', joined: 'join', rejected: 'reject' };

/** /admin/hr/recruitment — postings (reservation roster), pipeline kanban (drag between stages), panels & scores. */
export default function RecruitmentPage() {
  const postings = useQuery({ queryKey: ['recruitment', 'postings'], queryFn: () => hrApi.postings({ page_size: 100 }) });
  const departments = useDepartments({ scope: 'all', page_size: 200 });
  const [selected, setSelected] = useState<string | null>(null);
  const apps = useQuery({ queryKey: ['recruitment', 'apps', selected], queryFn: () => hrApi.applications(selected!), enabled: !!selected });
  const panels = useQuery({ queryKey: ['recruitment', 'panels', selected], queryFn: () => hrApi.panels(selected!), enabled: !!selected });
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState({ title: '', department_id: '', cadre: 'assistant', vacancies: 1, reservation: 'GEN:1', closes_at: '', description: '' });
  const [panelOpen, setPanelOpen] = useState(false);
  const [panel, setPanel] = useState<{ scheduled_at: string; venue: string; members: { user_id: string; name: string }[] }>({ scheduled_at: '', venue: '', members: [] });
  const [scoring, setScoring] = useState<Application | null>(null);
  const [scores, setScores] = useState({ subject: '', teaching: '' });
  const create = useHrMutation(() => {
    const vac: Record<string, number> = {};
    draft.reservation.split(',').map((x) => x.trim()).filter(Boolean).forEach((x) => { const [k, v] = x.split(':'); vac[k.trim()] = Number(v); });
    return hrApi.createPosting({ title: draft.title, department_id: draft.department_id || undefined, cadre: draft.cadre, vacancies: draft.vacancies, reservation: { roster: '100_point', vacancies: vac }, closes_at: draft.closes_at ? new Date(draft.closes_at).toISOString() : undefined, description: draft.description || undefined });
  }, ['recruitment']);
  const action = useHrMutation(({ id, act, body }: { id: string; act: string; body?: Record<string, unknown> }) => hrApi.appAction(id, act, body), ['recruitment', 'staff']);
  const postingAct = useHrMutation(({ id, act }: { id: string; act: 'publish' | 'close' | 'cancel' }) => hrApi.postingAction(id, act), ['recruitment']);
  const createPanel = useHrMutation(() => hrApi.createPanel(selected!, { scheduled_at: new Date(panel.scheduled_at).toISOString(), venue: panel.venue || undefined, members: panel.members.map((m) => ({ user_id: m.user_id })) }), ['recruitment']);
  const score = useHrMutation(() => hrApi.score(panels.data!.data[0].id, { application_id: scoring!.id, scores: { subject: Number(scores.subject), teaching: Number(scores.teaching) } }), ['recruitment']);

  const move = (app: Application, to: string) => {
    const act = ACTION[to];
    if (!act) return toast.error(`Scores move an application to ${to}`);
    const body: Record<string, unknown> =
      act === 'screen' ? { screening_score: Number(window.prompt('Screening score (0–100)', '60') ?? 0) }
        : act === 'shortlist' ? { application_ids: [app.id] }
        : act === 'join' ? { joining_date: localDate() }
        : {};
    action.mutate({ id: app.id, act, body }, { onSuccess: (r) => toast.success(`${app.name} → ${r.data.status}`), onError: (e) => toast.error(getApiError(e)) });
  };
  const onDrop = (e: DragEvent, to: string) => {
    const app = apps.data?.data.find((a) => a.id === e.dataTransfer.getData('text/plain'));
    if (app && app.status !== to) move(app, to);
  };
  const current = postings.data?.data.find((p) => p.id === selected);

  return (
    <div className="space-y-4">
      <PageHeader title="Recruitment" description="Postings with reservation roster, public careers page, screening → panel → offer → joining." actions={<Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" /> New posting</Button>} />
      <div className="grid gap-3 md:grid-cols-3">
        {(postings.data?.data ?? []).map((p) => (
          <Card key={p.id} className={selected === p.id ? 'ring-2 ring-primary' : ''} onClick={() => setSelected(p.id)} role="button">
            <CardHeader>
              <CardTitle className="flex items-center justify-between text-base">{p.title} <StatusBadge status={p.status} /></CardTitle>
              <p className="text-xs text-muted-foreground">{p.department_code ?? '—'} · {label(p.cadre)} · {p.vacancies} post(s) · {Object.entries(p.reservation?.vacancies ?? {}).map(([k, v]) => `${k} ${v}`).join(', ')}</p>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-1 text-xs">
              {Object.entries(p.pipeline).map(([k, v]) => <Badge key={k} variant="outline">{k} {v}</Badge>)}
              {p.status === 'draft' && <Button size="sm" onClick={(e) => { e.stopPropagation(); postingAct.mutate({ id: p.id, act: 'publish' }, { onSuccess: () => toast.success('Published on /careers'), onError: (er) => toast.error(getApiError(er)) }); }}><Send className="h-3 w-3" /> Publish</Button>}
              {p.status === 'open' && <Button size="sm" variant="outline" onClick={(e) => { e.stopPropagation(); postingAct.mutate({ id: p.id, act: 'close' }); }}>Close</Button>}
            </CardContent>
          </Card>
        ))}
      </div>

      {current && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold">Pipeline · {current.title}</h2>
            <Button variant="outline" onClick={() => setPanelOpen(true)}>Interview panel ({panels.data?.data.length ?? 0})</Button>
          </div>
          <div className="grid gap-2 overflow-x-auto md:grid-cols-7">
            {STAGES.map((stage) => (
              <div key={stage} onDragOver={(e) => e.preventDefault()} onDrop={(e) => onDrop(e, stage)} className="min-h-40 rounded-md border bg-muted/30 p-2" aria-label={`${stage} column`}>
                <p className="mb-2 text-xs font-semibold uppercase text-muted-foreground">{stage}</p>
                {(apps.data?.data ?? []).filter((a) => a.status === stage).map((a) => (
                  <div key={a.id} draggable onDragStart={(e) => e.dataTransfer.setData('text/plain', a.id)} className="mb-2 cursor-grab rounded border bg-card p-2 text-xs shadow-xs">
                    <p className="font-medium">{a.name}</p>
                    <p className="text-muted-foreground">{a.category ?? 'GEN'} · screen {num(a.screening_score)} · interview {num(a.interview_total)}</p>
                    {(stage === 'shortlisted' || stage === 'interviewed') && panels.data?.data.length ? <button type="button" className="text-primary underline" onClick={() => setScoring(a)}>score</button> : null}
                    {stage !== 'joined' && (
                      <select
                        aria-label={`Move ${a.name ?? 'application'}`}
                        className="mt-1 w-full rounded border bg-background px-1 py-0.5 text-xs"
                        value=""
                        onChange={(e) => e.target.value && move(a, e.target.value)}
                      >
                        <option value="">Move to…</option>
                        {[...STAGES.slice(STAGES.indexOf(stage) + 1).filter((s) => ACTION[s]), 'rejected'].map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    )}
                  </div>
                ))}
              </div>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">Drag a card to the next stage (or use its Move to… menu). Rejected applications are hidden from the board.</p>
        </div>
      )}

      <Modal open={creating} onOpenChange={setCreating} title="New job posting" description="Reservation as CODE:posts, e.g. GEN:3, OBC-NCL:1 — validated against the roster when the roster feature is on." size="lg" footer={<Button loading={create.isPending} disabled={draft.title.length < 3} onClick={() => create.mutate(undefined, { onSuccess: () => { toast.success('Posting created (draft)'); setCreating(false); }, onError: (e) => toast.error(getApiError(e)) })}>Create</Button>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Title" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} className="sm:col-span-2" />
          <label className="space-y-1.5 text-sm font-medium">
            Department
            <Select placeholder="—" options={(departments.data?.data ?? []).map((d) => ({ value: d.id, label: d.code }))} value={draft.department_id} onChange={(e) => setDraft({ ...draft, department_id: e.target.value })} />
          </label>
          <label className="space-y-1.5 text-sm font-medium">
            Cadre
            <Select options={['assistant', 'associate', 'professor', 'lecturer'].map((c) => ({ value: c, label: label(c) }))} value={draft.cadre} onChange={(e) => setDraft({ ...draft, cadre: e.target.value })} />
          </label>
          <FormField label="Vacancies" type="number" min={1} value={draft.vacancies} onChange={(e) => setDraft({ ...draft, vacancies: Number(e.target.value) })} />
          <FormField label="Reservation" value={draft.reservation} onChange={(e) => setDraft({ ...draft, reservation: e.target.value })} />
          <FormField label="Closes at" type="datetime-local" value={draft.closes_at} onChange={(e) => setDraft({ ...draft, closes_at: e.target.value })} />
          <label className="space-y-1.5 text-sm font-medium sm:col-span-2">
            Description
            <Textarea value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
          </label>
        </div>
      </Modal>

      <Modal open={panelOpen} onOpenChange={setPanelOpen} title="Interview panel" footer={<Button disabled={!panel.scheduled_at || panel.members.length === 0} onClick={() => createPanel.mutate(undefined, { onSuccess: () => { toast.success('Panel created'); setPanelOpen(false); }, onError: (e) => toast.error(getApiError(e)) })}>Create panel</Button>}>
        <div className="space-y-3">
          {(panels.data?.data ?? []).map((p) => <p key={p.id} className="text-sm">{new Date(p.scheduled_at).toLocaleString()} · {p.venue} · {p.members.map((m) => m.name).join(', ')}</p>)}
          <FormField label="When" type="datetime-local" value={panel.scheduled_at} onChange={(e) => setPanel({ ...panel, scheduled_at: e.target.value })} />
          <FormField label="Venue" value={panel.venue} onChange={(e) => setPanel({ ...panel, venue: e.target.value })} />
          <p className="text-sm">Members: {panel.members.map((m) => m.name).join(', ') || 'none'}</p>
          <StaffPicker onPick={(user_id, name) => setPanel({ ...panel, members: [...panel.members.filter((m) => m.user_id !== user_id), { user_id, name }] })} />
        </div>
      </Modal>

      <Modal open={scoring !== null} onOpenChange={(o) => !o && setScoring(null)} title={`Score · ${scoring?.name ?? ''}`} footer={<Button onClick={() => score.mutate(undefined, { onSuccess: (r) => { toast.success(`Total ${r.data.total}`); setScoring(null); }, onError: (e) => toast.error(getApiError(e)) })}>Save scores</Button>}>
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField label="Subject knowledge (0–100)" type="number" value={scores.subject} onChange={(e) => setScores({ ...scores, subject: e.target.value })} />
          <FormField label="Teaching (0–100)" type="number" value={scores.teaching} onChange={(e) => setScores({ ...scores, teaching: e.target.value })} />
        </div>
      </Modal>
    </div>
  );
}
