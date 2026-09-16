import type { components } from '@/api/generated/openapi';

/** Response/request shapes of the platform module, straight from the generated OpenAPI types (Phase 01). */
export type Job = components['schemas']['JobResponse'];
export type JobStatus = Job['status'];
export type ReadOnlyState = components['schemas']['ReadOnlyState'];
export type ReadOnlyModeRequest = components['schemas']['ReadOnlyModeRequest'];
export type HelpArticleSummary = components['schemas']['HelpArticleSummary'];
export type HelpArticle = components['schemas']['HelpArticleResponse'];
export type FeedbackCreate = components['schemas']['FeedbackCreate'];
export type FeedbackResponse = components['schemas']['FeedbackResponse'];
export type SearchResult = components['schemas']['SearchResult'];
export type SearchResponse = components['schemas']['SearchResponse'];
export type PublicConfig = components['schemas']['PublicConfig'];
export type MobileConfig = components['schemas']['MobileConfigResponse'];

export interface JobListParams {
  page?: number;
  page_size?: number;
  sort?: string;
  scope?: string;
  status?: JobStatus;
  job_type?: string;
}
