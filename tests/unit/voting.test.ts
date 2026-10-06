import { describe, expect, it } from 'vitest';
import { getData } from '../../src/lib/data';
import { voteTotals } from '../../src/lib/metrics';
import { comparableVotes, comparisonOutcome, groupPosition, publicVote, votingComparisons, votingCoverage, votingPatterns } from '../../src/lib/voting';
import type { Data, GroupVote, Vote } from '../../src/lib/types';

const group = (position: GroupVote['position'] = 'yes'): GroupVote => ({
  group: 'Test faction', party_id: 'spd', position, yes: null, no: null, abstain: null, absent: null, invalid: null,
});
function fixture(): Data {
  const data = structuredClone(getData('demo'));
  const impact = data.impacts[0];
  const criterion = data.criteria.find(c => c.id === impact.criterion_id)!;
  const program = data.programs.find(p => p.id === criterion.program_id)!;
  const law = data.laws.find(l => l.id === impact.law_id)!;
  program.period_start = '2025-01-01'; program.period_end = null; program.published_at = '2025-01-01';
  program.review.status = criterion.review.status = impact.review.status = 'proposed';
  impact.verification = 'passed'; impact.score = -1;
  impact.evaluation = { status: 'accepted', model: 'openai/gpt-6-sol', method: 'sol-final-v1', input_sha256: 'a'.repeat(64), decided_at: '2025-06-01' };
  law.published_at = '2025-06-01';
  const source = { url: 'https://dserver.bundestag.de/btp/21/test.pdf', publisher: 'Test fixture', title: 'Test protocol', retrieved_at: '2025-06-01', sha256: 'a'.repeat(64), license_note: '' };
  const vote: Vote = {
    id: 'demo-vote-test', schema_version: '1.0', dataset: 'demo', law_id: law.id, date: '2025-05-29',
    motion: 'Test final vote', stage: 'final_passage', type: 'group_record', source, compares_to_law: true,
    review: { status: 'proposed', reviewer: null, reviewed_at: null, note: '' },
    groups: [{ ...group(), party_id: criterion.party_id }], members: [],
    evidence: { method: 'bundestag-dip-v1', procedure_id: '12', position_id: '123', decision_index: 0,
      law_match: 'official_reference', procedure_source: source, position_source: source,
      protocol_source: source, protocol_page: '1234A', document_numbers: ['21/1'],
      text: 'Test decision', quote: 'Test decision', roll_call_id: null, roll_call_source: null },
  };
  return { ...data, laws: [law], impacts: [impact], criteria: [criterion], programs: [program], votes: [vote], votingCoverage: null };
}

describe('positions are evidence, not coalition/majority guesses', () => {
  it('leaves protocol counts unknown rather than zero', () => {
    expect(voteTotals([group()])).toBeNull();
    expect(voteTotals([])).toBeNull();
    expect(groupPosition(group())).toBe('yes');
    expect(groupPosition(group('unknown'))).toBe('unknown');
  });
  it('preserves dissent and separates non-participation from opposition', () => {
    const split = { ...group(), yes: 100, no: 1, abstain: 2, absent: 3, invalid: 1 };
    expect(groupPosition(split)).toBe('mixed');
    expect(voteTotals([split])).toEqual({ yes: 100, no: 1, abstain: 2, absent: 3, invalid: 1, cast: 104, total: 107 });
    expect(comparisonOutcome({ ...split, yes: 0, no: 0, abstain: 0 }, -2)).toBe('neutral');
    expect(comparisonOutcome(group('abstain'), -2)).toBe('neutral');
    expect(comparisonOutcome(group('unknown'), -2)).toBe('unknown');
  });
  it.each([
    ['yes', -2, 'tension'], ['yes', 2, 'consistent'], ['no', 1, 'tension'], ['no', -1, 'consistent'],
    ['yes', 0, 'contextual'], ['mixed', -1, 'mixed'],
  ] as const)('compares %s with signed law effect %s without judging motives', (position, score, outcome) => {
    expect(comparisonOutcome(group(position), score)).toBe(outcome);
  });
});

