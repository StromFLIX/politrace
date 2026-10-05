import { describe, expect, it } from 'vitest';
import { getData } from '../../src/lib/data';
import { formatPercentage, partyInsights } from '../../src/lib/party-insights';
import type { AssessmentStatus, Criterion, Impact, Law } from '../../src/lib/types';

function fixture() {
  const source = structuredClone(getData('demo'));
  const program = source.programs.find(p => p.id === 'demo-spd-2025')!;
  program.period_start = '2025-03-01';
  program.period_end = '2026-01-01';
  program.published_at = '2025-02-01';
  program.review.status = 'proposed';
  const data = { criteria: [] as Criterion[], impacts: [] as Impact[], laws: [] as Law[] };
  const criterion = (id: string, status: AssessmentStatus = 'unassessed', tags = ['arbeit']) => {
    const record = structuredClone(source.criteria[0]);
    Object.assign(record, { id, program_id: program.id, party_id: program.party_id, tags });
    record.review.status = 'proposed';
    record.assessment = { status, rationale: 'Separate overall assessment', method: 'agent', reviewer: null,
      assessed_at: '2026-02-01', evidence_ids: [], generation: { model: 'openai/gpt-6-sol', prompt_version: 'test', input_sha256: 'a'.repeat(64) } };
    data.criteria.push(record);
    return record;
  };
  const law = (id: string, date: string) => {
    const record = structuredClone(source.laws[0]);
    Object.assign(record, { id, published_at: date });
    record.review.status = 'proposed';
    data.laws.push(record);
    return record;
  };
  const impact = (c: Criterion, l: Law, score: Impact['score'] = 1) => {
    const record = structuredClone(source.impacts[0]);
    Object.assign(record, { id: `impact-${c.id}-${l.id}`, criterion_id: c.id, law_id: l.id, score });
    record.review.status = 'proposed';
    record.evaluation = { status: 'accepted', model: 'openai/gpt-6-sol', method: 'sol-final-v1', input_sha256: 'b'.repeat(64), decided_at: '2026-02-01' };
    c.assessment.evidence_ids.push(record.id);
    data.impacts.push(record);
    return record;
  };
  return { data, program, criterion, law, impact, report: () => partyInsights(data, [program]) };
}

describe('party insight denominators and accepted evidence', () => {
  it('keeps empty and unknown different; never invents a timeline without evidence', () => {
    const f = fixture();
    expect(f.report()).toMatchObject({ criteria: { total: 0 }, fulfilment_percent: null, coverage_percent: null, timeline: [], law_effects: [] });
    f.criterion('open');
    f.law('unlinked', '2025-04-01');
    expect(f.report()).toMatchObject({ criteria: { total: 1, unknown: 1 }, fulfilment_percent: 0, coverage_percent: 0, timeline: [] });
  });

  it('counts all five criterion states, not the sum or maximum of law scores', () => {
    const f = fixture();
    const l = f.law('one-law', '2025-04-01');
    for (const status of ['fulfilled', 'partial', 'contradicted', 'mixed', 'unassessed'] as const) {
      const c = f.criterion(status, status);
      if (status !== 'unassessed') f.impact(c, l, 2); // Even +2 must not become overall fulfilment.
    }
    const r = f.report();
    expect(r.criteria).toMatchObject({ total: 5, fulfilled: 1, partial: 1, contradicted: 1, mixed: 1, unknown: 1, covered: 4 });
    expect(r.fulfilment_percent).toBe(20);
    expect(r.coverage_percent).toBe(80);
    expect(r.laws).toMatchObject({ total: 1, supporting: 1, opposing: 0, evidence: 4 });
  });

  it.each(['draft', 'rejected', 'missing_context', 'editorially_rejected', 'wrong_model'] as const)('excludes %s links from counts and history', disposition => {
    const f = fixture();
    const i = f.impact(f.criterion('test', 'fulfilled'), f.law('test-law', '2025-04-01'), 2);
    if (disposition === 'draft') i.evaluation = null;
    else if (disposition === 'editorially_rejected') i.review.status = 'rejected';
    else if (disposition === 'wrong_model') i.evaluation!.model = 'openai/gpt-6-luna';
    else i.evaluation!.status = disposition;
    expect(f.report()).toMatchObject({ criteria: { total: 1, covered: 0, fulfilled: 0, unknown: 1 }, laws: { total: 0 }, timeline: [] });
  });

  it('respects editorial corrections without inventing machine or human approvals', () => {
    const f = fixture();
    f.program.review.status = 'reviewed';
    const c = f.criterion('editorial', 'contradicted');
    c.review.status = 'reviewed';
    c.assessment.method = 'editorial';
    const i = f.impact(c, f.law('corrected', '2025-04-01'), -2);
    i.review.status = 'reviewed';
    i.evaluation = null;
    expect(f.report()).toMatchObject({ criteria: { covered: 1, contradicted: 1 }, laws: { opposing: 1 } });
    f.program.review.status = 'proposed';
    expect(f.report()).toMatchObject({ criteria: { covered: 0, contradicted: 0 }, laws: { total: 0 } });
  });

  it('excludes rejected criteria, programmes, laws and dangling links', () => {
    const f = fixture();
    const c = f.criterion('test', 'fulfilled');
    const l = f.law('test-law', '2025-04-01');
    const i = f.impact(c, l, 2);
    c.review.status = 'rejected';
    expect(f.report().criteria.total).toBe(0);
    c.review.status = 'proposed';
    f.program.review.status = 'rejected';
    expect(f.report()).toMatchObject({ criteria: { total: 0 }, laws: { total: 0 }, timeline: [] });
    f.program.review.status = 'proposed';
    l.review.status = 'rejected';
    expect(f.report().laws.total).toBe(0);
    l.review.status = 'proposed';
    i.criterion_id = 'missing';
    expect(f.report().laws.total).toBe(0);
    i.criterion_id = c.id;
    i.law_id = 'missing';
    expect(f.report().laws.total).toBe(0);
  });

  it('isolates programme periods, including the exclusive end and start on publication', () => {
    const f = fixture();
    const c = f.criterion('current', 'partial');
    for (const [id, date] of [['before', '2025-02-28'], ['start', '2025-03-01'], ['last', '2025-12-31'], ['end', '2026-01-01']]) {
      f.impact(c, f.law(id, date));
    }
    const previous = { ...f.program, id: 'older', period_start: '2021-09-01', period_end: '2025-03-01', published_at: '2021-01-01' };
    const old = f.criterion('old'); old.program_id = previous.id;
    f.impact(old, f.data.laws[0]);
    const report = f.report();
    expect(report.criteria.total).toBe(1);
    expect(report.law_effects.map(l => l.id).sort()).toEqual(['last', 'start']);
    expect(report.laws_through).toBe('2025-12-31');
    expect(partyInsights(f.data, [previous]).law_effects.map(l => l.id)).toEqual(['before']);
  });
});

