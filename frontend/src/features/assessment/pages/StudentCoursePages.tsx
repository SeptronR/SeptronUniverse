import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getApiError } from '@/api/axios';
import { PageHeader } from '@/components/shared/PageHeader';
import { Badge, StatusBadge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Textarea } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs';
import { toast } from '@/components/ui/Toaster';
import { SimpleTable } from '@/features/hr/components/shared';
import { assessmentApi, lmsApi } from '../api';
import { useAssessmentMutation, useQ } from '../hooks';
import { AnnouncementsTab, DiscussionsTab } from './FacultyAssessmentPages';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const useTitle = (t: string) => useEffect(() => void (document.title = t), [t]);
const fail = (e: unknown) => toast.error(getApiError(e));

/** Timed quiz with autosave every 15 s and on every answer; the server auto-submits at the end. */
function QuizRunner({ quizId, onClose }: { quizId: string; onClose: () => void }) {
  const [att, setAtt] = useState<Any | null>(null);
  const [answers, setAnswers] = useState<Record<string, Any>>({});
  const [left, setLeft] = useState(0);
  const dirty = useRef(false);
  useEffect(() => {
    lmsApi.start(quizId).then((r: Any) => { setAtt(r.data); setAnswers(r.data.answers ?? {}); }).catch((e) => { fail(e); onClose(); });
  }, [quizId, onClose]);
  useEffect(() => {
    if (!att) return;
    const t = setInterval(() => {
      const s = Math.max(0, Math.round((new Date(att.ends_at).getTime() - Date.now()) / 1000));
      setLeft(s);
      if (dirty.current) {
        dirty.current = false;
        lmsApi.saveAnswers(att.attempt_id, answers).catch(() => (dirty.current = true));
      }
      if (s === 0) clearInterval(t);
    }, 1000);
    return () => clearInterval(t);
  }, [att, answers]);
  const answer = (qid: string, v: Any) => {
    setAnswers({ ...answers, [qid]: v });
    dirty.current = true;
  };
  const submit = async () => {
    try {
      await lmsApi.saveAnswers(att.attempt_id, answers);
      const r: Any = await lmsApi.submitAttempt(att.attempt_id);
      toast.success(r.data.show_result ? `Submitted — score ${r.data.total_score}` : 'Submitted');
      onClose();
    } catch (e) {
      fail(e);
    }
  };
  return (
    <Modal open onOpenChange={(o) => !o && onClose()} title={`Quiz — ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')} left`} size="xl" footer={<Button onClick={submit}>Submit</Button>}>
      <div className="space-y-4">
        {(att?.questions ?? []).map((q: Any, i: number) => (
          <div key={q.question_id} className="space-y-1">
            <p className="text-sm font-medium">{i + 1}. {q.body_primary} <span className="text-xs text-muted-foreground">[{q.marks}]</span></p>
            {q.body_secondary && <p className="text-xs text-muted-foreground">{q.body_secondary}</p>}
            {q.options.length ? (
              q.options.map((o: Any) => (
                <label key={o.id} className="flex items-center gap-2 text-sm">
                  <input type={q.type === 'msq' ? 'checkbox' : 'radio'} name={q.question_id} checked={q.type === 'msq' ? (answers[q.question_id] ?? []).includes(o.id) : answers[q.question_id] === o.id}
                    onChange={() => answer(q.question_id, q.type === 'msq' ? ((answers[q.question_id] ?? []).includes(o.id) ? answers[q.question_id].filter((x: string) => x !== o.id) : [...(answers[q.question_id] ?? []), o.id]) : o.id)} />
                  ({o.label}) {o.body_primary}
                </label>
              ))
            ) : (
              <Textarea value={answers[q.question_id] ?? ''} onChange={(e) => answer(q.question_id, e.target.value)} />
            )}
          </div>
        ))}
      </div>
    </Modal>
  );
}