describe('source-linked programme comparisons', () => {
  it('uses accepted Sol evidence and official imports without inventing human review', () => {
    const data = fixture();
    expect(publicVote(data.votes[0])).toBe(true);
    const [result] = votingComparisons(data);
    expect(result.outcome).toBe('tension');
    expect(result.tension_ballots).toBeNull();
    expect(result.vote.review.status).toBe('proposed');
    expect(result.criterion.id).toBe(data.impacts[0].criterion_id);
  });
  it('never counts drafts, rejected or missing-context impacts', () => {
    for (const state of ['rejected', 'missing_context', 'draft', 'other-model', 'citizen-rejected']) {
      const data = fixture();
      if (state === 'draft') data.impacts[0].evaluation = null;
      else if (state === 'other-model') data.impacts[0].evaluation!.model = 'other-model';
      else if (state === 'citizen-rejected') data.impacts[0].review.status = 'rejected';
      else data.impacts[0].evaluation!.status = state as 'rejected' | 'missing_context';
      expect(votingComparisons(data)).toEqual([]);
    }
  });
  it('respects editorial corrections over agent judgments', () => {
    const data = fixture();
    data.impacts[0].review.status = 'reviewed';
    data.impacts[0].evaluation!.status = 'rejected';
    data.impacts[0].score = 2;
    expect(votingComparisons(data)[0].outcome).toBe('consistent');
  });
  it.each(['second_reading', 'amendment', 'resolution', 'procedural', 'unknown'] as const)('excludes %s from final law-effect comparisons', stage => {
    const data = fixture(); data.votes[0].stage = stage;
    expect(votingComparisons(data)).toEqual([]);
  });
  it('excludes provisional title matches, stale sources and ambiguous finals', () => {
    let data = fixture(); data.votes[0].evidence!.law_match = 'exact_title';
    expect(votingComparisons(data)).toEqual([]);
    data = fixture(); data.votes.push({ ...data.votes[0], id: 'demo-another-final' });
    expect(comparableVotes(data)).toEqual([]);
    for (const status of ['source_error', 'source_changed', 'ambiguous'] as const) {
      data = fixture(); data.votingCoverage = { schema_version: '1.0', dataset: 'live', note: '', items: [{
        law_id: data.laws[0].id, checked_at: '2025-06-01', status, procedure_ids: ['12'], vote_ids: [data.votes[0].id], reason: 'Test fixture',
      }] };
      expect(votingComparisons(data)).toEqual([]);
    }
  });
  it('uses the vote date, not only the later promulgation, for programme eligibility', () => {
    const data = fixture(); data.programs[0].published_at = '2025-05-30';
    expect(votingComparisons(data)).toEqual([]);
    const ended = fixture(); ended.programs[0].period_end = '2025-05-29';
    expect(votingComparisons(ended)).toEqual([]);
  });
  it('does not attribute votes to an unrelated or missing party', () => {
    const data = fixture(); data.votes[0].groups[0].party_id = null;
    expect(votingComparisons(data)).toEqual([]);
  });
  it('shows exact split-ballot directions instead of blaming an entire faction', () => {
    const data = fixture(); data.votes[0].type = 'roll_call';
    Object.assign(data.votes[0].groups[0], { yes: 1, no: 100, abstain: 2, absent: 3, invalid: 0 });
    const [row] = votingComparisons(data);
    expect(row.outcome).toBe('mixed');
    expect(row.tension_ballots).toBe(1);
    expect(row.consistent_ballots).toBe(100);
  });
  it('deduplicates laws across readings and keeps programme pairs distinct', () => {
    const data = fixture();
    data.votes.push({ ...data.votes[0], id: 'demo-vote-second', stage: 'second_reading', compares_to_law: false });
    expect(votingCoverage(data)).toMatchObject({ laws: 1, with_positions: 1, comparable_laws: 1, decision_only: 0 });
    const party = data.criteria[0].party_id;
    expect(votingPatterns(data).find(row => row.party_id === party)).toMatchObject({ laws: 1, comparisons: 1, compared_laws: 1 });
  });
  it('publishes structured XML evidence only with an identified official chair block', () => {
    const data = fixture(); const vote = data.votes[0]; const evidence = vote.evidence!;
    evidence.method = 'bundestag-structured-v2';
    expect(publicVote(vote)).toBe(false);
    evidence.protocol_format = 'xml'; evidence.protocol_block = 0;
    evidence.protocol_source = { ...vote.source, url: 'https://www.bundestag.de/resource/blob/123/21012.xml' };
    vote.source = evidence.protocol_source;
    expect(publicVote(vote)).toBe(true);
    evidence.protocol_block = -1;
    expect(publicVote(vote)).toBe(false);
  });
  it('never uses a partial-law decision or disputed secondary ballots as a programme conflict', () => {
    const partial = fixture(); partial.votes[0].scope = 'partial_law';
    expect(votingComparisons(partial)).toEqual([]);
    const data = fixture();
    data.votes[0].evidence!.cross_check = { provider: 'abgeordnetenwatch', status: 'mismatch',
      checked_at: '2025-06-01', poll_id: '5', source: null, total_members: 1, compared_members: 1, matched_members: 0, note: '' };
    expect(publicVote(data.votes[0])).toBe(true); // Official evidence remains visible.
    expect(votingComparisons(data)).toEqual([]);
    const unavailable = fixture();
    unavailable.votes[0].evidence!.cross_check = { ...data.votes[0].evidence!.cross_check, status: 'source_error' };
    expect(votingComparisons(unavailable)).toHaveLength(1); // Optional provider does not erase official votes.
  });
  it('requires the workbook and official index provenance for new roll calls', () => {
    const vote = fixture().votes[0]; vote.type = 'roll_call';
    Object.assign(vote.evidence!, { method: 'bundestag-structured-v2', ballot_number: 1,
      ballot_match: 'official_title_and_tallies', roll_call_source: vote.source,
      ballot_index_source: { ...vote.source, url: 'https://www.bundestag.de/ajax/filterlist/de/parlament/plenum/abstimmung/liste/462112-462112?limit=30&offset=0' } });
    expect(publicVote(vote)).toBe(false);
    vote.members = [{ name: 'Erika Testperson', group: 'SPD', vote: 'yes', source_row: 2 }];
    expect(publicVote(vote)).toBe(true);
    vote.evidence!.ballot_index_source!.url += '&apiKey=not-a-real-key';
    expect(publicVote(vote)).toBe(false);
  });
  it('does not publish a rejected vote or a credential-bearing source', () => {
    const data = fixture(); data.votes[0].review.status = 'rejected';
    expect(publicVote(data.votes[0])).toBe(false);
    data.votes[0].review.status = 'proposed'; data.votes[0].source.url += '?apiKey=not-a-real-key';
    expect(publicVote(data.votes[0])).toBe(false);
  });
});
