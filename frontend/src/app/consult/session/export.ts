import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';

import { Auth } from '../../core/auth';
import type { Consultation } from '../../core/models';
import { ProblemNotice } from '../../shared/problem-notice';
import { SessionStore } from '../store';

/** Region 10: Markdown and JSON export; architects can also pin a reference case. */
@Component({
  selector: 'app-export-region',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslocoPipe, ProblemNotice],
  template: `
    <section class="card" aria-labelledby="exp-title">
      <h2 id="exp-title">{{ 'export.title' | transloco }}</h2>
      <p class="hint">{{ 'export.intro' | transloco }}</p>
      <app-problem-notice [problem]="store.problems()['export'] ?? null" />
      <div class="actions">
        <button
          type="button"
          class="btn btn-secondary"
          [disabled]="exporting()"
          (click)="store.download('markdown')"
        >
          {{ 'export.markdown' | transloco }}
        </button>
        <button
          type="button"
          class="btn btn-secondary"
          [disabled]="exporting()"
          (click)="store.download('json')"
        >
          {{ 'export.json' | transloco }}
        </button>
      </div>

      @if (auth.isArchitect() && !readOnly()) {
        <h3>{{ 'pin.title' | transloco }}</h3>
        <p class="hint">{{ 'pin.intro' | transloco }}</p>
        <app-problem-notice [problem]="store.problems()['pin'] ?? null" />
        @if (view().pinned; as p) {
          <p>
            {{ 'pin.pinned' | transloco: { title: p.title, by: p.pinned_by } }}
          </p>
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            [disabled]="pinning()"
            (click)="store.unpin()"
          >
            {{ 'pin.unpin' | transloco }}
          </button>
        } @else {
          <form class="pin" (ngSubmit)="pin()">
            <div class="field">
              <label for="pin-title">{{ 'pin.name' | transloco }}</label>
              <input
                id="pin-title"
                name="title"
                class="input"
                maxlength="200"
                [(ngModel)]="title"
              />
            </div>
            <button
              type="submit"
              class="btn btn-secondary"
              [disabled]="pinning() || !title.trim() || !view().evaluation"
            >
              {{ 'pin.pin' | transloco }}
            </button>
          </form>
        }
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
    h3,
    p {
      margin: 0;
    }
    .actions,
    .pin {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-end;
      gap: var(--space-3);
    }
    .pin .field {
      min-width: 260px;
    }
    button {
      align-self: flex-start;
    }
  `,
})
export class ExportRegion {
  protected readonly store = inject(SessionStore);
  protected readonly auth = inject(Auth);
  readonly view = input.required<Consultation>();
  readonly readOnly = input(false);

  protected title = '';
  protected readonly exporting = computed(() => !!this.store.busy()['export']);
  protected readonly pinning = computed(() => !!this.store.busy()['pin']);

  protected async pin(): Promise<void> {
    if (this.title.trim()) {
      await this.store.pin(this.title.trim());
    }
  }
}
