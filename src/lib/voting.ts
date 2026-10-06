import type { Ballot, Criterion, Data, GroupPosition, GroupVote, Impact, Law, Party, Program, Vote, VoteStage } from './types';
import { publicImpact } from './metrics';

export const ballotLabels: Record<Ballot, string> = {
  yes: 'Ja', no: 'Nein', abstain: 'Enthaltung', absent: 'Nicht abgegeben', invalid: 'Ungültig',
};
export const positionLabels: Record<GroupPosition, string> = {
  yes: 'Zustimmung', no: 'Ablehnung', abstain: 'Enthaltung', mixed: 'Geteiltes Stimmverhalten', unknown: 'Unbekannt',
};
export const stageLabels: Record<VoteStage, string> = {
  final_passage: 'Schlussabstimmung', second_reading: 'Zweite Beratung', amendment: 'Änderungsantrag',
  resolution: 'Entschließung', procedural: 'Verfahrensentscheidung', unknown: 'Beschlussstufe offen',
};
export const coverageLabels = {
  recorded: 'Stimmverhalten belegt', decision_only: 'Bisher nur Beschluss belegt', not_found: 'Beleg noch offen',
  ambiguous: 'Zuordnung nicht eindeutig', source_error: 'Quelle derzeit nicht abrufbar / prüfbar', source_changed: 'Quellenzuordnung geändert',
};
export type ComparisonOutcome = 'tension' | 'consistent' | 'mixed' | 'neutral' | 'contextual' | 'unknown';
export const outcomeLabels: Record<ComparisonOutcome, string> = {
  tension: 'Potenzielles Spannungsfeld', consistent: 'Richtung vereinbar', mixed: 'Geteiltes Stimmverhalten',
  neutral: 'Keine Ja-/Nein-Position', contextual: 'Gemischte Gesetzeswirkung', unknown: 'Position unbekannt',
};

function officialSource(source: Vote['source']) {
  try {
    const url = new URL(source.url);
    return /^[a-f0-9]{64}$/.test(source.sha256 ?? '') && url.protocol === 'https:' && !url.username && !url.password && !url.port &&
      ['search.dip.bundestag.de', 'dserver.bundestag.de', 'www.bundestag.de'].includes(url.hostname) &&
      (!url.search || (url.hostname === 'www.bundestag.de' && (/^\?id=\d+$/.test(url.search) ||
        (url.pathname.startsWith('/ajax/filterlist/de/parlament/plenum/abstimmung/liste/') && /^\?limit=\d+&offset=\d+$/.test(url.search)))));
  } catch { return false; }
}

// Official deterministic evidence is publishable without pretending a human approved it.
export function publicVote(vote: Vote) {
  if (vote.review.status === 'rejected') return false;
  if (vote.review.status === 'reviewed') return true;
  const evidence = vote.evidence;
  if (!evidence || !['bundestag-dip-v1', 'bundestag-structured-v2'].includes(evidence.method) ||
      !officialSource(vote.source) || !officialSource(evidence.procedure_source) || !officialSource(evidence.position_source)) return false;
  if (evidence.method === 'bundestag-structured-v2') {
    if (vote.type === 'group_record' && (evidence.protocol_format !== 'xml' || !Number.isInteger(evidence.protocol_block) || (evidence.protocol_block ?? -1) < 0 ||
        !evidence.protocol_source || !officialSource(evidence.protocol_source))) return false;
    if (vote.type === 'roll_call' && (!vote.members?.length || !Number.isInteger(evidence.ballot_number) || (evidence.ballot_number ?? 0) < 1 || !evidence.ballot_match || !evidence.ballot_index_source ||
        !officialSource(evidence.ballot_index_source) || !evidence.roll_call_source || !officialSource(evidence.roll_call_source))) return false;
  }
  return true;
}

export function groupPosition(group: GroupVote): GroupPosition {
  if (group.yes == null || group.no == null || group.abstain == null) return group.position ?? 'unknown';
  const positions = (['yes', 'no', 'abstain'] as const).filter(key => group[key]! > 0);
  // Never replace dissent or abstentions with a majority label for the whole faction.
  return positions.length > 1 ? 'mixed' : positions[0] ?? 'unknown';
}

export function comparisonOutcome(group: GroupVote, score: Impact['score']): ComparisonOutcome {
  const position = groupPosition(group);
  if (position === 'unknown') return group.yes == null ? 'unknown' : 'neutral';
  if (position === 'abstain') return 'neutral';
  if (score === 0) return 'contextual';
  if (position === 'mixed') return 'mixed';
  return (position === 'yes') === (score > 0) ? 'consistent' : 'tension';
}

