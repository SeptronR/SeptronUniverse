import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getApiError } from '@/api/axios';
import { FormField } from '@/components/shared/FormField';
import { PageHeader } from '@/components/shared/PageHeader';
import { ScopeTabs } from '@/components/shared/ScopeTabs';
import { StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Modal } from '@/components/ui/Modal';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { useFeature } from '@/hooks/useFeature';
import { usePermission } from '@/hooks/usePermission';
import { hrApi } from '../api';
import { SimpleTable, WorkflowPanel } from '../components/shared';
import { useHrMutation, useMyStaff } from '../hooks';
import { label, num, type Appraisal, type CasApplication } from '../types';

/** /admin/hr/appraisals — PBAS self-appraisal (research items auto-filled), reviews; CAS applications. */
export default function AppraisalsPage() {
  const { can } = usePermission();
  const casOn = useFeature('hr.cas_promotions');
  const me = useMyStaff();
  const [scope, setScope] = useState<string | undefined>();
  const schema = useQuery({ queryKey: ['appraisals', 'schema'], queryFn: hrApi.pbasSchema });
  const list = useQuery({ queryKey: ['appraisals', scope], queryFn: () => hrApi.appraisals({ scope, page_size: 100 }) });
  const cas = useQuery({ queryKey: ['cas', scope], queryFn: () => hrApi.cas({ scope, page_size: 100 }), enabled: casOn });
  const [values, setValues] = useState<Record<string, Record<string, string>>>({});
  const [review, setReview] = useState<Appraisal | null>(null);
  const [score, setScore] = useState('');
  const [decide, setDecide] = useState<CasApplication | null>(null);
  const [basic, setBasic] = useState('');
  const mine = (list.data?.data ?? []).find((a) => a.staff_id === me.data?.data.id);
  const save = useHrMutation(
    () =>
      hrApi.saveAppraisal({
        self_assessment: Object.fromEntries(Object.entries(values).map(([c, items]) => [c, Object.fromEntries(Object.entries(items).filter(([, v]) => v !== '').map(([k, v]) => [k, Number(v)]))])),
      }),
    ['appraisals'],
  );
  const submit = useHrMutation((id: string) => hrApi.submitAppraisal(id), ['appraisals']);
  const doReview = useHrMutation(({ id, decision }: { id: string; decision: string }) => hrApi.reviewAppraisal(id, { decision, reviewer_score: score ? Number(score) : undefined }), ['appraisals', 'approvals']);
  const applyCas = useHrMutation(() => hrApi.createCas(), ['cas']);
  const submitCas = useHrMutation((id: string) => hrApi.submitCas(id), ['cas']);
  const decideCas = useHrMutation(({ id, decision }: { id: string; decision: string }) => hrApi.decideCas(id, { decision, new_basic_paise: basic ? Math.round(Number(basic) * 100) : undefined }), ['cas', 'staff']);
  const auto = mine?.auto_filled ?? {};

  return (
    <div className="space-y-4">
      <PageHeader title="Appraisals & CAS" description="PBAS self-appraisal → HOD review → HR approval; Career Advancement Scheme promotions." />
      <ScopeTabs visibility={list.data?.meta.visibility} value={scope} onChange={setScope} labels={{ department: 'Team' }} />
      <Tabs defaultValue="mine">
        <TabsList>
          <TabsTrigger value="mine">My appraisal</TabsTrigger>
          <TabsTrigger value="all">Appraisals</TabsTrigger>
          {casOn && <TabsTrigger value="cas">CAS</TabsTrigger>}
        </TabsList>
        <TabsContent value="mine" className="space-y-3">
          {mine && <p className="text-sm">Current: <StatusBadge status={mine.status} /> · self score {num(mine.self_score)} · reviewer {num(mine.reviewer_score)} · final {num(mine.final_score)}</p>}
          <div className="grid gap-3 md:grid-cols-2">
            {Object.entries(schema.data?.data ?? {}).map(([cat, spec]) => (
              <Card key={cat}>
                <CardHeader><CardTitle className="text-sm">{spec.label} <span className="text-muted-foreground">(max {spec.max})</span></CardTitle></CardHeader>
                <CardContent className="grid gap-2 sm:grid-cols-2">
                  {Object.entries(spec.items).map(([item, ispec]) => (
                    <FormField
                      key={item}
                      label={`${ispec.label}${ispec.auto ? ' · auto' : ''}`}
                      type="number"
                      placeholder={ispec.auto ? String(auto[ispec.auto] ?? 0) : String(mine?.self_assessment?.values?.[cat]?.[item] ?? '')}
                      value={values[cat]?.[item] ?? ''}
                      onChange={(e) => setValues({ ...values, [cat]: { ...(values[cat] ?? {}), [item]: e.target.value } })}
                    />
                  ))}
                </CardContent>
              </Card>
            ))}
          </div>
          <div className="flex gap-2">
            <Button disabled={mine !== undefined && mine.status !== 'draft'} loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: (r) => toast.success(`Saved — self score ${num(r.data.self_score)}`), onError: (e) => toast.error(getApiError(e)) })}>Save draft</Button>
            {mine?.status === 'draft' && <Button variant="outline" onClick={() => submit.mutate(mine.id, { onSuccess: () => toast.success('Submitted to your HOD'), onError: (e) => toast.error(getApiError(e)) })}>Submit for review</Button>}
          </div>
          {mine?.workflow_instance_id && <WorkflowPanel instanceId={mine.workflow_instance_id} />}
        </TabsContent>
        <TabsContent value="all">
          <SimpleTable
            head={['Staff', 'Year', 'Self', 'Reviewer', 'Final', 'Status', '']}
            rows={(list.data?.data ?? []).map((a) => [
              `${a.employee_id} · ${a.staff_name}`,
              a.academic_year,
              num(a.self_score),
              num(a.reviewer_score),
              num(a.final_score),
              <StatusBadge key="s" status={a.status} />,
              ['submitted', 'reviewed'].includes(a.status) ? <Button key="r" size="sm" variant="outline" onClick={() => setReview(a)}>Review</Button> : null,
            ])}
          />
        </TabsContent>
        <TabsContent value="cas" className="space-y-3">
          <Button variant="outline" onClick={() => applyCas.mutate(undefined, { onSuccess: (r) => toast.success(`CAS ${r.data.from_cadre} → ${r.data.to_cadre}, eligible from ${r.data.eligibility_date}`), onError: (e) => toast.error(getApiError(e)) })}>Apply for CAS</Button>
          <SimpleTable
            head={['Staff', 'From → to', 'Eligible from', 'Status', '']}
            rows={(cas.data?.data ?? []).map((c) => [
              c.staff_name,
              `${label(c.from_cadre)} → ${label(c.to_cadre)}`,
              <span key="e">{c.eligibility_date} {c.eligible_now ? '✓' : ''}</span>,
              <StatusBadge key="s" status={c.status} />,
              c.status === 'draft' && c.staff_id === me.data?.data.id ? <Button key="b" size="sm" onClick={() => submitCas.mutate(c.id, { onSuccess: () => toast.success('Submitted'), onError: (e) => toast.error(getApiError(e)) })}>Submit</Button>
                : can('hr', 'cas') && ['submitted', 'screened', 'interviewed'].includes(c.status) ? <Button key="d" size="sm" variant="outline" onClick={() => setDecide(c)}>Decide</Button> : null,
            ])}
          />
        </TabsContent>
      </Tabs>

      <Modal open={review !== null} onOpenChange={(o) => !o && setReview(null)} title={`Review · ${review?.staff_name ?? ''}`} size="lg" footer={
        <div className="flex gap-2">
          <Button variant="destructive" onClick={() => review && doReview.mutate({ id: review.id, decision: 'reject' }, { onSuccess: () => setReview(null), onError: (e) => toast.error(getApiError(e)) })}>Reject</Button>
          <Button onClick={() => review && doReview.mutate({ id: review.id, decision: 'approve' }, { onSuccess: (r) => { toast.success(`Appraisal ${r.data.status}`); setReview(null); }, onError: (e) => toast.error(getApiError(e)) })}>Approve</Button>
        </div>
      }>
        <div className="space-y-2 text-sm">
          <p>Breakdown: {Object.entries(review?.breakdown ?? {}).map(([k, v]) => `${k} ${v}`).join(' · ')}</p>
          <FormField label="Reviewer score" type="number" value={score} onChange={(e) => setScore(e.target.value)} />
          <WorkflowPanel instanceId={review?.workflow_instance_id} />
        </div>
      </Modal>
      <Modal open={decide !== null} onOpenChange={(o) => !o && setDecide(null)} title={`CAS decision · ${decide?.staff_name ?? ''}`} footer={
        <div className="flex gap-2">
          <Button variant="destructive" onClick={() => decide && decideCas.mutate({ id: decide.id, decision: 'reject' }, { onSuccess: () => setDecide(null), onError: (e) => toast.error(getApiError(e)) })}>Reject</Button>
          <Button onClick={() => decide && decideCas.mutate({ id: decide.id, decision: 'approve' }, { onSuccess: () => { toast.success('Promoted'); setDecide(null); }, onError: (e) => toast.error(getApiError(e)) })}>Approve promotion</Button>
        </div>
      }>
        <FormField label="New basic (₹, empty = +3 %)" type="number" value={basic} onChange={(e) => setBasic(e.target.value)} />
      </Modal>
    </div>
  );
}
