import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import type { Consultation } from '../../core/models';
import { ruleValidation, summarize } from '../logic';

/** Region 4: counts, and how much of what the result rests on is not yet validated. */
@Component({
  selector: 'app-summary-region',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoPipe],
  template: `
    @if (summary(); as s) {
      <section class="card" aria-labelledby="sum-title">
        <h2 id="sum-title">{{ 'summary.title' | transloco }}</h2>
        <dl class="counts">
          @for (item of items(); track item.key) {
            <div>
              <dt>{{ 'summary.' + item.key | transloco }}</dt>
              <dd class="mono">{{ item.value }}</dd>
            </div>
          }
        </dl>
        @if (validation(); as v) {
          @if (v.total > 0) {
            <p [class]="v.notValidated ? 'notice notice-warning' : 'hint'">
              {{ 'summary.rules_not_validated' | transloco: { n: v.notValidated, total: v.total } }}
            </p>
          }
        }
      </section>
    }
  `,
  styles: `
    section {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    h2 {
      margin: 0;
    }
    .counts {
      margin: 0;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: var(--space-3);
    }
    .counts div {
      padding: var(--space-2) var(--space-3);
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: var(--radius);
    }
    dt {
      color: var(--text-2);
    }
    dd {
      margin: 0;
      font-size: 1.4rem;
      font-weight: 500;
    }
    p {
      margin: 0;
    }
  `,
})
export class SummaryRegion {
  readonly view = input.required<Consultation>();

  protected readonly summary = computed(() => {
    const evaluation = this.view().evaluation;
    return evaluation ? summarize(evaluation.result) : null;
  });
  protected readonly validation = computed(() => {
    const evaluation = this.view().evaluation;
    return evaluation ? ruleValidation(evaluation.result) : null;
  });
  protected readonly items = computed(() => {
    const s = this.summary();
    if (!s) {
      return [];
    }
    return [
      { key: 'required', value: s.required },
      { key: 'consider', value: s.consider },
      { key: 'identified', value: s.identified },
      { key: 'covered', value: s.covered },
      { key: 'conditional', value: s.conditional },
      { key: 'blocked', value: s.blocked },
      { key: 'gaps', value: s.gaps },
      { key: 'potential', value: s.potential },
      { key: 'questions', value: s.questions },
    ];
  });
}
