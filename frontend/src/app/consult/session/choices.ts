import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';

import type { AbbResult, ChoiceRecord, Consultation, SbbOutcome } from '../../core/models';
import { UserPreferences } from '../../core/preferences';
import { ProblemNotice } from '../../shared/problem-notice';
import { missingAnswers, openQuestionsFor, sbbsByResult } from '../logic';
import { SessionStore } from '../store';

const LATER = '__later__';
const OUTSIDE = '__outside__';

/** True when a reason is mandatory: the chosen SBB is conditional or deprecating. */
export function reasonRequired(sbb: SbbOutcome | undefined): boolean {
  return !!sbb && (sbb.result === 'conditional' || sbb.state === 'deprecating');
}

/** Region 8: record the choice per ABB (eligible or conditional SBB, later, or outside). */
@Component({
  selector: 'app-choices-region',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, DatePipe, TranslocoPipe, ProblemNotice],
  template: `
    <section class="card" aria-labelledby="choice-title">
      <h2 id="choice-title">{{ 'choices.title' | transloco }}</h2>
      <p class="hint">{{ 'choices.intro' | transloco }}</p>
      <app-problem-notice [problem]="store.problems()['choices'] ?? null" />

      @for (abb of abbs(); track abb.id) {
        <form class="choice" (ngSubmit)="save(abb)" [attr.aria-labelledby]="'choice-' + abb.id">
          <fieldset [disabled]="readOnly() || busy()">
            <legend [id]="'choice-' + abb.id">{{ name(abb.id) }}</legend>

            @if (current(abb.id); as c) {
              <p class="current" role="status">
                <strong>{{ 'choices.current' | transloco }}</strong>
                @switch (c.kind) {
                  @case ('chosen') {
                    {{ sbbName(c.sbb) }}
                  }
                  @case ('decide_later') {
                    {{ 'choices.decide_later' | transloco }}
                  }
                  @default {
                    {{ 'choices.outside' | transloco }}
                  }
                }
                <span class="hint">
                  — {{ c.actor }}, {{ c.at | date: 'medium' : undefined : prefs.locale() }}
                </span>
                @if (c.reason) {
                  <br /><span class="hint">{{ 'choices.reason' | transloco }}:</span> {{ c.reason }}
                }
              </p>
            }

            <div class="options">
              @for (s of options(abb); track s.id) {
                <label class="opt">
                  <input
                    type="radio"
                    [name]="'pick-' + abb.id"
                    [checked]="pick(abb.id) === s.id"
                    (change)="setPick(abb.id, s.id)"
                  />
                  <span>
                    {{ s.name }}
                    <span class="hint">({{ 'sbb_result.' + s.result | transloco }})</span>
                  </span>
                </label>
              }
              <label class="opt">
                <input
                  type="radio"
                  [name]="'pick-' + abb.id"
                  [checked]="pick(abb.id) === later"
                  (change)="setPick(abb.id, later)"
                />
                <span>{{ 'choices.decide_later' | transloco }}</span>
              </label>
              @if (abb.coverage === 'gap') {
                <label class="opt">
                  <input
                    type="radio"
                    [name]="'pick-' + abb.id"
                    [checked]="pick(abb.id) === outside"
                    (change)="setPick(abb.id, outside)"
                  />
                  <span>{{ 'choices.outside' | transloco }}</span>
                </label>
              }
            </div>

            @if (selected(abb); as s) {
              @if (s.result === 'conditional') {
                <p class="notice notice-warning" role="note">
                  {{ 'choices.conditional_warning' | transloco }}
                  <span class="mono">{{ unresolved(abb, s).join(', ') }}</span>
                </p>
              }
            }

            <div class="field">
              <label [for]="'reason-' + abb.id">
                {{ 'choices.reason' | transloco }}
                <span class="hint">
                  {{ (needsReason(abb) ? 'common.required' : 'common.optional') | transloco }}
                </span>
              </label>
              <textarea
                [id]="'reason-' + abb.id"
                [name]="'reason-' + abb.id"
                class="input"
                rows="2"
                maxlength="4000"
                [attr.aria-invalid]="missingReason() === abb.id ? 'true' : null"
                [attr.aria-describedby]="'reason-error-' + abb.id"
                [ngModel]="reason(abb.id)"
                (ngModelChange)="setReason(abb.id, $event)"
              ></textarea>
              <span [id]="'reason-error-' + abb.id" class="error-text" role="alert">
                @if (missingReason() === abb.id) {
                  {{ 'choices.reason_required' | transloco }}
                }
              </span>
            </div>

            <button type="submit" class="btn btn-secondary btn-sm" [disabled]="!pick(abb.id)">
              {{ 'choices.save' | transloco }}
              <span class="sr-only">{{ name(abb.id) }}</span>
            </button>
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
    h2,
    p {
      margin: 0;
    }
    .choice {
      padding-top: var(--space-3);
      border-top: 1px solid var(--border);
    }
    fieldset {
      border: 0;
      margin: 0;
      padding: 0;
      min-width: 0;
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
    }
    legend {
      font-weight: 600;
      padding: 0;
      margin-bottom: var(--space-1);
    }
    .options {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
    }
    .opt {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      min-height: 32px;
    }
    .choice button {
      align-self: flex-start;
    }
  `,
})
export class ChoicesRegion {
  protected readonly store = inject(SessionStore);
  protected readonly prefs = inject(UserPreferences);
  readonly view = input.required<Consultation>();
  readonly readOnly = input(false);