export function StudentCoursePage() {
  const { offeringId } = useParams();
  useTitle('Course');
  const mods = useQ(['modules', offeringId], () => lmsApi.modules(offeringId!), !!offeringId);
  const assignments = useQ(['assignments', offeringId], () => lmsApi.assignments(offeringId!), !!offeringId);
  const quizzes = useQ(['quizzes', offeringId], () => lmsApi.quizzes(offeringId!), !!offeringId);
  const marks = useQ(['my-marks'], () => assessmentApi.myMarks());
  const [submitFor, setSubmitFor] = useState<Any | null>(null);
  const [text, setText] = useState('');
  const [quiz, setQuiz] = useState<string | null>(null);
  const run = useAssessmentMutation((fn: () => Promise<unknown>) => fn());
  const mine = (marks.data?.data ?? []).find((m: Any) => m.offering_id === offeringId);
  if (!offeringId) return null;
  return (
    <div className="space-y-4">
      <PageHeader title={mine ? `${mine.course_code} — ${mine.course_title}` : 'Course'} breadcrumbs={[{ label: 'Marks', to: '/student/marks' }, { label: 'Course' }]} />
      <Tabs defaultValue="content">
        <TabsList>
          <TabsTrigger value="content">Content</TabsTrigger>
          <TabsTrigger value="assignments">Assignments</TabsTrigger>
          <TabsTrigger value="quizzes">Quizzes</TabsTrigger>
          <TabsTrigger value="announcements">Announcements</TabsTrigger>
          <TabsTrigger value="discussions">Discussions</TabsTrigger>
          <TabsTrigger value="marks">My marks</TabsTrigger>
        </TabsList>
        <TabsContent value="content">
          {(mods.data?.data ?? []).map((m: Any) => (
            <Card key={m.id} className="mb-3">
              <CardContent className="space-y-1 p-4">
                <p className="font-medium">{m.title} <span className="text-xs text-muted-foreground">{m.completion_pct != null ? `${m.completion_pct}% done` : ''}</span></p>
                {m.contents.map((c: Any) => (
                  <div key={c.id} className="flex items-center justify-between text-sm">
                    <span><Badge variant="secondary">{c.content_type}</Badge> {c.title}</span>
                    <span className="flex items-center gap-2">
                      {c.my_progress != null && <span className="text-xs">{c.my_progress}%</span>}
                      <Button size="sm" variant="outline" onClick={() => { if (c.file_url) window.open(c.file_url, '_blank', 'noopener'); run.mutate(() => lmsApi.view(c.id, 100), { onError: fail }); }}>Open</Button>
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>
          ))}
          {!mods.data?.data?.length && <p className="text-sm text-muted-foreground">No content published yet.</p>}
        </TabsContent>
        <TabsContent value="assignments">
          <SimpleTable
            head={['Assignment', 'Due', 'Status', 'My submission', '']}
            rows={(assignments.data?.data ?? []).map((a: Any) => [
              a.title,
              a.due_at ? new Date(a.due_at).toLocaleString() : '—',
              <StatusBadge key="s" status={a.status} />,
              a.my_submission ? `${a.my_submission.status}${a.my_submission.marks != null ? ` · ${a.my_submission.marks}/${a.max_marks}` : ''}${a.my_submission.is_late ? ' · late' : ''}` : '—',
              a.status === 'published' && (!a.my_submission || ['resubmit', 'returned'].includes(a.my_submission.status)) && <Button key="b" size="sm" onClick={() => setSubmitFor(a)}>Submit</Button>,
            ])}
            empty="No assignments."
          />
        </TabsContent>
        <TabsContent value="quizzes">
          <SimpleTable
            head={['Quiz', 'Duration', 'Status', 'My attempts', '']}
            rows={(quizzes.data?.data ?? []).map((q: Any) => [
              q.title,
              `${q.duration_minutes} min`,
              <StatusBadge key="s" status={q.status} />,
              q.my_attempts.map((x: Any) => `#${x.attempt_no} ${x.status}${x.total_score != null ? ` ${x.total_score}` : ''}`).join(', ') || '—',
              q.status === 'published' && <Button key="b" size="sm" onClick={() => setQuiz(q.id)}>Start</Button>,
            ])}
            empty="No quizzes."
          />
        </TabsContent>
        <TabsContent value="announcements"><AnnouncementsTab offeringId={offeringId} faculty={false} /></TabsContent>
        <TabsContent value="discussions"><DiscussionsTab offeringId={offeringId} faculty={false} /></TabsContent>
        <TabsContent value="marks">
          <SimpleTable head={['Component', 'Status', 'Marks']} rows={(mine?.components ?? []).map((c: Any) => [c.name, c.status, c.is_absent ? 'AB' : c.marks != null ? `${c.marks}/${c.max_marks}` : '—'])} />
          {mine?.cia_scaled != null && <p className="mt-2 text-sm">CIA: <strong>{mine.cia_scaled}</strong>{mine.cia_max ? ` / ${mine.cia_max}` : ''}</p>}
        </TabsContent>
      </Tabs>
      <Modal open={!!submitFor} onOpenChange={(o) => !o && setSubmitFor(null)} title={`Submit — ${submitFor?.title ?? ''}`}
        footer={<Button disabled={!text} onClick={() => run.mutate(() => lmsApi.submit(submitFor.id, { text_answer: text }), { onSuccess: () => { toast.success('Submitted'); setSubmitFor(null); setText(''); }, onError: fail })}>Submit</Button>}>
        {submitFor?.due_at && new Date(submitFor.due_at) < new Date() && <p className="mb-2 text-sm text-status-pending">The due date has passed — a late penalty applies.</p>}
        <Textarea rows={6} placeholder="Your answer" value={text} onChange={(e) => setText(e.target.value)} />
      </Modal>
      {quiz && <QuizRunner quizId={quiz} onClose={() => setQuiz(null)} />}
    </div>
  );
}

export function StudentMarksPage() {
  useTitle('My marks');
  const marks = useQ(['my-marks'], () => assessmentApi.myMarks());
  const projects = useQ(['my-projects'], () => lmsApi.myProjects());
  return (
    <div className="space-y-4">
      <PageHeader title="My marks" description="Internal assessment per course; open a course for content, assignments and quizzes." />
      {marks.error && <p className="text-sm text-muted-foreground">{getApiError(marks.error)}</p>}
      {(marks.data?.data ?? []).map((m: Any) => (
        <Card key={m.offering_id}>
          <CardContent className="space-y-2 p-4">
            <div className="flex justify-between">
              <Link className="font-medium text-primary hover:underline" to={`/student/courses/${m.offering_id}`}>{m.course_code} — {m.course_title}</Link>
              {m.cia_scaled != null && <span className="text-sm">CIA <strong>{m.cia_scaled}</strong></span>}
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              {m.components.map((c: Any) => <Badge key={c.assessment_id} variant="outline">{c.name}: {c.is_absent ? 'AB' : c.marks != null ? `${c.marks}/${c.max_marks}` : '—'}</Badge>)}
            </div>
          </CardContent>
        </Card>
      ))}
      {(projects.data?.data ?? []).length > 0 && (
        <>
          <h3 className="font-medium">My projects</h3>
          <SimpleTable head={['Title', 'Guide', 'Status', 'Reviews']} rows={(projects.data?.data ?? []).map((p: Any) => [p.title, p.guide_name ?? '—', <StatusBadge key="s" status={p.status} />, p.reviews.map((r: Any) => `R${r.review_no}: ${r.marks ?? '—'}`).join(' · ')])} />
        </>
      )}
    </div>
  );
}
