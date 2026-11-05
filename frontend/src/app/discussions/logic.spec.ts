import {
  catalogRefs,
  latestSynthesis,
  newEntries,
  opposing,
  parseProposal,
  prefill,
  unanswered,
} from './logic';
import type { Discussion, Entry, Position } from './models';

function position(id: number, participant: string, stance: Position['stance']): Position {
  return {
    id,
    participant_id: id,
    participant,
    stance,
    reason: '',
    created_at: '',
    revisions: 0,
  };
}

function entry(id: number, over: Partial<Entry> = {}): Entry {
  return {
    id,
    seq: id,
    kind: 'comment',
    author_id: 1,
    author: 'a',
    body: '',
    grounding: null,
    ai: false,
    created_at: '',
    edited_at: null,
    retracted_at: null,
    edits: 0,
    ...over,
  };
}

const positions = [
  position(1, 'bea', 'oppose'),
  position(2, 'cai', 'support'),
  position(3, 'dan', 'oppose'),
];

describe('opposing positions', () => {
  it('are the ones that need an answer', () => {
    expect(opposing(positions).map((p) => p.participant)).toEqual(['bea', 'dan']);
  });

  it('lists who has no complete answer yet', () => {
    expect(unanswered(positions, {})).toEqual(['bea', 'dan']);
    expect(
      unanswered(positions, {
        1: { accepted: false, response: 'Covered.' },
        3: { accepted: null, response: 'Text but no verdict' },
      }),
    ).toEqual(['dan']);
    expect(
      unanswered(positions, {
        1: { accepted: false, response: 'Covered.' },
        3: { accepted: true, response: 'Fair.' },
      }),
    ).toEqual([]);
  });
});

describe('the mediator synthesis', () => {
  const synthesis = entry(5, {
    kind: 'mediator',
    grounding: {
      mode: 'synthesis',
      responses: [
        { position_id: 1, accepted: true, response: 'Agreed.' },
        { position_id: 2, accepted: true, response: 'Not an objection.' },
      ],
    },
  });

  it('pre-fills only live opposing positions', () => {
    expect(prefill([entry(1), synthesis], positions)).toEqual({
      1: { accepted: true, response: 'Agreed.' },
    });
    expect(prefill([entry(1)], positions)).toEqual({});
  });

  it('finds the latest one', () => {
    expect(latestSynthesis([entry(1), synthesis, entry(6)])?.id).toBe(5);
    expect(latestSynthesis([entry(1)])).toBeNull();
  });
});

describe('new activity', () => {
  it('counts entries that were not in the previous view', () => {
    const view = (ids: number[]) => ({ thread: ids.map((i) => entry(i)) }) as Discussion;
    expect(newEntries(null, view([1, 2]))).toBe(0);
    expect(newEntries(view([1, 2]), view([1, 2, 3, 4]))).toBe(2);
  });
});

describe('catalog references in text', () => {
  it('turns kind:slug into links and keeps the rest', () => {
    expect(catalogRefs('See sbb:acme-sms and rule:R-001.')).toEqual([
      { text: 'See ', link: null },
      { text: 'sbb:acme-sms', link: ['/catalog', 'sbbs', 'acme-sms'] },
      { text: ' and ', link: null },
      { text: 'rule:R-001', link: ['/catalog', 'rules', 'R-001'] },
      { text: '.', link: null },
    ]);
    expect(catalogRefs('nothing here')).toEqual([{ text: 'nothing here', link: null }]);
  });
});

describe('proposal text', () => {
  it('accepts a JSON object only', () => {
    expect(parseProposal('{"id": "x"}').item).toEqual({ id: 'x' });
    expect(parseProposal('[1]').error).toBe('not_object');
    expect(parseProposal('{oops').error).toBe('not_json');
  });
});
