import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  numberAttribute,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import { Auth } from '../../core/auth';
import { UserPreferences } from '../../core/preferences';
import { ProblemNotice } from '../../shared/problem-notice';
import { SessionStore } from '../store';
import { AbbsRegion } from './abbs';
import { ChoicesRegion } from './choices';
import { ComparisonRegion } from './comparison';
import { ExportRegion } from './export';
import { FeedbackRegion } from './feedback';
import { QuestionsRegion } from './questions';
import { RationaleRegion } from './rationale';
import { RequirementRegion } from './requirement';
import { SummaryRegion } from './summary';
import { TraceDialog } from './trace-dialog';
import { UnderstoodRegion } from './understood';

const STAGES = ['interpreting', 'checking', 'evaluating'] as const;

/**
 * The living session page (consult.md 2-3): one page that updates as the user answers.
 * Regions are in the order of the spec; every recomputation is immediate and announced.
 */
@Component({
  selector: 'app-session',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    TranslocoPipe,
    ProblemNotice,
    RequirementRegion,
    UnderstoodRegion,
    QuestionsRegion,
    SummaryRegion,
    AbbsRegion,
    ComparisonRegion,
    RationaleRegion,
    ChoicesRegion,
    FeedbackRegion,
    ExportRegion,
    TraceDialog,
  ],
  template: `
    <app-trace-dialog />
    <p>
      <a routerLink="/consult">← {{ 'session.back' | transloco }}</a>
    </p>

    @if (store.consultation(); as view) {
      <header class="head">
        <div>
          <h1>{{ view.title }}</h1>
          <p class="hint">
            {{ 'session.by' | transloco: { owner: view.owner } }} ·
            {{ 'session.revision' | transloco: { n: view.revision.number } }}
          </p>
        </div>
        <fieldset class="detail">
          <legend class="hint">{{ 'session.detail' | transloco }}</legend>
          <label class="opt">
            <input
              type="radio"
              name="detail"
              value="summary"
              [checked]="prefs.detail() === 'summary'"
              (change)="prefs.setDetail('summary')"
            />
            {{ 'session.detail_summary' | transloco }}
          </label>
          <label class="opt">
            <input
              type="radio"
              name="detail"
              value="detailed"
              [checked]="prefs.detail() === 'detailed'"
              (change)="prefs.setDetail('detailed')"
            />
            {{ 'session.detail_detailed' | transloco }}
          </label>
        </fieldset>
      </header>

      @if (readOnly()) {
        <div class="notice notice-warning" role="note">
          <p>
            {{
              'session.old_revision'
                | transloco: { n: view.revision.number, latest: view.latest_revision }
            }}
            <a [routerLink]="['/consult', view.id]">{{ 'session.go_latest' | transloco }}</a>
          </p>
        </div>
      }

      @if (analysisRunning()) {
        <div class="notice" role="status">
          <span class="spinner" aria-hidden="true"></span>
          <ol class="stages">
            @for (s of stages; track s) {
              <li
                [attr.aria-current]="store.stage() === s ? 'step' : null"
                [class.done]="isDone(s)"
              >
                {{ 'stage.' + s | transloco }}
              </li>
            }
          </ol>
        </div>
      }

      <div class="stack">
        <app-requirement-region [view]="view" [readOnly]="readOnly()" />

        @if (analysisProblem(); as p) {
          @if (p.code === 'empty_catalog') {
            <div class="notice notice-warning" role="alert">
              <p>
                {{ 'session.empty_catalog' | transloco }}
                @if (auth.isArchitect()) {
                  {{ 'session.empty_catalog_architect' | transloco }}
                } @else {
                  {{ 'session.empty_catalog_user' | transloco }}
                }
              </p>
            </div>
          } @else {
            <app-problem-notice
              [problem]="p"
              [retryable]="!readOnly()"
              (retry)="store.retryAnalysis()"
            />
          }
        } @else if (!view.evaluation && !analysisRunning()) {
          <div class="notice notice-warning" role="status">
            <p>
              @if (view.revision.unrecognised) {
                {{ 'session.unrecognised' | transloco }}
              } @else {
                {{ 'session.not_analyzed' | transloco }}
              }
            </p>
            @if (!readOnly() && !view.revision.unrecognised) {
              <button
                type="button"
                class="btn btn-secondary btn-sm"
                (click)="store.retryAnalysis()"
              >
                {{ 'common.try_again' | transloco }}
              </button>
            }
          </div>
        }

        @if (view.evaluation || view.identified_abbs.length) {
          <app-understood-region [view]="view" [readOnly]="readOnly()" />
        }
        @if (view.evaluation) {
          <app-questions-region [view]="view" [readOnly]="readOnly()" />
          <app-summary-region [view]="view" />
          <app-abbs-region [view]="view" [detailed]="prefs.detail() === 'detailed'" />
          <app-comparison-region [view]="view" />
          <app-rationale-region [view]="view" [readOnly]="readOnly()" />
          <app-choices-region [view]="view" [readOnly]="readOnly()" />
          <app-feedback-region [view]="view" [readOnly]="readOnly()" />
          <app-export-region [view]="view" [readOnly]="readOnly()" />
        }
      </div>
    } @else if (store.stage()) {
      <div class="notice" role="status">
        <span class="spinner" aria-hidden="true"></span>
        <ol class="stages">
          @for (s of stages; track s) {
            <li [attr.aria-current]="store.stage() === s ? 'step' : null" [class.done]="isDone(s)">
              {{ 'stage.' + s | transloco }}
            </li>
          }
        </ol>
      </div>
    } @else if (store.loading()) {
      <p role="status">
        <span class="spinner" aria-hidden="true"></span> {{ 'common.loading' | transloco }}
      </p>
    } @else if (store.loadProblem(); as p) {
      <app-problem-notice [problem]="p" [retryable]="p.status !== 404" (retry)="store.refresh()" />
    } @else if (store.problems()['analysis']; as p) {
      <app-problem-notice [problem]="p" />
    }
  `,
  styles: `
    .head {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--space-4);
      margin-bottom: var(--space-4);
    }
    .head h1,
    .head p {
      margin: 0;
    }
    .detail {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
      border: 0;
      margin: 0;
      padding: 0;
    }
    .opt {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      min-height: 32px;
    }
    .stack {
      display: flex;
      flex-direction: column;
      gap: var(--space-4);
    }
    .notice {
      margin-bottom: var(--space-4);
      align-items: center;
    }
    .notice p {
      margin: 0;
    }
    .stages {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2) var(--space-5);
      margin: 0;
      padding: 0;
      list-style: none;
    }
    .stages li {
      color: var(--text-3);
    }
    .stages li[aria-current='step'] {
      color: var(--text);
      font-weight: 600;
    }
    .stages li.done {
      color: var(--text-2);
    }
    .stages li.done::before {
      content: '✓ ';
    }
  `,
})
export class SessionPage {
  protected readonly store = inject(SessionStore);
  protected readonly auth = inject(Auth);
  protected readonly prefs = inject(UserPreferences);

  /** Route parameter `:id`, bound by the router. */
  readonly id = input.required({ transform: numberAttribute });
  /** Optional `?revision=n` to read an earlier revision. */
  readonly revision = input<number | null, string | undefined>(null, {
    transform: (v) => (v ? Number(v) : null),
  });

  protected readonly stages = STAGES;
  protected readonly readOnly = computed(() => {
    const view = this.store.consultation();
    return !!view && view.revision.number !== view.latest_revision;
  });
  protected readonly analysisRunning = computed(() => this.store.stage() !== null);
  protected readonly analysisProblem = computed(() => this.store.problems()['analysis'] ?? null);

  constructor() {
    effect(() => {
      void this.store.open(this.id(), this.revision());
    });
  }

  protected isDone(stage: (typeof STAGES)[number]): boolean {
    const current = this.store.stage();
    return !!current && STAGES.indexOf(stage) < STAGES.indexOf(current as (typeof STAGES)[number]);
  }
}
