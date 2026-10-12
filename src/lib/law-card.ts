import { publicImpact, voteTotals } from './metrics';
import { comparableVotes, groupPosition, positionLabels } from './voting';
import type { Data, GroupVote, Vote } from './types';

// Keep every evidence link and its individual score; never sum effects for a party.
export function partyLinks(data: Data, lawId: string) {
  const criteria = new Map(data.criteria.map(c => [c.id, c]));
  const links = data.impacts.filter(i => i.law_id === lawId && publicImpact(i));
  return data.parties.flatMap(party => {
    const items = links.flatMap(impact => {
      const criterion = criteria.get(impact.criterion_id);
      return criterion?.party_id === party.id ? [{ impact, criterion }] : [];
    });
    return items.length ? [{ party, items }] : [];
  });
}

const voteCache = new WeakMap<Data, Map<string, Vote>>();
export function cardVote(data: Data, lawId: string) {
  let votes = voteCache.get(data);
  if (!votes) {
    votes = new Map(comparableVotes(data).map(v => [v.law_id, v]));
    voteCache.set(data, votes);
  }
  return votes.get(lawId);
}

export function groupVotePreview(group: GroupVote, type: Vote['type']) {
  const totals = type === 'roll_call' ? voteTotals([group]) : null;
  const position = groupPosition(group);
  return {
    position,
    totals,
    label: totals
      ? `${totals.yes} Ja, ${totals.no} Nein, ${totals.abstain} Enthaltungen, ${totals.absent} nicht abgegeben, ${totals.invalid} ungültig`
      : positionLabels[position],
  };
}
