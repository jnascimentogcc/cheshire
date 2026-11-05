import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import { ProblemNotice } from '../shared/problem-notice';
import { SessionStore } from './store';

const MAX_LENGTH = 20000;

@Component({
  selector: 'app-consult-new',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslocoPipe, ProblemNotice],
  template: `
    <h1>{{ 'new.title' | transloco }}</h1>
    <p class="hint">{{ 'new.intro' | transloco }}</p>

    <form class="card" (ngSubmit)="submit()" novalidate>
      <app-problem-notice [problem]="store.problems()['analysis'] ?? null" />
      <div class="field">
        <label for="requirement">{{ 'new.requirement' | transloco }}</label>
        <textarea
          id="requirement"
          name="requirement"
          class="input"
          rows="8"
          required
          [maxLength]="max"
          aria-describedby="requirement-hint requirement-error"
          [attr.aria-invalid]="empty() ? 'true' : null"
          [(ngModel)]="requirement"
          (ngModelChange)="empty.set(false)"
        ></textarea>
        <span id="requirement-hint" class="hint">{{ 'new.requirement_hint' | transloco }}</span>
        <span id="requirement-error" class="error-text" role="alert">
          @if (empty()) {
            {{ 'new.requirement_empty' | transloco }}
          }
        </span>
      </div>
      <div class="field">
        <label for="title">{{ 'new.name' | transloco }}</label>
        <input
          id="title"
          name="title"
          class="input"
          maxlength="200"
          [(ngModel)]="title"
          aria-describedby="title-hint"
        />
        <span id="title-hint" class="hint">{{ 'new.name_hint' | transloco }}</span>
      </div>
      <div class="actions">
        <button
          type="submit"
          class="btn btn-primary"
          [disabled]="running()"
          [attr.data-loading]="running()"
        >
          @if (running()) {
            <span class="spinner" aria-hidden="true"></span>
          }
          {{ 'new.analyze' | transloco }}
        </button>
      </div>
      @if (running() && store.stage(); as stage) {
        <p role="status">
          <span class="spinner" aria-hidden="true"></span> {{ 'stage.' + stage | transloco }}
        </p>
      }
    </form>
  `,
  styles: `
    form {
      display: flex;
      flex-direction: column;
      gap: var(--space-4);
      max-width: 820px;
    }
    textarea {
      resize: vertical;
    }
  `,
})
export class ConsultNewPage {
  protected readonly store = inject(SessionStore);
  private readonly router = inject(Router);

  protected readonly max = MAX_LENGTH;
  protected requirement = '';
  protected title = '';
  protected readonly empty = signal(false);
  protected readonly running = signal(false);

  protected async submit(): Promise<void> {
    if (this.running()) {
      return;
    }
    if (!this.requirement.trim()) {
      this.empty.set(true);
      return;
    }
    this.running.set(true);
    try {
      await this.store.startNew(this.requirement, this.title, (id) => {
        void this.router.navigate(['/consult', id]);
      });
    } finally {
      this.running.set(false);
    }
  }
}
