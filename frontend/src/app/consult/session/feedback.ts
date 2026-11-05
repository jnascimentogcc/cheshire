import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';

import type { Consultation } from '../../core/models';
import { UserPreferences } from '../../core/preferences';
import { ProblemNotice } from '../../shared/problem-notice';
import { SessionStore } from '../store';

/** Region 9: "something is missing / wrong", on one ABB or on the whole result. */
@Component({
  selector: 'app-feedback-region',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, DatePipe, TranslocoPipe, ProblemNotice],
  template: `
    <section class="card" aria-labelledby="fb-title">
      <h2 id="fb-title">{{ 'feedback.title' | transloco }}</h2>
      <p class="hint">{{ 'feedback.intro' | transloco }}</p>
      <app-problem-notice [problem]="store.problems()['feedback'] ?? null" />

      @if (!readOnly()) {
        <form (ngSubmit)="send()" novalidate>
          <fieldset>
            <legend>{{ 'feedback.kind' | transloco }}</legend>
            <label class="opt">
              <input type="radio" name="kind" value="missing" [(ngModel)]="kind" />
              {{ 'feedback.missing' | transloco }}
            </label>
            <label class="opt">
              <input type="radio" name="kind" value="wrong" [(ngModel)]="kind" />
              {{ 'feedback.wrong' | transloco }}
            </label>
          </fieldset>
          <div class="field">
            <label for="fb-target">{{ 'feedback.about' | transloco }}</label>
            <select id="fb-target" name="target" class="input" [(ngModel)]="target">
              <option value="">{{ 'feedback.whole_result' | transloco }}</option>
              @for (a of abbs(); track a.id) {
                <option [value]="a.id">{{ a.name }}</option>
              }
            </select>
          </div>
          <div class="field">
            <label for="fb-text">{{ 'feedback.text' | transloco }}</label>
            <textarea
              id="fb-text"
              name="text"
              class="input"
              rows="3"
              maxlength="4000"
              aria-describedby="fb-error"
              [attr.aria-invalid]="empty ? 'true' : null"
              [(ngModel)]="text"
              (ngModelChange)="empty = false"
            ></textarea>
            <span id="fb-error" class="error-text" role="alert">
              @if (empty) {
                {{ 'feedback.text_required' | transloco }}
              }
            </span>
          </div>
          <button type="submit" class="btn btn-secondary" [disabled]="busy()">
            {{ 'feedback.send' | transloco }}
          </button>
        </form>
      }

      @if (view().feedback.length) {
        <h3>{{ 'feedback.sent' | transloco }}</h3>
        <ul class="sent">
          @for (f of view().feedback; track f.id) {
            <li>
              <span class="badge">{{ 'feedback.' + f.kind | transloco }}</span>
              <span class="hint">
                {{ f.abb ? abbName(f.abb) : ('feedback.whole_result' | transloco) }} —
                {{ f.author }},
                {{ f.at | date: 'medium' : undefined : prefs.locale() }}
              </span>
              <p>{{ f.text }}</p>
            </li>
          }
        </ul>
        <p class="hint">{{ 'feedback.queue_note' | transloco }}</p>
      }
    </section>
  `,
  styles: `
    section,
    form {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    h2,
    h3 {
      margin: 0;
    }
    fieldset {
      border: 0;
      margin: 0;
      padding: 0;
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-4);
    }
    legend {
      font-weight: 500;
      padding: 0;
      margin-bottom: var(--space-1);
    }
    .opt {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      min-height: 32px;
    }
    form button {
      align-self: flex-start;
    }
    .sent {
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: var(--space-3);
    }
    .sent p {
      margin: var(--space-1) 0 0;
    }
    p {
      margin: 0;
    }
  `,
})
export class FeedbackRegion {
  protected readonly store = inject(SessionStore);
  protected readonly prefs = inject(UserPreferences);
  readonly view = input.required<Consultation>();
  readonly readOnly = input(false);

  protected kind: 'missing' | 'wrong' = 'missing';
  protected target = '';
  protected text = '';
  protected empty = false;

  protected readonly busy = computed(() => !!this.store.busy()['feedback']);
  protected readonly abbs = computed(() =>
    this.view().catalog.abbs.filter((a) =>
      this.view().evaluation?.result.abbs.some((r) => r.id === a.id),
    ),
  );

  protected abbName(id: string): string {
    return this.view().catalog.abbs.find((a) => a.id === id)?.name ?? id;
  }

  protected async send(): Promise<void> {
    if (!this.text.trim()) {
      this.empty = true;
      return;
    }
    await this.store.sendFeedback(this.kind, this.text, this.target || null);
    if (!this.store.problems()['feedback']) {
      this.text = '';
      this.target = '';
    }
  }
}
