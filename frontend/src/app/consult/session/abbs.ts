import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import type { AbbResult, CatalogSbb, Consultation, SbbOutcome } from '../../core/models';
import { CoverageBadge, ResultBadge, StateBadge, StatusBadge } from '../../shared/badges';
import { entriesFor, groupAbbs, missingAnswers, openQuestionsFor, sbbsByResult } from '../logic';
import { TraceViewer } from './trace-dialog';

/**
 * Region 5: the ABBs of the result, grouped. SBBs are listed alphabetically with neutral
 * state labels; nothing here sorts, scores or marks a "best" option (invariant 2).
 */
@Component({
  selector: 'app-abbs-region',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoPipe, CoverageBadge, StatusBadge, StateBadge, ResultBadge],
  template: `
    <section aria-labelledby="abbs-title" class="region">
      <h2 id="abbs-title">{{ 'abbs.title' | transloco }}</h2>
      @for (g of groups(); track g.group) {
        <section [attr.aria-labelledby]="'group-' + g.group" class="group">
          <h3 [id]="'group-' + g.group">
            {{ 'abbs.group_' + g.group | transloco }}
            <span class="hint mono">{{ g.abbs.length }}</span>
          </h3>
          @for (abb of g.abbs; track abb.id) {
            <article class="card abb" [attr.aria-labelledby]="'abb-' + abb.id">
              <header>
                <h4 [id]="'abb-' + abb.id">{{ name(abb.id) }}</h4>
                <span class="badges">
                  <app-coverage-badge [coverage]="abb.coverage" />
                  @if (abb.strength) {
                    <span class="badge">{{ 'abbs.strength_' + abb.strength | transloco }}</span>
                  }
                  @if (abb.validation) {
                    <app-status-badge [status]="abb.validation" />
                  }
                </span>
              </header>
              @if (description(abb.id); as text) {
                <p class="desc">{{ text }}</p>
              }
              <p class="why-row">
                <button type="button" class="btn btn-secondary btn-sm" (click)="why(abb)">
                  {{ 'abbs.why' | transloco }}
                  <span class="sr-only">{{ name(abb.id) }}</span>
                </button>
                <span class="hint">{{ 'abbs.activation_' + abb.activation | transloco }}</span>
              </p>

              @if (abb.coverage === 'gap') {
                <div class="notice" role="note">
                  <p>{{ 'abbs.gap' | transloco }}</p>
                </div>
              }

              @if (candidates(abb).length) {
                <h5>{{ 'abbs.candidates' | transloco }}</h5>
                <ul class="sbbs">
                  @for (s of candidates(abb); track s.id) {
                    <li>
                      <details [open]="detailed()">
                        <summary>
                          <span class="sbb-name">{{ s.name }}</span>
                          <app-result-badge [result]="s.result" />
                          <app-state-badge [state]="s.state" />
                          @if (s.status !== 'validated') {
                            <app-status-badge [status]="s.status" />
                          }
                        </summary>
                        <div class="sbb-body">
                          @if (s.result === 'conditional') {
                            <p class="notice notice-warning">
                              {{ 'abbs.needs_answer' | transloco }}
                              {{ answerNames(s) }}
                            </p>
                          }
                          @if (detail(s.id); as d) {
                            @if (d.when_to_choose) {
                              <p>
                                <strong>{{ 'abbs.when_to_choose' | transloco }}</strong>
                                {{ d.when_to_choose }}
                              </p>
                            }
                            @if (d.limitations) {
                              <p>
                                <strong>{{ 'abbs.limitations' | transloco }}</strong>
                                {{ d.limitations }}
                              </p>
                            }
                            @if (characteristics(d).length) {
                              <dl class="chars">
                                @for (c of characteristics(d); track c[0]) {
                                  <dt class="mono">{{ c[0] }}</dt>
                                  <dd class="mono">{{ c[1] }}</dd>
                                }
                              </dl>
                            }
                          }
                          @for (note of s.notes; track note) {
                            <p class="hint">{{ note }}</p>
                          }
                        </div>
                      </details>
                    </li>
                  }
                </ul>
              }

              @if (excluded(abb).length) {
                <h5>{{ 'abbs.excluded' | transloco }}</h5>
                <ul class="sbbs">
                  @for (s of excluded(abb); track s.id) {
                    <li class="excluded">
                      <span class="sbb-name">{{ s.name }}</span>
                      <app-result-badge [result]="s.result" />
                      <app-state-badge [state]="s.state" />
                      <span class="reason">
                        {{ s.exclusion ? ('abbs.exclusion_' + s.exclusion | transloco) : '' }}
                        @if (s.reason) {
                          — {{ s.reason }}
                        }
                      </span>
                    </li>
                  }
                </ul>
              }

              @if (questionsFor(abb).length) {
                <p class="hint">
                  {{ 'abbs.open_questions' | transloco }}
                  <span class="mono">{{ questionsFor(abb).join(', ') }}</span>
                </p>
              }
            </article>
          }
        </section>
      }
    </section>
  `,
  styles: `
    .region,
    .group {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    h2,
    h3,
    h4,
    h5 {
      margin: 0;
    }
    h5 {
      font-size: 0.93rem;
      color: var(--text-2);
      margin-top: var(--space-2);
    }
    .abb {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
    }
    header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-2);
    }
    .badges {
      display: inline-flex;
      flex-wrap: wrap;
      gap: var(--space-2);
    }
    .desc,
    .why-row {
      margin: 0;
    }
    .why-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-3);
    }
    .sbbs {
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: var(--space-2);
    }
    .sbbs > li {
      padding: var(--space-2) var(--space-3);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--surface-2);
    }
    summary {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-2);
      cursor: pointer;
      min-height: 32px;
    }
    .sbb-name {
      font-weight: 600;
    }
    .sbb-body {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      padding-top: var(--space-2);
    }
    .sbb-body p {
      margin: 0;
    }
    .chars {
      display: grid;
      grid-template-columns: max-content 1fr;
      gap: var(--space-1) var(--space-4);
      margin: 0;
    }
    .chars dd {
      margin: 0;
    }
    .excluded {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-2);
    }
    .reason {
      color: var(--text-2);
    }
    .notice p {
      margin: 0;
    }
  `,
})
export class AbbsRegion {
  private readonly viewer = inject(TraceViewer);
  readonly view = input.required<Consultation>();
  readonly detailed = input(false);

