import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import type { Consultation, Sentence } from '../../core/models';
import { UserPreferences } from '../../core/preferences';
import { renderInline } from '../../shared/markdown';
import { ProblemNotice } from '../../shared/problem-notice';
import { entryByRef } from '../logic';
import { SessionStore } from '../store';
import { TraceViewer } from './trace-dialog';

/** Region 7: prose written from the trace; every sentence carries chips for its sources. */
@Component({
  selector: 'app-rationale-region',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoPipe, ProblemNotice],
  template: `
    <section class="card" aria-labelledby="rat-title" [attr.aria-busy]="busy()">
      <div class="head">
        <h2 id="rat-title">{{ 'rationale.title' | transloco }}</h2>
        @if (!readOnly()) {
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            [disabled]="busy()"
            (click)="generate()"
          >
            @if (busy()) {
              <span class="spinner" aria-hidden="true"></span>
            }
            {{ (view().rationale ? 'rationale.update' : 'rationale.generate') | transloco }}
          </button>
        }
      </div>

      <app-problem-notice
        [problem]="store.problems()['rationale'] ?? null"
        [retryable]="!readOnly()"
        (retry)="generate()"
      />

      @if (view().rationale; as r) {
        @if (r.outdated) {
          <p class="notice notice-warning" role="note">{{ 'rationale.outdated' | transloco }}</p>
        }
        @if (r.status !== 'ok') {
          <p class="notice notice-warning" role="note">
            {{ 'rationale.unverified' | transloco: { n: r.checker.unverified ?? 0 } }}
          </p>
        }
        <ol class="sentences">
          @for (s of r.content.sentences; track $index) {
            <li [class.unverified]="!s.verified">
              <span class="text" [innerHTML]="html(s)"></span>
              @if (!s.verified) {
                <span class="badge badge-warning">{{ 'rationale.not_verified' | transloco }}</span>
              }
              @for (ref of s.refs; track ref) {
                <button type="button" class="ref mono" (click)="open(ref)">
                  {{ ref }}
                  <span class="sr-only">{{ 'rationale.open_source' | transloco }}</span>
                </button>
              }
              @if (!s.verified && s.problems?.length) {
                <ul class="problems">
                  @for (p of s.problems; track p) {
                    <li>{{ p }}</li>
                  }
                </ul>
              }
            </li>
          }
        </ol>
      } @else if (busy()) {
        <p role="status">
          <span class="spinner" aria-hidden="true"></span> {{ 'rationale.writing' | transloco }}
        </p>
      } @else if (!store.problems()['rationale']) {
        <p class="hint">{{ 'rationale.none' | transloco }}</p>
      }
    </section>
  `,
  styles: `
    section {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    .head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-3);
    }
    h2 {
      margin: 0;
    }
    .sentences {
      margin: 0;
      padding-left: var(--space-5);
      display: grid;
      gap: var(--space-3);
    }
    .unverified .text {
      text-decoration: underline dotted var(--warning);
    }
    .ref {
      margin-left: var(--space-1);
      padding: 0 var(--space-2);
      min-height: 24px;
      font-size: 0.8rem;
      color: var(--text-2);
      background: var(--accent-soft);
      border: 1px solid var(--border-2);
      border-radius: var(--radius-sm);
      cursor: pointer;
    }
    .ref:hover {
      background: var(--accent-soft-2);
    }
    .problems {
      margin: var(--space-1) 0 0;
      padding-left: var(--space-5);
      color: var(--text-2);
    }
    p {
      margin: 0;
    }
  `,
})
export class RationaleRegion {
  protected readonly store = inject(SessionStore);
  private readonly viewer = inject(TraceViewer);
  private readonly prefs = inject(UserPreferences);

  readonly view = input.required<Consultation>();
  readonly readOnly = input(false);

  protected readonly busy = computed(() => !!this.store.busy()['rationale']);

  protected html(sentence: Sentence): string {
    return renderInline(sentence.text);
  }

  protected generate(): void {
    void this.store.generateRationale(this.prefs.detail());
  }

  /** A chip opens the trace entry it cites (invariant 6). */
  protected open(ref: string): void {
    const entry = entryByRef(this.view().evaluation?.trace ?? [], ref);
    this.viewer.open(ref, entry ? [entry] : []);
  }
}
