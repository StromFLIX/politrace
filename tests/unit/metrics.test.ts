import { describe, expect, it } from 'vitest';
import { getData } from '../../src/lib/data';
import { metrics, voteTotals } from '../../src/lib/metrics';

describe('honest denominators', () => {
  it('uses null, not zero, for unknown coverage', () => {
    expect(metrics([], [], []).coverage).toBeNull();
    expect(metrics([], [], []).fulfilment).toBeNull();
  });
  it('does not confuse positive proposed links with fulfilment', () => {
    const data = getData('demo');
    const criteria = data.criteria.filter(c => c.party_id === 'bsw');
    const m = metrics(criteria, data.impacts, data.programs);
    expect(m.total).toBe(4);
    expect(m.covered).toBe(0);
    expect(m.fulfilled).toBe(0);
    expect(m.unknown).toBe(4);
  });
  it('includes unassessed criteria in the denominator, without penalising them', () => {
    const data = getData('demo');
    const criteria = data.criteria.filter(c => c.program_id === 'demo-spd-2025');
    const m = metrics(criteria, data.impacts, data.programs);
    expect(m).toMatchObject({ total: 4, fulfilled: 1, partial: 1, covered: 2, coverage: 50, unknown: 2 });
  });
  it('requires both the programme and criterion to be reviewed', () => {
    const data = structuredClone(getData('demo'));
    data.programs.forEach(p => p.review.status = 'proposed');
    const m = metrics(data.criteria, data.impacts, data.programs);
    expect(m.fulfilled).toBe(0);
    expect(m.covered).toBe(0);
  });
  it('rejects rejected criteria from counts', () => {
    const data = structuredClone(getData('demo'));
    data.criteria.forEach(c => c.review.status = 'rejected');
    expect(metrics(data.criteria, data.impacts, data.programs).total).toBe(0);
  });
  it('counts a criterion once even if two laws link to it', () => {
    const data = getData('demo');
    const before = metrics(data.criteria, data.impacts, data.programs).covered;
    expect(metrics(data.criteria, [...data.impacts, ...data.impacts], data.programs).covered).toBe(before);
  });
  it('never mixes historical programme criteria', () => {
    const data = getData('demo');
    expect(data.criteria.filter(c => c.program_id === 'demo-spd-2021')).toHaveLength(4);
    expect(metrics(data.criteria.filter(c => c.program_id === 'demo-spd-2021'), data.impacts, data.programs).fulfilled).toBe(0);
  });
});

describe('documented vote totals', () => {
  it('separates abstentions from absences', () => {
    expect(voteTotals([{ yes: 4, no: 3, abstain: 2, absent: 1 }])).toEqual({ yes: 4, no: 3, abstain: 2, absent: 1, cast: 9, total: 10 });
  });
  it('requires separately sourced records for any real votes', () => {
    for (const vote of getData('live').votes) {
      expect(vote.source.url).toMatch(/^https:\/\//);
      expect(vote.groups.length).toBeGreaterThan(0);
    }
    expect(voteTotals([]).total).toBe(0);
  });
});
