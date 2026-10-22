import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;
// Shapes come from the generated OpenAPI types; pages read only the fields they render.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;
const get = <T = Any>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const once = { idempotent: false } as AxiosRequestConfig;
const post = <T = Any>(url: string, body?: unknown, config: AxiosRequestConfig = once) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T = Any>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T = Any>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;
const blob = (url: string, params?: Params) => api.get(url, { params, responseType: 'blob' }) as unknown as Promise<Blob>;
const upload = <T = Any>(url: string, file: File, params?: Params) => {
  const fd = new FormData();
  fd.append('file', file);
  return api.post(url, fd, { ...once, params }) as unknown as Promise<Envelope<T>>;
};

/** Internal marks, CIA, change requests, OBE definitions (Prompts/13 §13.8). */
export const assessmentApi = {
  queue: (p: Params = {}) => get('/offering-assessments', { params: p }),
  list: (offeringId: string) => get(`/course-offerings/${offeringId}/assessments`),
  instantiate: (offeringId: string) => post(`/course-offerings/${offeringId}/assessments/instantiate`, {}),
  questions: (id: string) => get(`/offering-assessments/${id}/questions`),
  saveQuestions: (id: string, questions: Body[]) => put(`/offering-assessments/${id}/questions`, { questions }),
  grid: (id: string) => get(`/offering-assessments/${id}/marks`),
  /** Bulk marks carry an Idempotency-Key (axios interceptor default). */
  saveMarks: (id: string, rows: Body[]) => api.post(`/offering-assessments/${id}/marks`, { rows }) as unknown as Promise<Envelope<Any>>,
  importMarks: (id: string, file: File) => upload(`/offering-assessments/${id}/marks/import`, file),
  exportMarks: (id: string) => get(`/offering-assessments/${id}/export`),
  submit: (id: string) => post(`/offering-assessments/${id}/submit`),
  verify: (id: string, decision: 'approve' | 'reject', comment?: string) => post(`/offering-assessments/${id}/verify`, { decision, comment: comment ?? null }),
  lock: (id: string) => post(`/offering-assessments/${id}/lock`),
  reopen: (id: string, reason: string) => post(`/offering-assessments/${id}/reopen`, { reason }),
  cia: (offeringId: string) => get(`/course-offerings/${offeringId}/cia/consolidate`),
  consolidate: (offeringId: string) => post(`/course-offerings/${offeringId}/cia/consolidate`),
  approveCia: (offeringId: string) => post(`/cia/${offeringId}/approve`),
  lockCia: (offeringId: string) => post(`/cia/${offeringId}/lock`),
  submitCia: (offeringId: string) => post(`/cia/${offeringId}/submit-to-university`),
  changes: (p: Params = {}) => get('/marks-change-requests', { params: p }),
  requestChange: (b: Body) => post('/marks-change-requests', b),
  decideChange: (id: string, decision: 'approve' | 'reject') => post(`/marks-change-requests/${id}/${decision}`, {}),
  applyChange: (id: string) => post(`/marks-change-requests/${id}/apply`),
  myMarks: (p: Params = {}) => get('/marks/me', { params: p }),
  programOutcomes: (id: string) => get(`/programs/${id}/outcomes`),
  saveProgramOutcomes: (id: string, outcomes: Body[]) => put(`/programs/${id}/outcomes`, { outcomes }),
  importTemplate: (id: string, template?: string) => post(`/programs/${id}/outcomes/import-template`, { template: template ?? null }),
  savePeoPo: (id: string, cells: Body[]) => put(`/programs/${id}/peo-po-matrix`, { cells }),
  courseOutcomes: (id: string) => get(`/courses/${id}/outcomes`),
  saveCos: (id: string, outcomes: Body[]) => put(`/courses/${id}/outcomes`, { outcomes }),
  saveMatrix: (id: string, cells: Body[]) => put(`/courses/${id}/co-po-matrix`, { cells }),
  matrixCsv: (id: string) => blob(`/courses/${id}/co-po-matrix/export`),
};

