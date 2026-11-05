import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

import { Announcer } from './core/announcer';
import { Auth } from './core/auth';
import type { ThemePreference } from './core/models';
import { UserPreferences } from './core/preferences';
import { NotificationLink } from './discussions/notifications';

@Component({
  selector: 'app-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, TranslocoPipe, NotificationLink],
  template: `
    <a class="skip-link" href="#main" (click)="skipToMain($event)">{{
      'shell.skip' | transloco
    }}</a>
    <header class="shell-header">
      <div class="shell-bar">
        <a routerLink="/consult" class="brand">
          <span aria-hidden="true" class="mono brand-mark">=^.^=</span>
          <span>Cheshire</span>
        </a>
        @if (auth.user(); as user) {
          <nav [attr.aria-label]="'shell.nav' | transloco" class="shell-nav">
            <a routerLink="/consult" routerLinkActive="active" ariaCurrentWhenActive="page">{{
              'shell.consult' | transloco
            }}</a>
            <a routerLink="/catalog" routerLinkActive="active" ariaCurrentWhenActive="page">{{
              'shell.catalog' | transloco
            }}</a>
            @if (auth.isArchitect()) {
              <a routerLink="/discussions" routerLinkActive="active" ariaCurrentWhenActive="page">{{
                'shell.discussions' | transloco
              }}</a>
            }
          </nav>
          <div class="shell-tools">
            <label class="shell-theme">
              <span class="hint">{{ 'shell.theme' | transloco }}</span>
              <select class="input" [value]="prefs.theme()" (change)="setTheme($event)">
                <option value="system">{{ 'shell.theme_system' | transloco }}</option>
                <option value="light">{{ 'shell.theme_light' | transloco }}</option>
                <option value="dark">{{ 'shell.theme_dark' | transloco }}</option>
              </select>
            </label>
            <app-notification-link />
            <span>{{ user.display_name }}</span>
            <button type="button" class="btn btn-secondary btn-sm" (click)="logout()">
              {{ 'shell.sign_out' | transloco }}
            </button>
          </div>
        }
      </div>
    </header>
    <main id="main" tabindex="-1" class="page">
      <router-outlet />
    </main>
    <div class="sr-only" role="status" aria-live="polite" aria-atomic="true">
      {{ announcer.message() }}
    </div>
  `,
  styles: `
    .skip-link {
      position: absolute;
      left: -9999px;
      top: 8px;
      z-index: 60;
      padding: var(--space-2) var(--space-3);
      background: var(--surface);
      border-radius: var(--radius);
    }
    .skip-link:focus {
      left: 8px;
    }
    .shell-header {
      position: sticky;
      top: 0;
      z-index: 40;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      min-height: var(--header-height);
    }
    .shell-bar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-2) var(--space-6);
      max-width: var(--content-max);
      margin: 0 auto;
      padding: var(--space-2) var(--space-4);
    }
    @media (min-width: 640px) {
      .shell-bar {
        padding-left: var(--space-6);
        padding-right: var(--space-6);
      }
    }
    .brand {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      font-weight: 600;
      color: var(--text);
      text-decoration: none;
    }
    .brand-mark {
      color: var(--text-2);
    }
    .shell-nav {
      display: flex;
      gap: var(--space-1);
    }
    .shell-nav a {
      padding: var(--space-2) var(--space-3);
      border-radius: var(--radius);
      color: var(--text);
      text-decoration: none;
    }
    .shell-nav a:hover,
    .shell-nav a.active {
      background: var(--accent-soft-2);
    }
    .shell-tools {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-3);
      margin-left: auto;
    }
    .shell-theme {
      display: flex;
      align-items: center;
      gap: var(--space-2);
    }
    .shell-theme .input {
      width: auto;
    }
    main:focus {
      outline: none;
    }
  `,
})
export class App {
  protected readonly auth = inject(Auth);
  protected readonly prefs = inject(UserPreferences);
  protected readonly announcer = inject(Announcer);
  private readonly router = inject(Router);

  protected skipToMain(event: Event): void {
    event.preventDefault();
    document.getElementById('main')?.focus();
  }

  protected setTheme(event: Event): void {
    void this.prefs.setTheme((event.target as HTMLSelectElement).value as ThemePreference);
  }

  protected async logout(): Promise<void> {
    await this.auth.logout();
    await this.router.navigate(['/login']);
  }
}
