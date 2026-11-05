import { ChangeDetectionStrategy, Component, computed, inject, input, output } from '@angular/core';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';

import type { ApiProblem } from '../core/models';

/**
 * A persistent error next to the region it affects (ui-spec 7): what happened, in plain
 * language, and a safe action (retry) when there is one. Never shows internals.
 */
@Component({
  selector: 'app-problem-notice',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoPipe],
  template: `
    @if (problem(); as p) {
      <div class="notice notice-danger" role="alert">
        <div class="body">
          <p class="title">{{ text() }}</p>
          @if (p.problems?.length) {
            <ul>
              @for (line of p.problems; track line) {
                <li>{{ line }}</li>
              }
            </ul>
          }
        </div>
        @if (retryable()) {
          <button type="button" class="btn btn-secondary btn-sm" (click)="retry.emit()">
            {{ 'common.try_again' | transloco }}
          </button>
        }
      </div>
    }
  `,
  styles: `
    .body {
      flex: 1;
      min-width: 0;
    }
    .title {
      margin: 0;
      font-weight: 500;
    }
    ul {
      margin: var(--space-2) 0 0;
      padding-left: var(--space-5);
    }
  `,
})
export class ProblemNotice {
  private readonly i18n = inject(TranslocoService);

  readonly problem = input<ApiProblem | null>(null);
  readonly retryable = input(false);
  readonly retry = output<void>();

  protected readonly text = computed(() => {
    const p = this.problem();
    if (!p) {
      return '';
    }
    const key = `errors.${p.code}`;
    const translated = this.i18n.translate(key);
    return translated !== key ? translated : this.i18n.translate('errors.generic');
  });
}