/** LMS, lesson plans, course files, projects, question bank, study materials. */
export const lmsApi = {
  modules: (offeringId: string) => get(`/course-offerings/${offeringId}/modules`),
  createModule: (offeringId: string, b: Body) => post(`/course-offerings/${offeringId}/modules`, b),
  updateModule: (id: string, b: Body) => put(`/modules/${id}`, b),
  deleteModule: (id: string) => del(`/modules/${id}`),
  addContent: (moduleId: string, b: Body) => post(`/modules/${moduleId}/contents`, b),
  deleteContent: (id: string) => del(`/contents/${id}`),
  view: (id: string, progress_pct: number) => post(`/contents/${id}/view`, { progress_pct }),
  assignments: (offeringId: string) => get(`/course-offerings/${offeringId}/assignments`),
  createAssignment: (offeringId: string, b: Body) => post(`/course-offerings/${offeringId}/assignments`, b),
  assignmentStatus: (id: string, action: 'publish' | 'close') => post(`/assignments/${id}/${action}`),
  submissions: (id: string) => get(`/assignments/${id}/submissions`),
  submit: (id: string, b: Body) => post(`/assignments/${id}/submit`, b),
  grade: (id: string, rows: Body[]) => post(`/assignments/${id}/grade`, { rows }),
  similarity: (id: string) => post(`/assignments/${id}/similarity-check`),
  quizzes: (offeringId: string) => get(`/course-offerings/${offeringId}/quizzes`),
  createQuiz: (offeringId: string, b: Body) => post(`/course-offerings/${offeringId}/quizzes`, b),
  quizStatus: (id: string, action: 'publish' | 'close') => post(`/quizzes/${id}/${action}`),
  start: (id: string) => post(`/quizzes/${id}/start`),
  saveAnswers: (attemptId: string, answers: Body) => put(`/quiz-attempts/${attemptId}/answers`, { answers }),
  submitAttempt: (attemptId: string) => post(`/quiz-attempts/${attemptId}/submit`),
  attempts: (id: string) => get(`/quizzes/${id}/attempts`),
  pushToMarks: (id: string) => post(`/quizzes/${id}/push-to-marks`),
  announcements: (offeringId: string) => get(`/course-offerings/${offeringId}/announcements`),
  announce: (offeringId: string, b: Body) => post(`/course-offerings/${offeringId}/announcements`, b),
  threads: (offeringId: string) => get(`/course-offerings/${offeringId}/threads`),
  createThread: (offeringId: string, b: Body) => post(`/course-offerings/${offeringId}/threads`, b),
  patchThread: (id: string, b: Body) => put(`/threads/${id}`, b),
  posts: (threadId: string) => get(`/threads/${threadId}/posts`),
  post: (threadId: string, body: string) => post(`/threads/${threadId}/posts`, { body }),
  upvote: (id: string) => post(`/posts/${id}/upvote`),
  markAnswer: (id: string) => post(`/posts/${id}/mark-answer`),
  onlineLink: (offeringId: string, link?: string) => post(`/course-offerings/${offeringId}/online-link`, { link: link ?? null }),
  plan: (offeringId: string) => get(`/course-offerings/${offeringId}/lesson-plan`),
  savePlan: (offeringId: string, items: Body[]) => post(`/course-offerings/${offeringId}/lesson-plan`, { items }),
  deliver: (id: string, b: Body) => post(`/lesson-plans/${id}/deliver`, b),
  deviation: (offeringId: string) => get(`/course-offerings/${offeringId}/lesson-plan/deviation`),
  courseFile: (offeringId: string) => get(`/course-offerings/${offeringId}/course-file`),
  saveCourseFile: (offeringId: string, checklist: Body[]) => put(`/course-offerings/${offeringId}/course-file`, { checklist }),
  auditCourseFile: (id: string, remarks?: string) => post(`/course-files/${id}/audit`, { remarks: remarks ?? null }),
  projects: (offeringId: string) => get(`/course-offerings/${offeringId}/projects`),
  myProjects: () => get('/projects/me'),
  createProject: (offeringId: string, b: Body) => post(`/course-offerings/${offeringId}/projects`, b),
  review: (projectId: string, b: Body) => post(`/projects/${projectId}/reviews`, b),
  questions: (p: Params = {}) => get('/questions', { params: p }),
  createQuestion: (b: Body) => post('/questions', b),
  deleteQuestion: (id: string) => del(`/questions/${id}`),
  importQuestions: (file: File, courseId?: string) => upload('/questions/import', file, { course_id: courseId }),
  blueprints: (p: Params = {}) => get('/blueprints', { params: p }),
  createBlueprint: (b: Body) => post('/blueprints', b),
  generate: (b: Body) => post('/question-papers/generate', b),
  freeze: (id: string) => post(`/question-papers/${id}/freeze`),
  printPaper: (id: string, lang: string) => blob(`/question-papers/${id}/print`, { lang }),
  myMaterials: () => get('/study-materials/me'),
};

export function openBlob(b: Blob, filename?: string) {
  const url = URL.createObjectURL(b);
  if (filename) {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
  } else window.open(url, '_blank', 'noopener');
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