export function comparableVotes(data: Data): Vote[] {
  const coverage = new Map(data.votingCoverage?.items.map(row => [row.law_id, row]) ?? []);
  const candidates = data.votes.filter(v => publicVote(v) && v.stage === 'final_passage' && v.compares_to_law &&
    v.scope !== 'partial_law' && v.evidence?.cross_check?.status !== 'mismatch' &&
    v.evidence?.law_match === 'official_reference' && !['source_error', 'source_changed', 'ambiguous'].includes(coverage.get(v.law_id)?.status ?? '') &&
    data.laws.some(l => l.id === v.law_id && l.review.status !== 'rejected' && v.date <= l.published_at));
  // Multiple final decisions need version-specific reconciliation, not a cherry-picked vote.
  const counts = new Map<string, number>();
  for (const v of candidates) counts.set(v.law_id, (counts.get(v.law_id) ?? 0) + 1);
  return candidates.filter(v => counts.get(v.law_id) === 1);
}

export type VotingComparison = {
  id: string; vote: Vote; law: Law; impact: Impact; criterion: Criterion; program: Program; party: Party;
  group: GroupVote; position: GroupPosition; outcome: ComparisonOutcome;
  // Exact named counts, not a majority claim; null for non-named decisions.
  consistent_ballots: number | null; tension_ballots: number | null;
};
const comparisonCache = new WeakMap<Data, VotingComparison[]>();
export function votingComparisons(data: Data): VotingComparison[] {
  const cached = comparisonCache.get(data);
  if (cached) return cached;
  const laws = new Map(data.laws.map(l => [l.id, l]));
  const criteria = new Map(data.criteria.map(c => [c.id, c]));
  const programs = new Map(data.programs.map(p => [p.id, p]));
  const parties = new Map(data.parties.map(p => [p.id, p]));
  const impacts = new Map<string, Impact[]>();
  for (const impact of data.impacts.filter(publicImpact)) {
    if (impact.review.status !== 'reviewed' && impact.verification !== 'passed') continue;
    impacts.set(impact.law_id, [...impacts.get(impact.law_id) ?? [], impact]);
  }
  const result: VotingComparison[] = [];
  for (const vote of comparableVotes(data)) for (const impact of impacts.get(vote.law_id) ?? []) {
    const criterion = criteria.get(impact.criterion_id);
    const program = criterion && programs.get(criterion.program_id);
    const party = criterion && parties.get(criterion.party_id);
    const law = laws.get(vote.law_id)!;
    if (!criterion || !program || !party || criterion.review.status === 'rejected' || program.review.status === 'rejected' ||
        program.party_id !== criterion.party_id || program.published_at > vote.date || program.published_at > law.published_at ||
        program.period_start > vote.date || program.period_start > law.published_at ||
        (program.period_end && (vote.date >= program.period_end || law.published_at >= program.period_end))) continue;
    const group = vote.groups.find(g => g.party_id === party.id);
    if (!group) continue; // No assertion about an absent/unidentified faction.
    result.push({ id: `${vote.id}--${impact.id}`, vote, law, impact, criterion, program, party, group,
      position: groupPosition(group), outcome: comparisonOutcome(group, impact.score),
      consistent_ballots: impact.score === 0 ? null : (impact.score > 0 ? group.yes : group.no),
      tension_ballots: impact.score === 0 ? null : (impact.score > 0 ? group.no : group.yes),
    });
  }
  result.sort((a, b) => b.vote.date.localeCompare(a.vote.date) || a.id.localeCompare(b.id));
  comparisonCache.set(data, result);
  return result;
}

export function votingCoverage(data: Data) {
  const votes = data.votes.filter(publicVote);
  const withPositions = new Set(votes.filter(v => v.groups.length).map(v => v.law_id));
  const withDecisions = new Set(votes.map(v => v.law_id));
  return {
    laws: data.laws.length, checked: data.votingCoverage?.items.length ?? 0,
    with_positions: withPositions.size, decision_only: [...withDecisions].filter(id => !withPositions.has(id)).length,
    without_decisions: data.laws.filter(l => !withDecisions.has(l.id)).length,
    named_decisions: new Set(votes.filter(v => v.type === 'roll_call').map(v => v.evidence?.roll_call_id ?? v.id)).size,
    comparable_laws: new Set(comparableVotes(data).filter(v => v.groups.length).map(v => v.law_id)).size,
    errors: data.votingCoverage?.items.filter(row => ['source_error', 'source_changed'].includes(row.status)).length ?? 0,
  };
}

export function votingPatterns(data: Data) {
  const final = comparableVotes(data);
  const comparisons = votingComparisons(data);
  return data.parties.map(party => {
    const groups = final.flatMap(v => v.groups.filter(g => g.party_id === party.id));
    const rows = comparisons.filter(c => c.party.id === party.id);
    const byPosition = Object.fromEntries(Object.keys(positionLabels).map(p => [p, groups.filter(g => groupPosition(g) === p).length]));
    const byOutcome = Object.fromEntries(Object.keys(outcomeLabels).map(o => [o, rows.filter(c => c.outcome === o).length]));
    return { party_id: party.id, laws: groups.length, positions: byPosition, comparisons: rows.length,
      compared_laws: new Set(rows.map(c => c.law.id)).size, outcomes: byOutcome };
  });
}
