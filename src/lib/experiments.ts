import fs from 'node:fs';
import path from 'node:path';
import type { Dataset } from './types';

export interface Experiment {
  program_id: string; version: string; criteria_sha256: string;
  processed_leaves: number; total_leaves: number; law_ids: string[];
  groups: { id: string; canonical_criterion_id: string; member_ids: string[]; status: 'proposed' }[];
  deduplication: { left_id: string; right_id: string; decision: { equivalent: boolean; rationale: string } }[];
  laws: { law_id: string; status: 'completed' | 'needs_ocr' | 'partial'; eligible_count: number; omitted_count: number;
    candidate_ids: string[]; pairs: { criterion_id: string; disposition: string; rationale: string; impact_id: string | null }[] }[];
  cost: { reported_cost_usd?: number; budget_exposure_usd?: number; max_usd?: number;
    cost_accounting_complete?: boolean; model?: string; review_model?: string };
  note: string;
}
const cache = new Map<Dataset, Experiment[]>();
export function experiments(dataset: Dataset): Experiment[] {
  if (!cache.has(dataset)) {
    const records = new Map<string, Experiment>();
    for (const collection of ['experiments', 'analyses']) {
      const directory = path.resolve('data', dataset, collection);
      if (fs.existsSync(directory)) for (const file of fs.readdirSync(directory).filter(f => f.endsWith('.json')).sort()) {
        const report = JSON.parse(fs.readFileSync(path.join(directory, file), 'utf8')) as Experiment;
        records.set(report.program_id, report);
      }
    }
    cache.set(dataset, [...records.values()]);
  }
  return cache.get(dataset)!;
}
export function experimentTotals(report: Experiment) {
  const pairs = report.laws.flatMap(law => law.pairs);
  return {
    criteria: report.groups.reduce((n, group) => n + group.member_ids.length, 0),
    grouped: report.groups.length,
    combined: report.groups.filter(group => group.member_ids.length > 1).length,
    lawsCompleted: report.laws.filter(law => law.status === 'completed').length,
    candidatePairs: pairs.length,
    links: pairs.filter(pair => pair.impact_id).length,
    missingContext: pairs.filter(pair => pair.disposition === 'missing_context').length,
    unsupported: pairs.filter(pair => pair.disposition === 'no_supported_link').length,
    omitted: report.laws.reduce((n, law) => n + law.omitted_count, 0),
  };
}
