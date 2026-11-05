import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import type { Consultation } from '../../core/models';
import { ProblemNotice } from '../../shared/problem-notice';
import { highlightSegments, spanSources } from '../logic';
import { SessionStore } from '../store';

/** Region 1: the requirement, read-only, with the Interpreter's spans marked by chips. */
@Component({
  selector: 'app-requirement-region',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, TranslocoPipe, ProblemNotice],
  template: `
    <section class="card" aria-labelledby="req-title">
      <h2 id="req-title">{{ 'requirement.title' | transloco }}</h2>

      @if (view().revisions.length > 1) {
        <nav [attr.aria-label]="'requirement.revisions' | transloco" class="revisions">
          <span class="hint">{{ 'requirement.revisions' | transloco }}</span>
          @for (r of view().revisions; track r.number) {
            <a
              class="chip-link"
              [routerLink]="['/consult', view().id]"
              [queryParams]="r.number === view().latest_revision ? {} : { revision: r.number }"
              [attr.aria-current]="r.number === view().revision.number ? 'page' : null"
              >{{ r.number }}</a
            >
          }
        </nav>
      }

      @if (editing()) {
        <form (ngSubmit)="save()" novalidate>
          <div class="field">
            <label for="rewrite">{{ 'requirement.rewrite' | transloco }}</label>
            <textarea
              id="rewrite"
              name="rewrite"
              class="input"
              rows="6"
              [(ngModel)]="draft"
            ></textarea>
            <span class="hint">{{ 'requirement.rewrite_hint' | transloco }}</span>
          </div>
          <div class="actions">
            <button type="submit" class="btn btn-primary" [disabled]="busy() || !draft.trim()">
              {{ 'requirement.analyze_again' | transloco }}
            </button>
            <button type="button" class="btn btn-ghost" (click)="editing.set(false)">
              {{ 'common.cancel' | transloco }}
            </button>
          </div>
        </form>
      } @else {
        <p class="text" [attr.aria-label]="'requirement.text_label' | transloco">
          @for (segment of segments(); track $index) {
            @if (segment.chips.length) {
              <mark
                >{{ segment.text }}<sup class="chips">{{ segment.chips.join(',') }}</sup></mark
              >
            } @else {
              <span>{{ segment.text }}</span>
            }
          }
        </p>

        @if (sources().length) {
          <ol class="legend" [attr.aria-label]="'requirement.legend' | transloco">
            @for (s of sources(); track s.index) {
              <li value="{{ s.index }}">
                <span class="mono">{{ s.id }}</span>
                <span class="hint">
                  {{
                    s.kind === 'abb'
                      ? ('requirement.legend_abb' | transloco)
                      : ('requirement.legend_attribute' | transloco)
                  }}</span
                >
              </li>
            }
          </ol>
        }
        @if (!readOnly()) {
          <button type="button" class="btn btn-secondary btn-sm" (click)="startEditing()">
            {{ 'requirement.edit' | transloco }}
          </button>
        }
      }
      <app-problem-notice [problem]="store.problems()['analysis'] ?? null" />
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
    .text {
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    mark {
      background: var(--accent-soft-2);
      color: inherit;
      border-radius: var(--radius-sm);
      padding: 0 2px;
      border-bottom: 2px solid var(--accent);
    }
    .chips {
      margin-left: 2px;
      font-family: var(--mono);
      font-size: 0.75rem;
      font-weight: 600;
    }
    .legend {
      margin: 0;
      padding-left: var(--space-6);
      list-style: decimal;
    }
    .legend li + li {
      margin-top: var(--space-1);
    }
    .revisions {
      display: flex;
      align-items: center;
      gap: var(--space-2);
    }
    .chip-link {
      min-width: 28px;
      text-align: center;
      padding: 1px var(--space-2);
      border: 1px solid var(--border-2);
      border-radius: var(--radius-sm);
      font-family: var(--mono);
      text-decoration: none;
    }
    .chip-link[aria-current='page'] {
      background: var(--accent-soft-2);
      font-weight: 600;
    }
    form {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
  `,
})
export class RequirementRegion {
  protected readonly store = inject(SessionStore);
  readonly view = input.required<Consultation>();
  readonly readOnly = input(false);

  protected readonly editing = signal(false);
  protected draft = '';

  protected readonly sources = computed(() => spanSources(this.view()));
  protected readonly segments = computed(() =>
    highlightSegments(this.view().revision.requirement_text, this.sources()),
  );
  protected readonly busy = computed(() => this.store.stage() !== null);

  protected startEditing(): void {
    this.draft = this.view().revision.requirement_text;
    this.editing.set(true);
  }

  protected async save(): Promise<void> {
    if (!this.draft.trim() || this.busy()) {
      return;
    }
    this.editing.set(false);
    await this.store.revise(this.draft);
  }
}
