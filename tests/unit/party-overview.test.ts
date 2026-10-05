import { describe, expect, it } from 'vitest';
import parties from '../../data/parties.json';
import { overviewParties } from '../../src/lib/data';

const live = { dataset: 'live' as const, parties };

describe('election-scoped party overview', () => {
  it('shows the 2025 Bundestag parties, including opposition and SSW, without depending on programme imports', () => {
    expect(overviewParties(live, 2025).map(party => party.id)).toEqual([
      'cdu-csu', 'spd', 'gruene', 'afd', 'linke', 'ssw',
    ]);
  });

  it('does not delete FDP or BSW from the party registry', () => {
    const before = structuredClone(parties);
    overviewParties(live, 2025);
    expect(parties).toEqual(before);
    expect(parties.map(party => party.id)).toEqual(expect.arrayContaining(['fdp', 'bsw']));
  });

  it('does not apply the current Bundestag scope to earlier election years', () => {
    expect(overviewParties(live, 2021)).toBe(parties);
  });

  it('does not apply real election results to fictional test fixtures', () => {
    expect(overviewParties({ dataset: 'demo', parties }, 2025)).toBe(parties);
  });
});
