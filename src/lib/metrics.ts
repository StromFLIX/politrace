import type { Criterion, Impact, Program } from './types';

export function publicImpact(impact: Impact) {
  return impact.review.status !== 'rejected' && (impact.review.status === 'reviewed' ||
    (impact.evaluation?.status === 'accepted' && impact.evaluation.model === 'openai/gpt-6-sol'));
}

export function metrics(criteria: Criterion[], impacts: Impact[], programs: Program[]) {
  const activePrograms = new Set(programs.filter(p => p.review.status !== 'rejected').map(p => p.id));
  const eligible = criteria.filter(c => c.review.status !== 'rejected' && activePrograms.has(c.program_id));
  const reviewedPrograms = new Set(programs.filter(p => p.review.status === 'reviewed').map(p => p.id));
  const reviewed = eligible.filter(c => c.review.status === 'reviewed' && reviewedPrograms.has(c.program_id));
  const accepted = new Map(impacts.filter(publicImpact).map(i => [i.id, i]));
  const automatic = eligible.filter(c => c.assessment.method === 'agent' &&
    c.assessment.generation?.model === 'openai/gpt-6-sol' && c.assessment.evidence_ids.length > 0 &&
    c.assessment.evidence_ids.every(id => accepted.get(id)?.criterion_id === c.id));
  const assessed = eligible.filter(c => automatic.includes(c) || reviewed.includes(c));
  const fulfilled = assessed.filter(c => c.assessment.status === 'fulfilled').length;
  const partial = assessed.filter(c => c.assessment.status === 'partial').length;
  const contradicted = assessed.filter(c => c.assessment.status === 'contradicted').length;
  const mixed = assessed.filter(c => c.assessment.status === 'mixed').length;
  const evidence = new Set([...accepted.values()].filter(i => i.evaluation?.status === 'accepted' ||
    reviewed.some(c => c.id === i.criterion_id)).map(i => i.criterion_id));
  const covered = eligible.filter(c => evidence.has(c.id)).length;
  const scores = automatic.filter(c => c.assessment.score != null).map(c => c.assessment.score!);
  return {
    total: eligible.length, reviewed: reviewed.length, fulfilled, partial, contradicted, mixed,
    unknown: eligible.length - fulfilled - partial - contradicted - mixed, covered,
    automated: automatic.length, scored: scores.length,
    alignment: scores.length ? Math.round(scores.reduce<number>((a, b) => a + b, 0) / scores.length * 100) / 100 : null,
    coverage: eligible.length ? Math.round(covered / eligible.length * 100) : null,
    fulfilment: eligible.length ? Math.round(fulfilled / eligible.length * 100) : null,
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

export function voteTotals(groups: { yes: number; no: number; abstain: number; absent: number }[]) {
  const totals = groups.reduce((acc, g) => ({
    yes: acc.yes + g.yes, no: acc.no + g.no, abstain: acc.abstain + g.abstain, absent: acc.absent + g.absent,
  }), { yes: 0, no: 0, abstain: 0, absent: 0 });
  return { ...totals, cast: totals.yes + totals.no + totals.abstain, total: totals.yes + totals.no + totals.abstain + totals.absent };
}
