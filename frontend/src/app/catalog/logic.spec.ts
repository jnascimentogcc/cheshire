import {
  conditionProblems,
  fromRows,
  openTarget,
  referencedIn,
  toRows,
  validSlug,
  workTarget,
} from './logic';
import type { RawCondition, Vocabulary, WorkItem } from './models';

const vocab: Vocabulary = {
  attributes: [
    { id: 'volume', values: ['low', 'high'] },
    { id: 'personal_data', values: ['none', 'sensitive'] },
  ],
  abbs: [{ id: 'channel-sms', name: 'SMS' }],
  characteristics: [],
};

describe('condition rows', () => {
  const raw: RawCondition = {
    volume: ['high'],
    abb_present: ['channel-sms'],
    except: { personal_data: ['sensitive'] },
  };

  it('round-trips the open format', () => {
    expect(fromRows(toRows(raw))).toEqual(raw);
  });

  it('drops tests that are not filled in and keeps an empty condition empty', () => {
    expect(
      fromRows({
        tests: [
          { attribute: '', values: [] },
          { attribute: 'volume', values: [] },
        ],
        abbs: [],
        except: { tests: [], abbs: [], except: null },
      }),
    ).toEqual({});
    expect(fromRows(toRows(undefined))).toEqual({});
  });

  it('lists what a condition reads, including the exception', () => {
    expect(referencedIn(toRows(raw))).toEqual({
      attributes: ['personal_data', 'volume'],
      abbs: ['channel-sms'],
    });
  });

  it('names what is wrong before the server does', () => {
    expect(conditionProblems(toRows(raw), vocab)).toEqual([]);
    const bad = toRows({ volume: ['huge'], nope: ['x'], abb_present: ['ghost'] });
    expect(conditionProblems(bad, vocab)).toEqual([
      'volume has no value huge',
      'unknown attribute nope',
      'unknown ABB ghost',
    ]);
  });
});

describe('workTarget', () => {
  const base: WorkItem = {
    id: 1,
    kind: 'gap',
    status: 'open',
    payload: {},
    subject: 'channel-sms',
    subject_kind: 'abb',
    sessions: 1,
    first_consultation_id: 7,
    claimed_by: null,
    claimed_by_me: false,
    claim_expires_at: null,
    expiring_soon: false,
    resolution: '',
    created_at: '',
  };

  it('opens a new solution for a gap, pre-filled with its building block', () => {
    expect(workTarget(base)).toEqual({
      link: ['/catalog', 'sbbs', 'new'],
      query: { realises: 'channel-sms' },
    });
  });

  it('shows the building block of a gap on Open, not the new-solution form', () => {
    expect(openTarget(base)).toEqual({ link: ['/catalog', 'abbs', 'channel-sms'] });
    expect(openTarget({ ...base, kind: 'unrecognised' })?.link).toEqual(['/consult', '7']);
    expect(openTarget({ ...base, subject: null })).toBeNull();
  });

  it('opens the consultation for an unrecognised requirement and the item for a draft', () => {
    expect(workTarget({ ...base, kind: 'unrecognised' })?.link).toEqual(['/consult', '7']);
    expect(
      workTarget({
        ...base,
        kind: 'draft_review',
        payload: { item_kind: 'sbb', item: 'sms-provider-a' },
      })?.link,
    ).toEqual(['/catalog', 'sbbs', 'sms-provider-a']);
    expect(workTarget({ ...base, kind: 'validator_finding' })).toBeNull();
  });
});

describe('validSlug', () => {
  it('matches the slug rule of the catalog', () => {
    expect(validSlug('sms-provider.a_1')).toBe(true);
    expect(validSlug('-bad')).toBe(false);
    expect(validSlug('has space')).toBe(false);
    expect(validSlug('')).toBe(false);
  });
});
