import type { Ballot, Criterion, Impact, Program } from './types';

export function publicImpact(impact: Impact) {
  return impact.review.status !== 'rejected' && (impact.review.status === 'reviewed' ||
    (impact.evaluation?.status === 'accepted' && impact.evaluation.model === 'openai/gpt-6-sol'));
}

// One eligibility decision for totals, topic summaries, row badges and status filters.
export function criterionOutcomes(criteria: Criterion[], impacts: Impact[], programs: Program[]) {
  const activePrograms = new Set(programs.filter(p => p.review.status !== 'rejected').map(p => p.id));
  const eligible = criteria.filter(c => c.review.status !== 'rejected' && activePrograms.has(c.program_id));
  const reviewedPrograms = new Set(programs.filter(p => p.review.status === 'reviewed').map(p => p.id));
  const reviewed = eligible.filter(c => c.review.status === 'reviewed' && reviewedPrograms.has(c.program_id));
  const accepted = new Map(impacts.filter(publicImpact).map(i => [i.id, i]));
  const automatic = eligible.filter(c => c.assessment.method === 'agent' &&
    c.assessment.generation?.model === 'openai/gpt-6-sol' && c.assessment.evidence_ids.length > 0 &&
    c.assessment.evidence_ids.every(id => accepted.get(id)?.criterion_id === c.id));
  const evidence = new Set([...accepted.values()].filter(i => i.evaluation?.status === 'accepted' ||
    reviewed.some(c => c.id === i.criterion_id)).map(i => i.criterion_id));
  return eligible.map(criterion => ({
    criterion,
    status: automatic.includes(criterion) || reviewed.includes(criterion) ? criterion.assessment.status : 'unassessed' as const,
    covered: evidence.has(criterion.id),
    reviewed: reviewed.includes(criterion),
    automatic: automatic.includes(criterion),
  }));
}

export function metrics(criteria: Criterion[], impacts: Impact[], programs: Program[]) {
  const outcomes = criterionOutcomes(criteria, impacts, programs);
  const total = outcomes.length;
  const fulfilled = outcomes.filter(c => c.status === 'fulfilled').length;
  const partial = outcomes.filter(c => c.status === 'partial').length;
  const contradicted = outcomes.filter(c => c.status === 'contradicted').length;
  const mixed = outcomes.filter(c => c.status === 'mixed').length;
  const covered = outcomes.filter(c => c.covered).length;
  const scores = outcomes.filter(c => c.automatic && c.criterion.assessment.score != null).map(c => c.criterion.assessment.score!);
  return {
    total, reviewed: outcomes.filter(c => c.reviewed).length, fulfilled, partial, contradicted, mixed,
    unknown: total - fulfilled - partial - contradicted - mixed, covered,
    automated: outcomes.filter(c => c.automatic).length, scored: scores.length,
    alignment: scores.length ? Math.round(scores.reduce<number>((a, b) => a + b, 0) / scores.length * 100) / 100 : null,
    coverage: total ? Math.round(covered / total * 100) : null,
    fulfilment: total ? Math.round(fulfilled / total * 100) : null,
  };
}

// Machine processing coverage is not semantic completeness or human review.
export function extractionCoverage(program: Program, criteria: Criterion[]) {
  const source = new Set(program.leaves.map(leaf => leaf.id));
  const processed = new Set([
    ...(program.criteria_extraction ?? []).map(audit => audit.leaf_id),
    ...criteria.filter(c => c.program_id === program.id).map(c => c.leaf_id),
  ].filter(id => source.has(id)));
  return { source_leaves: source.size, processed_leaves: processed.size,
    remaining_leaves: source.size - processed.size, complete: source.size > 0 && source.size === processed.size };
}

export function voteTotals(groups: { yes: number | null; no: number | null; abstain: number | null; absent: number | null; invalid?: number | null }[]) {
  if (!groups.length || groups.some(g => [g.yes, g.no, g.abstain, g.absent].some(n => n == null))) return null;
  const totals = groups.reduce<Record<Ballot, number>>((acc, g) => ({
    yes: acc.yes + g.yes!, no: acc.no + g.no!, abstain: acc.abstain + g.abstain!, absent: acc.absent + g.absent!,
    invalid: acc.invalid + (g.invalid ?? 0),
  }), { yes: 0, no: 0, abstain: 0, absent: 0, invalid: 0 });
  const cast = totals.yes + totals.no + totals.abstain + totals.invalid;
  return { ...totals, cast, total: cast + totals.absent };
}
