import { describe, expect, it } from 'vitest';
import { getData, datasets, sectionPath } from '../../src/lib/data';

describe('site data graph', () => {
  for (const dataset of datasets) {
    const data = getData(dataset);
    it(`${dataset}: every criterion is reachable in the source tree`, () => {
      for (const c of data.criteria) {
        const program = data.programs.find(p => p.id === c.program_id)!;
        expect(sectionPath(program.tree, c.leaf_id).length).toBeGreaterThan(0);
        expect(program.leaves.find(p => p.id === c.leaf_id)?.text).toContain(c.reference.quote);
      }
    });
    it(`${dataset}: every impact resolves a criterion, law and exact quotation`, () => {
      for (const i of data.impacts) {
        expect(data.criteria.find(c => c.id === i.criterion_id)).toBeDefined();
        expect(data.laws.find(l => l.id === i.law_id)?.passages.find(p => p.id === i.law_passage_id)?.text).toContain(i.law_quote);
      }
    });
  }
});
