import type { SbbOutcome } from '../../core/models';
import { reasonRequired } from './choices';

function sbb(result: SbbOutcome['result'], state: SbbOutcome['state']): SbbOutcome {
  return {
    id: 's',
    name: 'S',
    state,
    status: 'validated',
    result,
    exclusion: null,
    reason: '',
    notes: [],
    tests: [],
  };
}

describe('reasonRequired', () => {
  it('is required for a conditional or a deprecating solution (consult.md 9.2)', () => {
    expect(reasonRequired(sbb('conditional', 'accepted'))).toBe(true);
    expect(reasonRequired(sbb('eligible', 'deprecating'))).toBe(true);
  });

  it('is optional otherwise, and when nothing is chosen', () => {
    expect(reasonRequired(sbb('eligible', 'recommended'))).toBe(false);
    expect(reasonRequired(sbb('eligible', 'accepted'))).toBe(false);
    expect(reasonRequired(undefined)).toBe(false);
  });
});
