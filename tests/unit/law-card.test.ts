import { describe, expect, it } from 'vitest';
import { getData } from '../../src/lib/data';
import { cardVote, groupVotePreview, partyLinks } from '../../src/lib/law-card';
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
    expect(cardVote(data, vote.law_id)?.id).toBe(vote.id);
    expect(cardVote(data, 'missing-law')).toBeUndefined();
  });
  it('does not pick an earlier reading or cherry-pick conflicting final votes', () => {
    const data = structuredClone(getData('live'));
    const vote = comparableVotes(data).find(v => v.groups.length)!;
    data.votes = [{ ...vote, id: 'earlier', stage: 'second_reading' }, vote, { ...vote, id: 'conflicting-final' }];
    expect(cardVote(data, vote.law_id)).toBeUndefined();
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
