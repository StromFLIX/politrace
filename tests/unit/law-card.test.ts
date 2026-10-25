import { describe, expect, it } from 'vitest';
import { getData } from '../../src/lib/data';
import { cardVotes, groupVotePreview, partyLinks } from '../../src/lib/law-card';
import { publicImpact } from '../../src/lib/metrics';
import { comparableVotes } from '../../src/lib/voting';
import type { GroupVote } from '../../src/lib/types';

const group: GroupVote = { group: 'Test', party_id: null, yes: null, no: null, abstain: null, absent: null, position: 'yes' };

describe('compact law cards', () => {
  it('groups all published links once by party without aggregating their scores', () => {
    const data = getData('live');
    const law = data.laws.find(l => data.impacts.filter(i => i.law_id === l.id && publicImpact(i)).length > 5)!;
    const groups = partyLinks(data, law.id);
    expect(new Set(groups.map(g => g.party.id)).size).toBe(groups.length);
    const items = groups.flatMap(g => g.items);
    expect(items.map(i => i.impact.id).sort()).toEqual(data.impacts.filter(i => i.law_id === law.id && publicImpact(i)).map(i => i.id).sort());
    for (const g of groups) expect(g.items.every(i => i.criterion.party_id === g.party.id)).toBe(true);
  });
  it('includes official machine-sourced final votes, not just editorial reviews', () => {
    const data = getData('live');
    const vote = comparableVotes(data).find(v => v.review.status === 'proposed' && v.groups.length)!;
    expect(vote).toBeDefined();
    expect(cardVotes(data, vote.law_id).map(v => v.id)).toEqual([vote.id]);
    expect(cardVotes(data, 'missing-law')).toEqual([]);
  });
  it('shows provisional official voting evidence without admitting it to programme comparisons', () => {
    const data = getData('live');
    for (const lawId of ['bgbl-1-2026-314', 'bgbl-1-2026-307', 'bgbl-1-2026-304']) {
      const votes = cardVotes(data, lawId);
      expect(votes).toHaveLength(1);
      expect(votes[0].stage).toBe('final_passage');
      expect(votes[0].evidence?.law_match).toBe('exact_title');
      expect(votes[0].groups.length).toBeGreaterThan(0);
      expect(comparableVotes(data).some(v => v.law_id === lawId)).toBe(false);
    }
    expect(cardVotes(data, 'bgbl-1-2026-304')[0].groups).toHaveLength(2);
  });
  it('prefers final readings but preserves every conflicting final separately', () => {
    const data = structuredClone(getData('live'));
    const vote = comparableVotes(data).find(v => v.groups.length)!;
    data.votes = [{ ...vote, id: 'earlier', stage: 'second_reading' }, vote, { ...vote, id: 'conflicting-final' }];
    expect(cardVotes(data, vote.law_id).map(v => v.id).sort()).toEqual([vote.id, 'conflicting-final'].sort());
    expect(comparableVotes(data)).toEqual([]);
  });
  it('retains actual stages and decision-only records when no final vote is published', () => {
    const data = structuredClone(getData('live'));
    const vote = comparableVotes(data).find(v => v.groups.length)!;
    const earlier = { ...vote, stage: 'second_reading' as const, compares_to_law: false };
    data.votes = [earlier];
    expect(cardVotes(data, vote.law_id)).toEqual([earlier]);
    const decisions = { ...data, votes: [{ ...earlier, type: 'plenary_record' as const, groups: [] }] };
    expect(cardVotes(decisions, vote.law_id)[0].groups).toEqual([]);
    expect(comparableVotes(data)).toEqual([]);
  });
  it('never publishes rejected or unsupported imports', () => {
    const data = structuredClone(getData('live'));
    const vote = comparableVotes(data).find(v => v.groups.length)!;
    data.votes = [
      { ...vote, review: { ...vote.review, status: 'rejected' } },
      { ...vote, id: 'unsupported', evidence: null, review: { ...vote.review, status: 'proposed' } },
    ];
    expect(cardVotes(data, vote.law_id)).toEqual([]);
  });
  it('never fabricates counts for protocol positions', () => {
    expect(groupVotePreview(group, 'group_record')).toEqual({ position: 'yes', totals: null, label: 'Zustimmung' });
    expect(groupVotePreview({ ...group, position: 'unknown' }, 'group_record').label).toBe('Unbekannt');
  });
  it('preserves split ballots, absence and invalid votes in small bar data', () => {
    const preview = groupVotePreview({ ...group, yes: 100, no: 1, abstain: 2, absent: 3, invalid: 1 }, 'roll_call');
    expect(preview.position).toBe('mixed');
    expect(preview.totals?.total).toBe(107);
    expect(preview.label).toBe('100 Ja, 1 Nein, 2 Enthaltungen, 3 nicht abgegeben, 1 ungültig');
  });
});
