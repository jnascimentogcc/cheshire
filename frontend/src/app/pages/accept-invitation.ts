import { ChangeDetectionStrategy, Component, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';

import { Api, toProblem } from '../core/api';
import type { ApiProblem } from '../core/models';
import { ProblemNotice } from '../shared/problem-notice';

const MIN_PASSWORD = 12;

@Component({
  selector: 'app-accept-invitation',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslocoPipe, ProblemNotice],
  template: `
    <div class="accept">
      <h1>{{ 'invitation.title' | transloco }}</h1>
      <form class="card" (ngSubmit)="submit()" novalidate>
        <app-problem-notice [problem]="problem()" />
        <div class="field">
          <label for="name">{{ 'invitation.name' | transloco }}</label>
          <input
            id="name"
            name="name"
            class="input"
            required
            autocomplete="name"
            [(ngModel)]="name"
          />
        </div>
        <div class="field">
          <label for="password">{{ 'invitation.password' | transloco }}</label>
          <input
            id="password"
            name="password"
            type="password"
            class="input"
            required
            autocomplete="new-password"
            aria-describedby="password-hint"
            [(ngModel)]="password"
          />
          <span id="password-hint" class="hint">{{
            'invitation.password_hint' | transloco: { n: min }
          }}</span>
        </div>
        <button type="submit" class="btn btn-primary" [disabled]="busy()">
          {{ 'invitation.submit' | transloco }}
        </button>
      </form>
    </div>
  `,
  styles: `
    .accept {
      max-width: 420px;
      margin: var(--space-10) auto;
    }
    form {
      display: flex;
      flex-direction: column;
      gap: var(--space-4);
    }
  `,
})
export class AcceptInvitationPage {
  private readonly api = inject(Api);
  private readonly router = inject(Router);

  /** From the `?token=` query parameter. */
  readonly token = input('');

  protected readonly min = MIN_PASSWORD;
  protected name = '';
  protected password = '';
  protected readonly busy = signal(false);
  protected readonly problem = signal<ApiProblem | null>(null);

  protected async submit(): Promise<void> {
    if (this.busy()) {
      return;
    }
    if (!this.token()) {
      this.problem.set({ status: 400, code: 'invalid_invitation', message: '' });
      return;
    }
    if (!this.name.trim() || this.password.length < MIN_PASSWORD) {
      this.problem.set({ status: 422, code: 'weak_password', message: '' });
      return;
    }
    this.busy.set(true);
    this.problem.set(null);
    try {
      await firstValueFrom(
        this.api.post('/auth/accept-invitation', {
          token: this.token(),
          display_name: this.name.trim(),
          password: this.password,
        }),
      );
      await this.router.navigate(['/login']);
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.busy.set(false);
    }
  }
}
