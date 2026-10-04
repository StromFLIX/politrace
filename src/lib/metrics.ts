import type { Criterion, Impact, Program } from './types';

export function metrics(criteria: Criterion[], impacts: Impact[], programs: Program[]) {
  const eligible = criteria.filter(c => c.review.status !== 'rejected');
  const reviewedPrograms = new Set(programs.filter(p => p.review.status === 'reviewed').map(p => p.id));
  const reviewed = eligible.filter(c => c.review.status === 'reviewed' && reviewedPrograms.has(c.program_id));
  const evidence = new Set(impacts.filter(i => i.review.status === 'reviewed').map(i => i.criterion_id));
  const fulfilled = reviewed.filter(c => c.assessment.status === 'fulfilled').length;
  const partial = reviewed.filter(c => c.assessment.status === 'partial').length;
  const contradicted = reviewed.filter(c => c.assessment.status === 'contradicted').length;
  const covered = reviewed.filter(c => evidence.has(c.id)).length;
  return {
    total: eligible.length, reviewed: reviewed.length, fulfilled, partial, contradicted,
    unknown: eligible.length - fulfilled - partial - contradicted, covered,
    coverage: eligible.length ? Math.round(covered / eligible.length * 100) : null,
    fulfilment: eligible.length ? Math.round(fulfilled / eligible.length * 100) : null,
  };
}

export function voteTotals(groups: { yes: number; no: number; abstain: number; absent: number }[]) {
  const totals = groups.reduce((acc, g) => ({
    yes: acc.yes + g.yes, no: acc.no + g.no, abstain: acc.abstain + g.abstain, absent: acc.absent + g.absent,
  }), { yes: 0, no: 0, abstain: 0, absent: 0 });
  return { ...totals, cast: totals.yes + totals.no + totals.abstain, total: totals.yes + totals.no + totals.abstain + totals.absent };
}
