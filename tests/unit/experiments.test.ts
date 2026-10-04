import { describe, expect, it } from 'vitest';
import { experimentTotals, type Experiment } from '../../src/lib/experiments';

describe('proposed experiment coverage', () => {
  it('does not call grouped or missing-context records fulfilled', () => {
    const report: Experiment = {
      program_id: 'gruene-2025', version: 'test', criteria_sha256: 'test',
      processed_leaves: 337, total_leaves: 337, law_ids: ['law-aa', 'law-bb'],
      groups: [{ id: 'group-aa', canonical_criterion_id: 'crit-aa', member_ids: ['crit-aa', 'crit-bb'], status: 'proposed' }],
      deduplication: [], cost: {}, note: 'test',
      laws: [{ law_id: 'law-aa', status: 'completed', eligible_count: 3, omitted_count: 1,
        candidate_ids: ['crit-aa', 'crit-bb'], pairs: [
          { criterion_id: 'crit-aa', disposition: 'missing_context', rationale: 'Absent base law', impact_id: null },
          { criterion_id: 'crit-bb', disposition: 'proposed_link', rationale: 'Proposed, not reviewed', impact_id: 'impact-aa' },
        ] }],
    };
    expect(experimentTotals(report)).toEqual({ criteria: 2, grouped: 1, combined: 1,
      lawsCompleted: 1, candidatePairs: 2, links: 1, missingContext: 1, unsupported: 0, omitted: 1 });
  });
});