  protected readonly later = LATER;
  protected readonly outside = OUTSIDE;
  private readonly picks = signal<Record<string, string>>({});
  private readonly reasons = signal<Record<string, string>>({});
  protected readonly missingReason = signal<string | null>(null);
  protected readonly busy = computed(() => !!this.store.busy()['choices']);

  protected readonly abbs = computed<AbbResult[]>(() => this.view().evaluation?.result.abbs ?? []);

  protected name(id: string): string {
    return this.view().catalog.abbs.find((a) => a.id === id)?.name ?? id;
  }

  /** Eligible and conditional SBBs, alphabetical: the only ones that can be chosen. */
  protected options(abb: AbbResult): SbbOutcome[] {
    return [...sbbsByResult(abb, 'eligible'), ...sbbsByResult(abb, 'conditional')].sort((a, b) =>
      a.id.localeCompare(b.id),
    );
  }

  protected current(abbId: string): ChoiceRecord | undefined {
    return this.view().choices.find((c) => c.abb === abbId);
  }

  protected sbbName(id: string | null): string {
    return this.view().catalog.sbbs.find((s) => s.id === id)?.name ?? id ?? '';
  }

  protected pick(abbId: string): string {
    return this.picks()[abbId] ?? '';
  }

  protected setPick(abbId: string, value: string): void {
    this.picks.update((all) => ({ ...all, [abbId]: value }));
    this.missingReason.set(null);
  }

  protected reason(abbId: string): string {
    return this.reasons()[abbId] ?? '';
  }

  protected setReason(abbId: string, value: string): void {
    this.reasons.update((all) => ({ ...all, [abbId]: value }));
    if (value.trim() && this.missingReason() === abbId) {
      this.missingReason.set(null);
    }
  }

  protected selected(abb: AbbResult): SbbOutcome | undefined {
    const id = this.pick(abb.id);
    return abb.sbbs.find((s) => s.id === id && s.result !== 'excluded');
  }

  protected needsReason(abb: AbbResult): boolean {
    return reasonRequired(this.selected(abb));
  }

  protected unresolved(abb: AbbResult, sbb: SbbOutcome): string[] {
    const result = this.view().evaluation?.result;
    const fromQuestions = result ? openQuestionsFor(result, abb.id).map((q) => q.attribute) : [];
    return [...new Set([...missingAnswers(sbb), ...fromQuestions])].sort();
  }

  protected async save(abb: AbbResult): Promise<void> {
    const pick = this.pick(abb.id);
    if (!pick || this.busy()) {
      return;
    }
    const reason = this.reason(abb.id).trim();
    if (this.needsReason(abb) && !reason) {
      this.missingReason.set(abb.id);
      return;
    }
    const kind = pick === LATER ? 'decide_later' : pick === OUTSIDE ? 'outside_catalog' : 'chosen';
    await this.store.choose(abb.id, kind, kind === 'chosen' ? pick : null, reason);
    if (!this.store.problems()['choices']) {
      this.reasons.update((all) => ({ ...all, [abb.id]: '' }));
      this.picks.update((all) => ({ ...all, [abb.id]: '' }));
    }
  }
}
