import { describe, expect, it } from 'vitest';
import { getData } from '../../src/lib/data';
import { criterionOutcomes, metrics } from '../../src/lib/metrics';
import { matchingRecords, pageLinks, paginate, parsePage, parsePageSize, progressLabel, topicProgress } from '../../src/lib/criteria-browser';
import { searchText } from '../../src/lib/program-reader-search';

describe('bounded, complete pagination', () => {
  it('uses twenty items by default and accepts only supported page sizes', () => {
    for (const size of [null, '', '0', '-1', '5', '21', '1e4', 'NaN', 'Infinity']) expect(parsePageSize(size)).toBe(20);
    for (const size of [20, 50, 100]) expect(parsePageSize(String(size))).toBe(size);
  });

  it('rejects invalid, fractional and unsafe page numbers', () => {
    for (const page of [null, '', '0', '-2', '3.5', '1e2', 'Infinity', 'oops', '9007199254740992']) expect(parsePage(page)).toBe(1);
    expect(parsePage('27')).toBe(27);
  });

  it('handles empty, exact, partial and out-of-range pages', () => {
    expect(paginate(0, 7, 20)).toEqual({ page: 1, pages: 1, start: 0, end: 0 });
    expect(paginate(40, 2, 20)).toEqual({ page: 2, pages: 2, start: 20, end: 40 });
    expect(paginate(41, 999, 20)).toEqual({ page: 3, pages: 3, start: 40, end: 41 });
    expect(paginate(41, 0, 20).page).toBe(1);
  });

  it('makes every result reachable exactly once, including beyond the old 100-row cutoff', () => {
    const records = Array.from({ length: 1384 }, (_, i) => i);
    for (const size of [20, 50, 100]) {
      const visited: number[] = [];
      const { pages } = paginate(records.length, 1, size);
      for (let page = 1; page <= pages; page++) {
        const { start, end } = paginate(records.length, page, size);
        const slice = records.slice(start, end);
        expect(slice.length).toBeLessThanOrEqual(size);
        visited.push(...slice);
      }
      expect(visited).toEqual(records);
    }
  });

  it('keeps first, last and current pages reachable with a small control set', () => {
    expect(pageLinks(1, 1)).toEqual([1]);
    expect(pageLinks(1, 8)).toEqual([1, 2, 3, 4, 5, 'gap', 8]);
    expect(pageLinks(37, 70)).toEqual([1, 'gap', 36, 37, 38, 'gap', 70]);
    expect(pageLinks(70, 70)).toEqual([1, 'gap', 66, 67, 68, 69, 70]);
    for (let page = 1; page <= 100; page++) {
      const links = pageLinks(page, 100);
      const numbers = links.filter(link => typeof link === 'number');
      expect(links.length).toBeLessThanOrEqual(7);
      expect(numbers[0]).toBe(1);
      expect(numbers.at(-1)).toBe(100);
      expect(numbers).toContain(page);
      expect(new Set(numbers).size).toBe(numbers.length);
    }
  });
});

describe('combined filters', () => {
  const records = [
    { search: searchText('Straße, höhere Löhne'), topics: ['arbeit', 'soziales'], parties: ['spd'], status: 'partial' },
    { search: searchText('Löhne in der Pflege'), topics: ['gesundheit', 'arbeit'], parties: ['linke'], status: 'unassessed' },
  ];
  const empty = { q: '', topic: '', party: '', status: '' };

  it('normalizes German text and combines every word and all filters', () => {
    expect(matchingRecords(records, empty)).toEqual(records);
    expect(matchingRecords(records, { q: 'HOHERE strasse', topic: 'soziales', party: 'spd', status: 'partial' })).toEqual([records[0]]);
    expect(matchingRecords(records, { ...empty, q: 'loHNe', topic: 'arbeit' })).toEqual(records);
    expect(matchingRecords(records, { ...empty, topic: 'arbeit', party: 'linke', status: 'partial' })).toEqual([]);
    expect(matchingRecords(records, { ...empty, q: '<script>alert(1)</script>' })).toEqual([]);
  });
});

describe('honest topic progress', () => {
  it('counts each multi-tag criterion once in every applicable topic', () => {
    const summaries = topicProgress([
      { topics: ['arbeit', 'soziales', 'arbeit'], status: 'fulfilled', covered: true },
      { topics: ['arbeit'], status: 'partial', covered: true },
      { topics: ['arbeit'], status: 'contradicted', covered: true },
      { topics: ['arbeit'], status: 'mixed', covered: true },
      { topics: ['arbeit'], status: 'unassessed', covered: false },
    ]);
    expect(summaries.get('arbeit')).toEqual({ total: 5, covered: 4, counts: { fulfilled: 1, partial: 1, contradicted: 1, mixed: 1, unassessed: 1 } });
    expect(summaries.get('soziales')?.total).toBe(1);
    expect(summaries.has('gesundheit')).toBe(false);
    expect(topicProgress([]).size).toBe(0);
    expect(progressLabel(summaries.get('arbeit')!)).toContain('1 gemischte Wirkung, 1 offen');
  });

  it('agrees with existing metrics for each topic and never merges programme periods', () => {
    const data = getData('demo');
    for (const program of data.programs) {
      const criteria = data.criteria.filter(c => c.program_id === program.id);
      const outcomes = criterionOutcomes(criteria, data.impacts, [program]);
      const summaries = topicProgress(outcomes.map(({ criterion, status, covered }) => ({ topics: criterion.tags, status, covered })));
      for (const [topic, summary] of summaries) {
        const expected = metrics(criteria.filter(c => c.tags.includes(topic)), data.impacts, [program]);
        expect(summary).toEqual({ total: expected.total, covered: expected.covered, counts: {
          fulfilled: expected.fulfilled, partial: expected.partial, contradicted: expected.contradicted, mixed: expected.mixed, unassessed: expected.unknown,
        } });
      }
    }
  });

  it('does not expose an unaccepted assessment as implemented in a row or a topic', () => {
    const data = structuredClone(getData('demo'));
    const criterion = data.criteria.find(c => c.party_id === 'bsw')!;
    criterion.assessment.status = 'fulfilled';
    criterion.review.status = 'proposed';
    const [outcome] = criterionOutcomes([criterion], data.impacts, data.programs);
    expect(outcome.status).toBe('unassessed');
    expect(outcome.covered).toBe(false);
    criterion.review.status = 'rejected';
    expect(criterionOutcomes([criterion], data.impacts, data.programs)).toEqual([]);
    criterion.review.status = 'proposed';
    data.programs.find(p => p.id === criterion.program_id)!.review.status = 'rejected';
    expect(criterionOutcomes([criterion], data.impacts, data.programs)).toEqual([]);
  });
});
