import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import type { Consultation, PendingQuestion } from '../../core/models';
import { ProblemNotice } from '../../shared/problem-notice';
import { SessionStore } from '../store';

/** Region 3: open questions in the engine's order, with what each answer affects. */
@Component({
  selector: 'app-questions-region',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoPipe, ProblemNotice],
  template: `
    <section class="card" aria-labelledby="q-title">
      <h2 id="q-title">{{ 'questions.title' | transloco }}</h2>
      <app-problem-notice [problem]="store.problems()['questions'] ?? null" />

      @if (questions().length === 0) {
        <p class="hint">{{ 'questions.none' | transloco }}</p>
      }
      @for (q of questions(); track q.attribute) {
        <form
          class="question"
          [attr.data-question]="q.attribute"
          (submit)="$event.preventDefault(); applyMulti(q)"
        >
          <fieldset [disabled]="readOnly() || busy()">
            <legend>{{ q.question }}</legend>
            <p class="affects">
              <span class="hint">{{ 'questions.affects' | transloco }}</span>
              {{ affects(q) }}
            </p>
            <div class="options">
              @for (v of q.values; track v) {
                <label class="opt">
                  <input
                    [type]="q.multi ? 'checkbox' : 'radio'"
                    [name]="'q-' + q.attribute"
                    [value]="v"
                    [checked]="selected(q).includes(v)"
                    (change)="q.multi ? toggle(q, v) : answer(q, v)"
                  />
                  <span class="mono">{{ v }}</span>
                </label>
              }
              @if (!q.multi) {
                <label class="opt">
                  <input
                    type="radio"
                    [name]="'q-' + q.attribute"
                    value="unknown"
                    (change)="answer(q, 'unknown')"
                  />
                  <span>{{ 'questions.dont_know' | transloco }}</span>
                </label>
              }
            </div>
            @if (q.multi) {
              <div class="actions">
                <button
                  type="submit"
                  class="btn btn-primary btn-sm"
                  [disabled]="!selected(q).length"
                >
                  {{ 'questions.answer' | transloco }}
                </button>
                <button type="button" class="btn btn-ghost btn-sm" (click)="answer(q, 'unknown')">
                  {{ 'questions.dont_know' | transloco }}
                </button>
              </div>
            }
          </fieldset>
        </form>
      }
    </section>
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
    .question {
      padding-top: var(--space-3);
      border-top: 1px solid var(--border);
    }
    fieldset {
      border: 0;
      margin: 0;
      padding: 0;
      min-width: 0;
    }
    legend {
      font-weight: 600;
      padding: 0;
    }
    .affects {
      margin: var(--space-1) 0 var(--space-2);
    }
    .options {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2) var(--space-4);
    }
    .opt {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      min-height: 36px;
    }
    @media (pointer: coarse) {
      .opt {
        min-height: 44px;
      }
    }
    .actions {
      display: flex;
      gap: var(--space-2);
      margin-top: var(--space-2);
    }
  `,
})
export class QuestionsRegion {
  protected readonly store = inject(SessionStore);
  readonly view = input.required<Consultation>();
  readonly readOnly = input(false);

  private readonly picked = signal<Record<string, string[]>>({});
  protected readonly busy = computed(() => !!this.store.busy()['questions']);
  protected readonly questions = computed(
    () => this.view().evaluation?.result.pending_questions ?? [],
  );

  protected selected(q: PendingQuestion): string[] {
    return this.picked()[q.attribute] ?? [];
  }

  protected affects(q: PendingQuestion): string {
    const names = new Map(this.view().catalog.abbs.map((a) => [a.id, a.name]));
    return q.impact.map((id) => names.get(id) ?? id).join(', ');
  }

  protected toggle(q: PendingQuestion, value: string): void {
    this.picked.update((all) => {
      const now = all[q.attribute] ?? [];
      return {
        ...all,
        [q.attribute]: now.includes(value) ? now.filter((v) => v !== value) : [...now, value],
      };
    });
  }

  protected applyMulti(q: PendingQuestion): void {
    const values = this.selected(q);
    if (values.length) {
      void this.answerAndRefocus(q, values.length === 1 ? values[0] : values);
    }
  }

  protected answer(q: PendingQuestion, value: string): Promise<void> {
    return this.answerAndRefocus(q, value);
  }

  /** The answered question leaves this list; focus moves to the next question so keyboard
   * users keep their place and nothing is announced by moving focus elsewhere. */
  private async answerAndRefocus(q: PendingQuestion, value: string | string[]): Promise<void> {
    const order = this.questions().map((x) => x.attribute);
    const index = order.indexOf(q.attribute);
    await this.store.answer(q.attribute, value);
    if (this.store.problems()['questions']) {
      return;
    }
    // wait for the list to re-render before moving focus
    setTimeout(() => {
      const next = document.querySelectorAll<HTMLElement>('[data-question] input');
      const remaining = this.questions().map((x) => x.attribute);
      const target = remaining[Math.min(index, remaining.length - 1)] ?? null;
      const el = target
        ? document.querySelector<HTMLElement>(`[data-question="${target}"] input`)
        : null;
      (el ?? next[0])?.focus();
    }, 50);
  }
}
