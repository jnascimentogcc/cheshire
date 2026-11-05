import type { AbbResult, EngineResult, SbbOutcome, TraceTest } from '../core/models';
import {
  highlightSegments,
  comparable,
  comparisonTable,
  groupAbbs,
  groupOf,
  missingAnswers,
  openQuestionsFor,
  ruleValidation,
  sbbsByResult,
  summarize,
} from './logic';

function sbb(id: string, result: SbbOutcome['result'], tests: TraceTest[] = []): SbbOutcome {
  return {
    id,
    name: id.toUpperCase(),
    state: 'accepted',
    status: 'validated',
    result,
    exclusion: null,
    reason: '',
    notes: [],
    tests,
  };
}

function abb(id: string, over: Partial<AbbResult> = {}): AbbResult {
  return {
    id,
    activation: 'confirmed',
    strength: 'requires',
    validation: 'validated',
    origin: [],
    coverage: 'covered',
    sbbs: [],
    ...over,
  };
}

const unknownTest: TraceTest = {
  test: 'volume in [high]',
  result: null,
  attribute: 'volume',
  value: null,
  source: null,
  children: [],
};

const result: EngineResult = {
  abbs: [
    abb('a-required'),
    abb('b-consider', { strength: 'considers' }),
    abb('c-identified', { activation: 'identified', strength: null, coverage: 'gap' }),
    abb('d-potential', { activation: 'potential', coverage: 'conditional' }),
    abb('e-blocked', {
      coverage: 'blocked',
      origin: [
        {
          rule: 'R-1',
          result: true,
          strength: 'requires',
          status: 'proposed',
          reason: '',
          tests: [],
        },
        {
          rule: 'R-2',
          result: true,
          strength: 'requires',
          status: 'validated',
          reason: '',
          tests: [],
        },
      ],
    }),
  ],
  pending_questions: [
    {
      attribute: 'volume',
      question: 'How many?',
      values: ['low', 'high'],
      multi: false,
      impact: ['d-potential'],
    },
  ],
};

describe('consult logic', () => {
  it('groups ABBs the way the page shows them', () => {
    expect(result.abbs.map(groupOf)).toEqual([
      'required',
      'consider',
      'identified',
      'potential',
      'required',
    ]);
    expect(groupAbbs(result).map((g) => g.group)).toEqual([
      'required',
      'consider',
      'identified',
      'potential',
    ]);
  });

  it('drops empty groups', () => {
    expect(groupAbbs({ abbs: [abb('x')], pending_questions: [] }).map((g) => g.group)).toEqual([
      'required',
    ]);
  });

  it('counts coverage and questions', () => {
    expect(summarize(result)).toEqual({
      required: 2,
      consider: 1,
      identified: 1,
      potential: 1,
      covered: 2,
      conditional: 1,
      blocked: 1,
      gaps: 1,
      questions: 1,
    });
  });

  it('says how many rules are not validated, never hiding them', () => {
    expect(ruleValidation(result)).toEqual({ total: 2, notValidated: 1 });
  });

  it('keeps SBBs alphabetical whatever order they arrive in', () => {
    const a = abb('x', {
      sbbs: [sbb('zeta', 'eligible'), sbb('alpha', 'eligible'), sbb('mid', 'excluded')],
    });
    expect(sbbsByResult(a, 'eligible').map((s) => s.id)).toEqual(['alpha', 'zeta']);
  });

  it('finds the questions behind an ABB and behind a conditional SBB', () => {
    expect(openQuestionsFor(result, 'd-potential').map((q) => q.attribute)).toEqual(['volume']);
    expect(openQuestionsFor(result, 'a-required')).toEqual([]);
    const nested: TraceTest = {
      ...unknownTest,
      test: 'all',
      attribute: null,
      children: [unknownTest],
    };
    expect(missingAnswers(sbb('s', 'conditional', [nested, unknownTest]))).toEqual(['volume']);
  });

  it('compares only ABBs with two or more candidates, columns alphabetical', () => {
    const many = abb('many', {
      sbbs: [sbb('b', 'eligible'), sbb('a', 'conditional'), sbb('c', 'excluded')],
    });
    const one = abb('one', { sbbs: [sbb('a', 'eligible')] });
    expect(comparable({ abbs: [many, one], pending_questions: [] }).map((x) => x.id)).toEqual([
      'many',
    ]);
    const table = comparisonTable(many, [
      {
        id: 'a',
        realises: 'many',
        name: 'A',
        when_to_choose: '',
        limitations: '',
        owner: '',
        characteristics: { speed: 'fast', cost: 'low' },
      },
      {
        id: 'b',
        realises: 'many',
        name: 'B',
        when_to_choose: '',
        limitations: '',
        owner: '',
        characteristics: { speed: 'slow' },
      },
    ]);
    expect(table.columns.map((c) => c.id)).toEqual(['a', 'b']);
    expect(table.characteristics).toEqual(['cost', 'speed']);
  });

  it('marks spans in the text with chip numbers, joining parts split by "..."', () => {
    const text = 'When an order is shipped, notify by e-mail and SMS.';
    const segments = highlightSegments(text, [
      { index: 1, kind: 'abb', id: 'sms', text: 'SMS' },
      { index: 2, kind: 'attribute', id: 'mode', text: 'When an order ... shipped' },
    ]);
    expect(segments.map((s) => s.text).join('')).toBe(text);
    const marked = segments.filter((s) => s.chips.length > 0).map((s) => [s.text, s.chips]);
    expect(marked).toEqual([
      ['When an order', [2]],
      ['shipped', [2]],
      ['SMS', [1]],
    ]);
  });

  it('ignores spans that are not in the text', () => {
    const segments = highlightSegments('abc', [{ index: 1, kind: 'abb', id: 'x', text: 'zzz' }]);
    expect(segments).toEqual([{ text: 'abc', chips: [] }]);
  });
});
