import { expect, it } from 'vitest';
import { getData } from '../../src/lib/data';
import { extractionCoverage } from '../../src/lib/metrics';

it('reports an explicit remaining scope, independent of political review', () => {
  const data = structuredClone(getData('demo'));
  const program = data.programs[0];
  program.criteria_extraction = [];
  expect(extractionCoverage(program, [])).toEqual({ source_leaves: program.leaves.length,
    processed_leaves: 0, remaining_leaves: program.leaves.length, complete: false });
  program.criteria_extraction = [{ leaf_id: program.leaves[0].id, criterion_ids: [],
    abstention_reason: 'Synthetic abstention.' }];
  const coverage = extractionCoverage(program, []);
  expect(coverage.processed_leaves).toBe(1);
  expect(coverage.remaining_leaves).toBe(program.leaves.length - 1);
  expect(coverage.complete).toBe(false);
});

it('deduplicates audited and criterion-bearing leaves and ignores foreign IDs', () => {
  const data = structuredClone(getData('demo'));
  const program = data.programs[0];
  const criteria = data.criteria.filter(c => c.program_id === program.id);
  program.criteria_extraction = [
    { leaf_id: criteria[0].leaf_id, criterion_ids: [criteria[0].id], abstention_reason: null },
    { leaf_id: 'unknown-leaf', criterion_ids: [], abstention_reason: 'Not part of this programme' },
  ];
  const coverage = extractionCoverage(program, [...data.criteria, ...criteria]);
  expect(coverage.processed_leaves).toBe(new Set(criteria.map(c => c.leaf_id)).size);
  expect(coverage.remaining_leaves).toBe(program.leaves.length - coverage.processed_leaves);
});