  protected readonly groups = computed(() => {
    const evaluation = this.view().evaluation;
    return evaluation ? groupAbbs(evaluation.result) : [];
  });

  protected name(id: string): string {
    return this.view().catalog.abbs.find((a) => a.id === id)?.name ?? id;
  }

  protected description(id: string): string {
    return this.view().catalog.abbs.find((a) => a.id === id)?.description ?? '';
  }

  protected detail(sbbId: string): CatalogSbb | undefined {
    return this.view().catalog.sbbs.find((s) => s.id === sbbId);
  }

  protected characteristics(d: CatalogSbb): [string, string][] {
    return Object.entries(d.characteristics).sort(([a], [b]) => a.localeCompare(b));
  }

  /** Eligible and conditional SBBs together, alphabetical by id: the label tells them apart. */
  protected candidates(abb: AbbResult): SbbOutcome[] {
    return [...sbbsByResult(abb, 'eligible'), ...sbbsByResult(abb, 'conditional')].sort((a, b) =>
      a.id.localeCompare(b.id),
    );
  }

  protected excluded(abb: AbbResult): SbbOutcome[] {
    return sbbsByResult(abb, 'excluded');
  }

  protected questionsFor(abb: AbbResult): string[] {
    const result = this.view().evaluation?.result;
    return result ? openQuestionsFor(result, abb.id).map((q) => q.attribute) : [];
  }

  protected answerNames(s: SbbOutcome): string {
    return missingAnswers(s).join(', ');
  }

  protected why(abb: AbbResult): void {
    const trace = this.view().evaluation?.trace ?? [];
    this.viewer.open(this.name(abb.id), entriesFor(trace, abb.id));
  }
}
