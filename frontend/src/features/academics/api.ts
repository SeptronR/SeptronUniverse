import type { AxiosRequestConfig } from 'axios';
import { api } from '@/api/axios';
import type { Envelope } from '@/utils/types';
import type {
  AssessmentScheme,
  Basket,
  Batch,
  Course,
  GradingScale,
  Program,
  ProgramRegulation,
  PublicCourse,
  PublicProgram,
  Regulation,
  RegulationDiff,
  RulesHelpItem,
  Structure,
  StructureValidation,
} from './types';

const get = <T>(url: string, config?: AxiosRequestConfig) => api.get(url, config) as unknown as Promise<Envelope<T>>;
const post = <T>(url: string, body?: unknown, config?: AxiosRequestConfig) =>
  api.post(url, body, config) as unknown as Promise<Envelope<T>>;
const put = <T>(url: string, body?: unknown) => api.put(url, body) as unknown as Promise<Envelope<T>>;
const del = <T>(url: string) => api.delete(url) as unknown as Promise<Envelope<T>>;

type Params = Record<string, string | number | boolean | undefined | null>;
type Body = Record<string, unknown>;

/** Programmes, regulations, curriculum, courses, grading, batches, public catalogue (Prompts/05 §05.8). */
export const academicsApi = {
  // programmes
  programs: (params: Params = {}) => get<Program[]>('/programs', { params }),
  createProgram: (body: Body) => post<Program>('/programs', body),
  updateProgram: (id: string, body: Body) => put<Program>(`/programs/${id}`, body),
  closeProgram: (id: string) => post<Program>(`/programs/${id}/close`, undefined, { idempotent: false }),
  // regulations
  regulations: (params: Params = {}) => get<Regulation[]>('/regulations', { params }),
  regulation: (id: string) => get<Regulation>(`/regulations/${id}`),
  rulesSchema: () => get<RulesHelpItem[]>('/regulations/rules-schema'),
  createRegulation: (body: Body) => post<Regulation>('/regulations', body),
  updateRegulation: (id: string, body: Body) => put<Regulation>(`/regulations/${id}`, body),
  approveRegulation: (id: string, body: Body = {}) =>
    post<{ regulation: Regulation; workflow_instance_id: string | null; pending_workflow: boolean }>(
      `/regulations/${id}/approve`,
      body,
      { idempotent: false },
    ),
  activateRegulation: (id: string) => post<Regulation>(`/regulations/${id}/activate`, undefined, { idempotent: false }),
  cloneRegulation: (id: string, body: Body) => post<Regulation>(`/regulations/${id}/clone`, body, { idempotent: false }),
  diff: (id: string) => get<RegulationDiff>(`/regulations/${id}/diff`),
  // programme-regulations + structure
  programRegulations: (params: Params = {}) => get<ProgramRegulation[]>('/program-regulations', { params }),
  createProgramRegulation: (body: Body) => post<ProgramRegulation>('/program-regulations', body, { idempotent: false }),
  updateProgramRegulation: (id: string, body: Body) => put<ProgramRegulation>(`/program-regulations/${id}`, body),
  structure: (id: string) => get<Structure>(`/program-regulations/${id}/structure`),
  replaceStructure: (id: string, body: Body) => put<Structure>(`/program-regulations/${id}/structure`, body),
  validateStructure: (id: string, forApproval = false) =>
    post<StructureValidation>(`/program-regulations/${id}/structure/validate`, undefined, {
      params: { for_approval: forApproval },
      idempotent: false,
    }),
  // baskets
  baskets: (params: Params = {}) => get<Basket[]>('/elective-baskets', { params }),
  createBasket: (body: Body) => post<Basket>('/elective-baskets', body, { idempotent: false }),
  updateBasket: (id: string, body: Body) => put<Basket>(`/elective-baskets/${id}`, body),
  deleteBasket: (id: string) => del<null>(`/elective-baskets/${id}`),
  basketCourses: (id: string, courses: { course_id: string }[]) => put<Basket>(`/elective-baskets/${id}/courses`, { courses }),
  // courses
  courses: (params: Params = {}) => get<Course[]>('/courses', { params }),
  course: (id: string) => get<Course>(`/courses/${id}`),
  createCourse: (body: Body) => post<Course>('/courses', body),
  updateCourse: (id: string, body: Body) => put<Course>(`/courses/${id}`, body),
  courseStatus: (id: string, status: string) => post<Course>(`/courses/${id}/status`, { status }, { idempotent: false }),
  prerequisites: (id: string, items: Body[]) => put<Course>(`/courses/${id}/prerequisites`, { items }),
  bulkImport: (regulationId: string, csv: string) =>
    post<{ job_id: string; status: string }>('/courses/bulk-import', { regulation_id: regulationId, csv }, { idempotent: false }),
  exportCourses: (params: Params = {}) => api.get('/courses/export', { params, responseType: 'blob' }) as unknown as Promise<Blob>,
  // grading + schemes
  scales: (params: Params = {}) => get<GradingScale[]>('/grading-scales', { params }),
  createScale: (body: Body) => post<GradingScale>('/grading-scales', body, { idempotent: false }),
  updateScale: (id: string, body: Body) => put<GradingScale>(`/grading-scales/${id}`, body),
  schemes: (params: Params = {}) => get<AssessmentScheme[]>('/assessment-schemes', { params }),
  createScheme: (body: Body) => post<AssessmentScheme>('/assessment-schemes', body, { idempotent: false }),
  updateScheme: (id: string, body: Body) => put<AssessmentScheme>(`/assessment-schemes/${id}`, body),
  schemeComponents: (id: string, components: Body[]) => put<AssessmentScheme>(`/assessment-schemes/${id}/components`, { components }),
  // batches
  batches: (params: Params = {}) => get<Batch[]>('/batches', { params }),
  createBatch: (body: Body) => post<Batch>('/batches', body),
  replaceSections: (id: string, sections: Body[]) => put<Batch>(`/batches/${id}/sections`, { sections }),
  assignAdvisor: (id: string, sectionId: string, userId: string) =>
    put<Batch>(`/batches/${id}/sections/${sectionId}/advisor`, { user_id: userId }),
  // public catalogue (no auth)
  catalog: (params: Params = {}) =>
    get<{ institution: string; programs: PublicProgram[]; generated_at: string }>('/public/catalog', { params }),
  catalogProgram: (code: string, params: Params = {}) => get<PublicProgram>(`/public/catalog/programs/${code}`, { params }),
  catalogCourse: (regulation: string, code: string, params: Params = {}) =>
    get<PublicCourse>(`/public/catalog/courses/${regulation}/${code}`, { params }),
};
