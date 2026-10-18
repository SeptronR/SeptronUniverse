import type { components } from '@/api/generated/openapi';

type S = components['schemas'];
export type SessionSheet = S['SessionForAttendance'];
export type RosterRow = S['RosterRow'];
export type MarkResult = S['MarkResult'];
export type QrIssue = S['QrIssueResponse'];
export type Checkin = S['CheckinResult'];
export type SummaryRow = S['StudentAttendanceSummary'];
export type OfferingSummary = S['SummaryResponse'];
export type MySummary = S['MySummaryResponse'];
export type HistoryRow = S['StudentHistoryRow'];
export type RegisterGrid = S['RegisterGrid'];
export type MissingSession = S['MissingSessionRow'];
export type UnmatchedPunch = S['UnmatchedPunch'];
export type OnDuty = S['OdResponse'];
export type Condonation = S['CondonationResponse'];
export type EligibilityRow = S['EligibilityRow'];
export type EligibilityRun = S['EligibilityRunSummary'];
export type DetentionRow = S['DetentionListRow'];
export type AlertConfig = S['AlertConfig'];
export type OfflineResult = S['OfflineBatchResult'];

export const MARKS = ['present', 'absent', 'late', 'on_duty', 'leave', 'medical', 'exempt'] as const;
export type Mark = (typeof MARKS)[number];
/** Tap-cycle order on the marking grid. */
export const CYCLE: Mark[] = ['present', 'absent', 'late', 'on_duty', 'leave', 'medical', 'exempt'];
export const MARK_SHORT: Record<string, string> = { present: 'P', absent: 'A', late: 'L', on_duty: 'OD', leave: 'LV', medical: 'M', exempt: 'EX' };
export const BAND_VARIANT: Record<string, 'success' | 'warning' | 'destructive' | 'info'> = {
  eligible: 'success',
  condonable: 'warning',
  not_eligible: 'destructive',
  condoned: 'info',
};
export const DECISION_VARIANT: Record<string, 'success' | 'warning' | 'destructive' | 'info' | 'secondary'> = {
  eligible: 'success',
  pending: 'warning',
  detained: 'destructive',
  debarred: 'destructive',
  condoned: 'info',
};
export const OD_REASONS = ['sports', 'nss', 'ncc', 'placement', 'conference', 'other'];
export const CONDONATION_REASONS = ['medical', 'sports', 'bereavement', 'other'];
export const hhmm = (t?: string | null) => (t ? t.slice(0, 5) : '');
