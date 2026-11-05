import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import { toProblem } from '../core/api';
import { Auth } from '../core/auth';
import type { ApiProblem } from '../core/models';
import { ProblemNotice } from '../shared/problem-notice';

@Component({
  selector: 'app-login',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslocoPipe, ProblemNotice],
  template: `
    <div class="login">
      <h1>{{ 'login.title' | transloco }}</h1>
      <p class="hint">{{ 'login.intro' | transloco }}</p>
      <form class="card" (ngSubmit)="submit()" #form="ngForm" novalidate>
        <app-problem-notice [problem]="problem()" />
        <div class="field">
          <label for="email">{{ 'login.email' | transloco }}</label>
          <input
            id="email"
            name="email"
            type="email"
            class="input"
            autocomplete="username"
            required
            [(ngModel)]="email"
            [attr.aria-invalid]="problem() ? 'true' : null"
          />
        </div>
        <div class="field">
          <label for="password">{{ 'login.password' | transloco }}</label>
          <input
            id="password"
            name="password"
            type="password"
            class="input"
            autocomplete="current-password"
            required
            [(ngModel)]="password"
            [attr.aria-invalid]="problem() ? 'true' : null"
          />
        </div>
        <button
          type="submit"
          class="btn btn-primary"
          [disabled]="busy()"
          [attr.data-loading]="busy()"
        >
          @if (busy()) {
            <span class="spinner" aria-hidden="true"></span>
          }
          {{ 'login.submit' | transloco }}
        </button>
      </form>
    </div>
  `,
  styles: `
    .login {
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
export class LoginPage {
  private readonly auth = inject(Auth);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected email = '';
  protected password = '';
  protected readonly busy = signal(false);
  protected readonly problem = signal<ApiProblem | null>(null);

  protected async submit(): Promise<void> {
    if (this.busy()) {
      return;
    }
    if (!this.email || !this.password) {
      this.problem.set({ status: 0, code: 'missing_credentials', message: '' });
      return;
    }
    this.busy.set(true);
    this.problem.set(null);
    try {
      await this.auth.login(this.email, this.password);
      const next = this.route.snapshot.queryParamMap.get('next');
      await this.router.navigateByUrl(next && next.startsWith('/') ? next : '/consult');
    } catch (error) {
      this.problem.set(toProblem(error)); // the typed email stays (ui-spec 6.2)
      this.password = '';
    } finally {
      this.busy.set(false);
    }
  }
}
