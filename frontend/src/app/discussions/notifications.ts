import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  Injectable,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';

import { Api, toProblem } from '../core/api';
import { Auth } from '../core/auth';
import type { ApiProblem } from '../core/models';
import { UserPreferences } from '../core/preferences';
import { ProblemNotice } from '../shared/problem-notice';
import { notificationLink } from './logic';
import type { Notification } from './models';

interface Listing {
  unread: number;
  items: Notification[];
}

/** The unread count shown in the header; refreshed now and then, never announced loudly. */
@Injectable({ providedIn: 'root' })
export class NotificationCount {
  private readonly api = inject(Api);
  readonly unread = signal(0);

  async refresh(): Promise<void> {
    try {
      const l = await firstValueFrom(this.api.get<Listing>('/notifications?unread=true'));
      this.unread.set(l.unread);
    } catch {
      // the bell is a convenience: stay quiet when the server cannot be reached
    }
  }
}

/** Header link with the number of unread notifications (architects only). */
@Component({
  selector: 'app-notification-link',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslocoPipe],
  template: `
    @if (auth.isArchitect()) {
      <a routerLink="/notifications" class="bell">
        {{ 'notifications.title' | transloco }}
        @if (count.unread() > 0) {
          <span class="badge badge-info">
            {{ count.unread() }}
            <span class="sr-only">{{ 'notifications.unread' | transloco }}</span>
          </span>
        }
      </a>
    }
  `,
  styles: `
    .bell {
      display: inline-flex;
      gap: var(--space-2);
      align-items: center;
    }
  `,
})
export class NotificationLink implements OnInit {
  protected readonly auth = inject(Auth);
  protected readonly count = inject(NotificationCount);
  private readonly destroyRef = inject(DestroyRef);

  ngOnInit(): void {
    void this.count.refresh();
    const timer = setInterval(() => {
      if (!document.hidden && this.auth.isArchitect()) {
        void this.count.refresh();
      }
    }, 60000);
    this.destroyRef.onDestroy(() => clearInterval(timer));
  }
}

/** Everything that happened that concerns me; in-application only (no e-mail in v1). */
@Component({
  selector: 'app-notifications',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, TranslocoPipe, ProblemNotice],
  template: `
    <div class="head">
      <h1>{{ 'notifications.title' | transloco }}</h1>
      @if (unread() > 0) {
        <button type="button" class="btn btn-secondary btn-sm" (click)="readAll()">
          {{ 'notifications.read_all' | transloco }}
        </button>
      }
    </div>
    <app-problem-notice [problem]="problem()" [retryable]="true" (retry)="load()" />
    @if (loading()) {
      <p role="status">
        <span class="spinner" aria-hidden="true"></span> {{ 'common.loading' | transloco }}
      </p>
    } @else if (!problem()) {
      @if (items().length === 0) {
        <div class="card">{{ 'notifications.empty' | transloco }}</div>
      } @else {
        <ul class="list">
          @for (n of items(); track n.id) {
            <li class="card" [class.unread]="!n.read_at">
              <p>
                @if (!n.read_at) {
                  <span class="badge badge-info">{{ 'notifications.new' | transloco }}</span>
                }
                <strong>{{ 'notifications.kind_' + n.kind | transloco }}</strong>
                — {{ text(n) }}
              </p>
              <p class="hint">
                {{ n.created_at | date: 'medium' : undefined : prefs.locale() }}
              </p>
              <div class="actions">
                <button type="button" class="btn btn-secondary btn-sm" (click)="open(n)">
                  {{ 'notifications.open' | transloco }}
                </button>
                @if (!n.read_at) {
                  <button type="button" class="btn btn-ghost btn-sm" (click)="read(n)">
                    {{ 'notifications.mark_read' | transloco }}
                  </button>
                }
              </div>
            </li>
          }
        </ul>
      }
    }
  `,
  styles: `
    .head {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: var(--space-4);
      margin-bottom: var(--space-4);
    }
    h1,
    p {
      margin: 0;
    }
    .list {
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    .unread {
      border-left: 3px solid var(--accent);
    }
    .actions {
      display: flex;
      gap: var(--space-2);
      margin-top: var(--space-2);
    }
  `,
})
export class NotificationsPage implements OnInit {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly count = inject(NotificationCount);
  protected readonly prefs = inject(UserPreferences);

  protected readonly items = signal<Notification[]>([]);
  protected readonly unread = signal(0);
  protected readonly loading = signal(true);
  protected readonly problem = signal<ApiProblem | null>(null);

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.problem.set(null);
    try {
      const l = await firstValueFrom(this.api.get<Listing>('/notifications'));
      this.items.set(l.items);
      this.unread.set(l.unread);
      this.count.unread.set(l.unread);
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.loading.set(false);
    }
  }

  /** One short line from the payload; the kind label above says what it is. */
  protected text(n: Notification): string {
    const p = n.payload;
    const title = typeof p['title'] === 'string' ? p['title'] : '';
    switch (n.kind) {
      case 'discussion_opened':
        return `${title} (${String(p['opened_by'] ?? '')})`;
      case 'mention':
        return `${String(p['by'] ?? '')}: ${title}`;
      case 'discussion_activity':
        return `${title}: ${String(p['what'] ?? '')}`;
      case 'discussion_reassigned':
        return `${title} (${String(p['by'] ?? '')})`;
      case 'decider_nudge':
        return title;
      case 'claim_expiring':
        return String(p['kind'] ?? '');
    }
  }

  protected async read(n: Notification): Promise<void> {
    try {
      await firstValueFrom(this.api.post(`/notifications/${n.id}/read`));
      this.items.update((all) =>
        all.map((x) => (x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x)),
      );
      this.unread.update((u) => Math.max(0, u - (n.read_at ? 0 : 1)));
      this.count.unread.set(this.unread());
    } catch (error) {
      this.problem.set(toProblem(error));
    }
  }

  protected async open(n: Notification): Promise<void> {
    await this.read(n);
    await this.router.navigate(notificationLink(n));
  }

  protected async readAll(): Promise<void> {
    try {
      await firstValueFrom(this.api.post('/notifications/read-all'));
      await this.load();
    } catch (error) {
      this.problem.set(toProblem(error));
    }
  }
}
