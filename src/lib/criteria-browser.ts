import type { AssessmentStatus } from './types';
import { searchText } from './program-reader-search';

export const pageSizes = [20, 50, 100] as const;
export const defaultPageSize = pageSizes[0];

export function parsePageSize(value: string | null): number {
  const size = Number(value);
  return pageSizes.some(option => option === size) ? size : defaultPageSize;
}

export function parsePage(value: string | null): number {
  if (!value || !/^\d+$/.test(value)) return 1;
  const page = Number(value);
  return Number.isSafeInteger(page) && page > 0 ? page : 1;
}

export function paginate(total: number, requestedPage: number, pageSize: number) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.max(1, Math.min(requestedPage, pages));
  const start = (page - 1) * pageSize;
  return { page, pages, start, end: Math.min(start + pageSize, total) };
}

// At most seven controls, including gaps, even for thousands of criteria.
export function pageLinks(page: number, pages: number): (number | 'gap')[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  if (page <= 4) return [1, 2, 3, 4, 5, 'gap', pages];
  if (page >= pages - 3) return [1, 'gap', pages - 4, pages - 3, pages - 2, pages - 1, pages];
  return [1, 'gap', page - 1, page, page + 1, 'gap', pages];
}

export interface FilterRecord {
  search: string;
  topics: string[];
  parties: string[];
  status: string;
}
export interface Filters { q: string; topic: string; party: string; status: string }

export function matchingRecords<T extends FilterRecord>(records: T[], filters: Filters): T[] {
  const words = searchText(filters.q).split(' ').filter(Boolean);
  return records.filter(record => words.every(word => record.search.includes(word)) &&
    (!filters.topic || record.topics.includes(filters.topic)) &&
    (!filters.party || record.parties.includes(filters.party)) &&
    (!filters.status || record.status === filters.status));
}

export const progressStatuses: AssessmentStatus[] = ['fulfilled', 'partial', 'contradicted', 'mixed', 'unassessed'];
export interface TopicProgress {
  total: number;
  covered: number;
  counts: Record<AssessmentStatus, number>;
}
export interface ProgressRecord { topics: string[]; status: string; covered: boolean }

// Input is the full eligible programme/party, never a page or a status-filtered slice.
// Multi-tag criteria count once in each topic, not once per tag occurrence.
export function topicProgress(records: ProgressRecord[]): Map<string, TopicProgress> {
  const summaries = new Map<string, TopicProgress>();
  for (const record of records) {
    for (const topic of new Set(record.topics)) {
      let summary = summaries.get(topic);
      if (!summary) {
        summary = { total: 0, covered: 0, counts: { fulfilled: 0, partial: 0, contradicted: 0, mixed: 0, unassessed: 0 } };
        summaries.set(topic, summary);
      }
      summary.total++;
      if (record.covered) summary.covered++;
      const status = progressStatuses.includes(record.status as AssessmentStatus) ? record.status as AssessmentStatus : 'unassessed';
      summary.counts[status]++;
    }
  }
  return summaries;
}

export function progressLabel(summary: TopicProgress): string {
  const counts = summary.counts;
  return `${counts.fulfilled} gesetzlich umgesetzt, ${counts.partial} teilweise umgesetzt, ${counts.contradicted} widersprochen, ${counts.mixed} gemischte Wirkung, ${counts.unassessed} offen`;
}
