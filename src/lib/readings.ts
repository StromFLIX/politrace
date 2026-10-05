import fs from 'node:fs';
import path from 'node:path';
import { dataRoot } from './data';

export type ReadingPage = { number: number; markdown: string; header: string; footer: string; warnings: string[]; native_word_recall: number | null; corrections?: { before: string; after: string; source_evidence: string }[]; ocr_markdown_sha256?: string | null };
export type ReadingEdition = {
  document_id: string; collection: 'programs' | 'laws'; source_pdf_sha256: string; source_url: string; retrieved_from?: string | null;
  processor: string; models: string[]; page_count: number; pages: ReadingPage[];
  markdown_path: string; markdown_sha256: string; created_at: string; review_status: 'proposed'; evidence_unchanged: true;
};
const cache = new Map<string, ReadingEdition | null>();
export function readingEdition(id: string): ReadingEdition | null {
  if (cache.has(id)) return cache.get(id)!;
  if (!/^[a-z0-9-]+$/.test(id)) throw new Error('Invalid document ID');
  const file = path.join(dataRoot, 'live', 'readings', `${id}.json`);
  const result = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : null;
  cache.set(id, result);
  return result;
}
export function readingIndex() {
  const dir = path.join(dataRoot, 'live', 'readings');
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter(f => f.endsWith('.json')).sort().map(f => readingEdition(f.slice(0, -5))!);
}
export function readingProgress(): Record<string, any> | null {
  const file = path.join(dataRoot, 'live', 'processing', 'readings.json');
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : null;
}
export function productionProgress(): Record<string, any> | null {
  const file = path.join(dataRoot, 'live', 'analysis', 'overview.json');
  return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : null;
}
