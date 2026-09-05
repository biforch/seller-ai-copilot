import { apiClient } from '@/app/api/client';

export type EventMetricKey =
  | 'registration_completed'
  | 'audit_started'
  | 'audit_completed'
  | 'audit_failed'
  | 'amazon_connect_started'
  | 'amazon_connected';

export type EventMetrics = Record<EventMetricKey, number>;

export interface AnalyticsSummary {
  days: number;
  period_start: string;
  period_end: string;
  counts: EventMetrics;
  unique_users: EventMetrics;
  audit_success_rate: number | null;
  daily: Array<EventMetrics & { date: string }>;
}

export const analyticsApi = {
  summary: (days: number, signal?: AbortSignal) =>
    apiClient.get<AnalyticsSummary>('/analytics/summary', { params: { days }, signal }),
};
