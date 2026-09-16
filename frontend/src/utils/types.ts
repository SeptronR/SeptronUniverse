/** Envelope + list conventions shared by every feature api.ts (docs/Technical_Architecture.md §1). */
export interface PaginationMeta {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
}

export type ScopeName = 'self' | 'own' | 'department' | 'faculty' | 'college' | 'all';

export interface VisibilityMeta {
  self: boolean;
  scopes: ScopeName[];
  default: ScopeName;
  pii: boolean;
}

export interface EnvelopeMeta {
  pagination?: PaginationMeta;
  visibility?: VisibilityMeta;
  idempotent_replay?: boolean;
  [key: string]: unknown;
}

export interface Envelope<T> {
  success: true;
  data: T;
  message: string | null;
  meta: EnvelopeMeta;
}

export interface ApiErrorBody {
  success: false;
  error: { code: string; message: string; details: Record<string, unknown> };
  request_id?: string | null;
}

export type FilterOp = 'eq' | 'ne' | 'in' | 'lt' | 'lte' | 'gt' | 'gte' | 'like';

export interface ListParams {
  page?: number;
  page_size?: number;
  sort?: string;
  scope?: string;
  q?: string;
  include?: string;
  fields?: string;
  [filter: `filter[${string}]`]: string | undefined;
  [extra: string]: string | number | boolean | undefined;
}

export interface BulkResult<T = unknown> {
  succeeded: T[];
  failed: { index: number; code: string; message: string }[];
}
