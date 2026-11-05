import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import en from '../../public/i18n/en.json';

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

function has(key: string): boolean {
  let node: unknown = en;
  for (const part of key.split('.')) {
    if (typeof node !== 'object' || node === null || !(part in node)) {
      return false;
    }
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === 'string' || typeof node === 'object';
}

describe('translations', () => {
  const sources = files(join(__dirname)).filter(
    (f) => f.endsWith('.ts') && !f.endsWith('.spec.ts'),
  );

  it('has every literal key used with the transloco pipe', () => {
    const missing: string[] = [];
    for (const file of sources) {
      const text = readFileSync(file, 'utf-8');
      for (const m of text.matchAll(/'([a-z_]+(?:\.[a-z_]+)+)'\s*\|\s*transloco/g)) {
        if (!has(m[1])) {
          missing.push(`${file}: ${m[1]}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });

  it('has every key built from a prefix', () => {
    const prefixes: Record<string, string[]> = {
      coverage: ['covered', 'conditional', 'blocked', 'gap'],
      status: ['draft', 'proposed', 'validated'],
      sbb_state: ['recommended', 'accepted', 'deprecating', 'prohibited'],
      sbb_result: ['eligible', 'conditional', 'excluded'],
      source: ['stated', 'inferred', 'answered', 'edited', 'unknown'],
      stage: ['interpreting', 'checking', 'evaluating'],
      abbs: [
        'group_required',
        'group_consider',
        'group_identified',
        'group_potential',
        'strength_requires',
        'strength_considers',
        'activation_identified',
        'activation_confirmed',
        'activation_potential',
        'exclusion_prohibited',
        'exclusion_not_applies_when',
        'exclusion_applies_when_not_met',
      ],
      summary: [
        'required',
        'consider',
        'identified',
        'covered',
        'conditional',
        'blocked',
        'gaps',
        'potential',
        'questions',
      ],
      feedback: ['missing', 'wrong'],
      'live.questions': ['one', 'other'],
      'live.gaps': ['one', 'other'],
      kind: [
        'abb',
        'sbb',
        'rule',
        'attribute',
        'characteristic',
        'lens',
        'abbs',
        'sbbs',
        'rules',
        'attributes',
        'characteristics',
        'lenses',
      ],
      queue_kind: [
        'gap',
        'unrecognised',
        'feedback',
        'draft_review',
        'validation_backlog',
        'validator_finding',
      ],
      impact: ['label_added', 'label_removed', 'label_changed', 'label_question'],
      item: [
        'origin_manual',
        'origin_interview',
        'origin_import',
        'origin_discussion',
        'origin_feedback',
        'origin_restore',
      ],
      try: ['true', 'false', 'indeterminate'],
      interview: [
        'kind_sbb',
        'kind_rule',
        'kind_abb',
        'kind_attribute_value',
        'state_pending',
        'state_accepted',
        'state_rejected',
        'state_depends',
        'status_open',
        'status_closed',
      ],
      discussions: [
        ...['attention', 'mine', 'open', 'closed', 'orphaned'].flatMap((t) => [
          `tab_${t}`,
          `empty_${t}`,
        ]),
        ...['open', 'accepted', 'rejected', 'withdrawn'].map((t) => `status_${t}`),
        ...['accepted', 'accepted_modified', 'rejected', 'withdrawn'].flatMap((t) => [
          `outcome_${t}`,
          `consequence_${t}`,
        ]),
        ...['support', 'support_with_conditions', 'oppose', 'abstain'].map((t) => `stance_${t}`),
        ...['comment', 'position', 'mediator', 'system'].map((t) => `kind_${t}`),
        ...['fact', 'question', 'counterargument', 'suggestion', 'agreement', 'disagreement'].map(
          (t) => `sk_${t}`,
        ),
        'err_rationale',
        'err_responses',
        'proposal_error_not_object',
        'proposal_error_not_json',
      ],
      notifications: [
        'kind_discussion_opened',
        'kind_discussion_activity',
        'kind_mention',
        'kind_decider_nudge',
        'kind_claim_expiring',
        'kind_discussion_reassigned',
      ],
      edit: ['reason_not_applies', 'reason_prohibited', 'when_to_choose', 'limitations'],
    };
    const missing = Object.entries(prefixes).flatMap(([prefix, names]) =>
      names.filter((n) => !has(`${prefix}.${n}`)).map((n) => `${prefix}.${n}`),
    );
    expect(missing).toEqual([]);
  });

  it('has a message for every error code the API can return', () => {
    const codes = [
      'not_found',
      'empty_catalog',
      'catalog_invalid',
      'invalid_input',
      'nothing_to_explain',
      'forbidden',
      'llm_unavailable',
      'llm_output_rejected',
      'llm_error',
      'llm_not_configured',
      'invalid_credentials',
      'rate_limited',
      'invalid_invitation',
      'weak_password',
      'network',
      'stale',
      'unknown_reference',
      'conflict',
      'constraint',
      'invalid_document',
      'validation_errors',
      'already_open',
      'missing_responses',
      'invalid',
    ];
    expect(codes.filter((c) => !has(`errors.${c}`))).toEqual([]);
  });
});
