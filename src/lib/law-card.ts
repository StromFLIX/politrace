import { publicImpact, voteTotals } from './metrics';
import { groupPosition, positionLabels, publicVote } from './voting';
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

const voteCache = new WeakMap<Data, Map<string, Vote[]>>();
// Evidence display is not programme comparison eligibility. In particular, a
// provisional exact-title match still has publishable, explicitly labelled votes.
export function cardVotes(data: Data, lawId: string): Vote[] {
  let votes = voteCache.get(data);
  if (!votes) {
    votes = new Map();
    for (const vote of data.votes.filter(publicVote)) {
      votes.set(vote.law_id, [...votes.get(vote.law_id) ?? [], vote]);
    }
    for (const [id, records] of votes) {
      const finals = records.filter(v => v.stage === 'final_passage');
      // Prefer finals, but never cherry-pick one of multiple final decisions.
      votes.set(id, (finals.length ? finals : records).sort((a, b) =>
        b.date.localeCompare(a.date) || a.id.localeCompare(b.id)));
    }
    voteCache.set(data, votes);
  }
  return votes.get(lawId) ?? [];
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
