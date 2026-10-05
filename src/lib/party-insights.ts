import { metrics, publicImpact } from './metrics';
import type { Data, Impact, Program } from './types';

export function percentage(count: number, total: number) {
  return total ? count / total * 100 : null;
}

export function formatPercentage(value: number | null) {
  if (value === null) return '—';
  // A small, real contribution must not disappear into a rounded zero.
  if (value > 0 && value < 0.1) return '<0,1 %';
  return `${new Intl.NumberFormat('de-DE', { maximumFractionDigits: 1 }).format(value)} %`;
}

/** Build-time, programme-scoped citizen statistics. Never infer fulfilment from law scores. */
export function partyInsights(data: Pick<Data, 'criteria' | 'impacts' | 'laws'>, programs: Program[]) {
  const active = new Map(programs.filter(p => p.review.status !== 'rejected').map(p => [p.id, p]));
  const criteria = data.criteria.filter(c => c.review.status !== 'rejected' && active.has(c.program_id));
  const criterionById = new Map(criteria.map(c => [c.id, c]));
  const inWindow = (date: string, program: Program) => date >= program.period_start &&
    date >= program.published_at && (!program.period_end || date < program.period_end);
  const laws = data.laws.filter(l => l.review.status !== 'rejected' && [...active.values()].some(p => inWindow(l.published_at, p)));
  const lawById = new Map(laws.map(l => [l.id, l]));
  // The editorial path follows the same reviewed programme/criterion rule as metrics().
  // Canonical records already have validated source quotations; don't include dangling,
  // rejected, out-of-period or non-final links in a reconstructed chronology.
  const impacts = [...new Map(data.impacts.filter(i => {
    const criterion = criterionById.get(i.criterion_id);
    const law = lawById.get(i.law_id);
    if (!criterion || !law || !publicImpact(i)) return false;
    const program = active.get(criterion.program_id)!;
    return inWindow(law.published_at, program) && (i.evaluation?.status === 'accepted' ||
      (criterion.review.status === 'reviewed' && program.review.status === 'reviewed'));
  }).map(i => [i.id, i])).values()];
  const stats = metrics(criteria, impacts, [...active.values()]);
  const byLaw = new Map<string, Impact[]>();
  const firstEvidence = new Map<string, { date: string; lawIds: Set<string> }>();
  for (const impact of impacts) {
    const date = lawById.get(impact.law_id)!.published_at;
    const group = byLaw.get(impact.law_id) ?? [];
    group.push(impact);
    byLaw.set(impact.law_id, group);
    const first = firstEvidence.get(impact.criterion_id);
    if (!first || date < first.date) firstEvidence.set(impact.criterion_id, { date, lawIds: new Set([impact.law_id]) });
    else if (date === first.date) first.lawIds.add(impact.law_id);
  }
  const lawEffects = [...byLaw].map(([id, evidence]) => {
    const law = lawById.get(id)!;
    const criterionIds = new Set(evidence.map(i => i.criterion_id));
    const count = (predicate: (impact: Impact) => boolean) => new Set(evidence.filter(predicate).map(i => i.criterion_id)).size;
    const supporting = count(i => i.score > 0);
    const opposing = count(i => i.score < 0);
    const mixed = count(i => i.score === 0);
    const firstHere = [...criterionIds].filter(id => firstEvidence.get(id)!.date === law.published_at);
    // Same-day laws are co-first evidence. Do not arbitrarily assign the increase to
    // one of them or double-count their shared contribution as exclusive progress.
    const newlyCovered = firstHere.filter(id => firstEvidence.get(id)!.lawIds.size === 1).length;
    return {
      id, title: law.title, published_at: law.published_at, citation: law.citation,
      affected: criterionIds.size, supporting, opposing, mixed,
      direction: mixed || (supporting && opposing) ? 'mixed' as const : opposing ? 'opposing' as const : 'supporting' as const,
      newly_covered: newlyCovered, shared_newly_covered: firstHere.length - newlyCovered,
      coverage_points: percentage(newlyCovered, stats.total),
      evidence: evidence.sort((a, b) => a.criterion_id.localeCompare(b.criterion_id) || a.id.localeCompare(b.id)).map(i => ({
        impact_id: i.id, criterion_id: i.criterion_id, criterion_title: criterionById.get(i.criterion_id)!.title,
        score: i.score, rationale: i.rationale,
      })),
    };
  }).sort((a, b) => b.affected - a.affected || b.newly_covered - a.newly_covered ||
    b.published_at.localeCompare(a.published_at) || a.id.localeCompare(b.id));

  const start = [...active.values()].map(p => p.period_start).sort()[0] ?? null;
  const through = laws.map(l => l.published_at).sort().at(-1) ?? null;
  const timeline: {
    date: string; baseline: boolean; covered: number; coverage_percent: number | null;
    opposing: number; opposing_percent: number | null; newly_covered: number; law_ids: string[];
  }[] = [];
  if (start && through && impacts.length && stats.total) {
    const covered = new Set<string>();
    const opposing = new Set<string>();
    const chronological = [...lawEffects].sort((a, b) => a.published_at.localeCompare(b.published_at) || a.id.localeCompare(b.id));
    const before = new Date(`${start}T00:00:00Z`);
    before.setUTCDate(before.getUTCDate() - 1);
    timeline.push({ date: before.toISOString().slice(0, 10), baseline: true, covered: 0, coverage_percent: 0,
      opposing: 0, opposing_percent: 0, newly_covered: 0, law_ids: [] });
    let cursor = 0;
    let month = start.slice(0, 7);
    while (month <= through.slice(0, 7)) {
      const [year, number] = month.split('-').map(Number);
      const monthEnd = new Date(Date.UTC(year, number, 0)).toISOString().slice(0, 10);
      const date = monthEnd < through ? monthEnd : through;
      const previous = covered.size;
      const lawIds: string[] = [];
      while (cursor < chronological.length && chronological[cursor].published_at <= date) {
        const law = chronological[cursor++];
        lawIds.push(law.id);
        law.evidence.forEach(i => { covered.add(i.criterion_id); if (i.score < 0) opposing.add(i.criterion_id); });
      }
      timeline.push({ date, baseline: false, covered: covered.size, coverage_percent: percentage(covered.size, stats.total),
        opposing: opposing.size, opposing_percent: percentage(opposing.size, stats.total),
        newly_covered: covered.size - previous, law_ids: lawIds });
      month = new Date(Date.UTC(year, number, 1)).toISOString().slice(0, 7);
    }
  }

  const topics = [...new Set(criteria.flatMap(c => c.tags))].map(topic => {
    const subset = criteria.filter(c => c.tags.includes(topic));
    const topicStats = metrics(subset, impacts, [...active.values()]);
    return { topic, ...topicStats, fulfilment_percent: percentage(topicStats.fulfilled, topicStats.total) };
  }).sort((a, b) => b.covered - a.covered || b.total - a.total || a.topic.localeCompare(b.topic));
  const acceptedIds = new Set(impacts.map(i => i.id));
  const assessmentDates = criteria.filter(c => c.assessment.status !== 'unassessed' &&
    c.assessment.evidence_ids.length && c.assessment.evidence_ids.every(id => acceptedIds.has(id)))
    .map(c => c.assessment.assessed_at).filter((date): date is string => !!date);
  return {
    program_ids: [...active.keys()].sort(), period_start: start, laws_through: through,
    last_assessed_at: assessmentDates.sort().at(-1) ?? null,
    criteria: stats, fulfilment_percent: percentage(stats.fulfilled, stats.total), coverage_percent: percentage(stats.covered, stats.total),
    laws: { total: lawEffects.length, supporting: lawEffects.filter(l => l.supporting > 0).length,
      opposing: lawEffects.filter(l => l.opposing > 0).length, mixed: lawEffects.filter(l => l.direction === 'mixed').length,
      evidence: impacts.length },
    timeline, law_effects: lawEffects, topics,
  };
}

export type PartyInsights = ReturnType<typeof partyInsights>;