describe('law reach and the reconstructed evidence timeline', () => {
  it('counts laws and covered criteria once, while explicitly allowing overlapping directions', () => {
    const f = fixture();
    const c = f.criterion('supported', 'partial');
    const other = f.criterion('opposed', 'contradicted');
    const l = f.law('mixed-law', '2025-04-02');
    f.impact(c, l, 1); f.impact(other, l, -1);
    f.data.impacts.push(f.data.impacts[0]);
    const r = f.report();
    expect(r.laws).toEqual({ total: 1, supporting: 1, opposing: 1, mixed: 1, evidence: 2 });
    expect(r.law_effects[0]).toMatchObject({ affected: 2, supporting: 1, opposing: 1, mixed: 0, direction: 'mixed', newly_covered: 2 });
    expect(r.timeline.at(-1)).toMatchObject({ covered: 2, coverage_percent: 100, opposing: 1, opposing_percent: 50 });
  });

  it('uses publication dates, fills empty months and does not backdate current fulfilment', () => {
    const f = fixture();
    const c = f.criterion('implemented-now', 'fulfilled');
    f.impact(c, f.law('first', '2025-03-15'), 1);
    f.impact(c, f.law('later', '2025-05-02'), 2);
    f.law('latest-unlinked', '2025-06-04');
    const r = f.report();
    expect(r.timeline.map(p => [p.date, p.covered, p.newly_covered])).toEqual([
      ['2025-02-28', 0, 0], ['2025-03-31', 1, 1], ['2025-04-30', 1, 0], ['2025-05-31', 1, 0], ['2025-06-04', 1, 0],
    ]);
    expect(r.timeline.flatMap(p => p.law_ids)).toEqual(['first', 'later']);
    expect(r.last_assessed_at).toBe('2026-02-01');
    expect(r.timeline.every(p => !('fulfilled' in p))).toBe(true);
    expect(r.law_effects.find(l => l.id === 'later')!.coverage_points).toBe(0);
  });

  it('does not award the same increase twice to laws published on the same date', () => {
    const f = fixture();
    const shared = f.criterion('shared', 'partial');
    const unique = f.criterion('unique', 'partial');
    const a = f.law('a', '2025-04-02');
    const b = f.law('b', '2025-04-02');
    f.impact(shared, a); f.impact(shared, b); f.impact(unique, a);
    const r = f.report();
    expect(r.law_effects.find(l => l.id === 'a')).toMatchObject({ newly_covered: 1, shared_newly_covered: 1, coverage_points: 50 });
    expect(r.law_effects.find(l => l.id === 'b')).toMatchObject({ newly_covered: 0, shared_newly_covered: 1, coverage_points: 0 });
    expect(r.timeline.at(-1)).toMatchObject({ covered: 2, newly_covered: 2, coverage_percent: 100 });
    f.data.impacts.reverse(); f.data.laws.reverse();
    expect(f.report()).toEqual(r);
  });

  it('keeps topic denominators independent and includes uncovered topics', () => {
    const f = fixture();
    const c = f.criterion('multi-topic', 'partial', ['arbeit', 'soziales']);
    f.criterion('open', 'unassessed', ['arbeit']);
    f.criterion('uncovered', 'unassessed', ['klima']);
    f.impact(c, f.law('example', '2025-03-01'));
    expect(f.report().topics.map(t => [t.topic, t.total, t.covered, t.partial, t.unknown])).toEqual([
      ['arbeit', 2, 1, 1, 1], ['soziales', 1, 1, 1, 0], ['klima', 1, 0, 0, 1],
    ]);
  });

  it('agrees with the final live coverage and partitions every programme denominator', () => {
    const data = getData('live');
    for (const program of data.programs) {
      const report = partyInsights(data, [program]);
      const { total, fulfilled, partial, contradicted, mixed, unknown, covered } = report.criteria;
      expect(fulfilled + partial + contradicted + mixed + unknown).toBe(total);
      if (report.timeline.length) expect(report.timeline.at(-1)!.covered).toBe(covered);
      expect(report.laws.total).toBe(new Set(report.law_effects.map(l => l.id)).size);
    }
  });

  it('formats unknowns and small changes honestly with German numbers', () => {
    expect(formatPercentage(null)).toBe('—');
    expect(formatPercentage(0)).toBe('0 %');
    expect(formatPercentage(1 / 1384 * 100)).toBe('<0,1 %');
    expect(formatPercentage(7 / 1384 * 100)).toBe('0,5 %');
  });
});
