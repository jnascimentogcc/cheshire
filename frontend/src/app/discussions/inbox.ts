import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';

import { Api, toProblem } from '../core/api';
import { Auth } from '../core/auth';
import type { ApiProblem } from '../core/models';
import { UserPreferences } from '../core/preferences';
import { ProblemNotice } from '../shared/problem-notice';
import { ROUTE_OF_KIND } from '../catalog/models';
import type { InboxRow, Tab } from './models';

/** Where discussions are found: what needs me, what I opened, everything open, closed. */
@Component({
  selector: 'app-discussion-inbox',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, FormsModule, TranslocoPipe, ProblemNotice],
  template: `
    <div class="head">
      <div>
        <h1>{{ 'discussions.title' | transloco }}</h1>
        <p class="hint">{{ 'discussions.intro' | transloco }}</p>
      </div>
      <a routerLink="/discussions/new" class="btn btn-primary">{{
        'discussions.new' | transloco
      }}</a>
    </div>

    <div role="group" [attr.aria-label]="'discussions.tabs' | transloco" class="tabs">
      @for (t of tabs(); track t) {
        <button
          type="button"
          class="btn btn-sm"
          [class.btn-primary]="tab() === t"
          [class.btn-secondary]="tab() !== t"
          [attr.aria-pressed]="tab() === t"
          (click)="choose(t)"
        >
          {{ 'discussions.tab_' + t | transloco }}
        </button>
      }
    </div>

    <form class="filters" (submit)="$event.preventDefault(); load()">
      <label class="field">
        <span class="label">{{ 'discussions.f_kind' | transloco }}</span>
        <select class="input" name="kind" [(ngModel)]="kind">
          <option value="">{{ 'discussions.f_any' | transloco }}</option>
          @for (k of kinds; track k) {
            <option [value]="k">{{ 'kind.' + routeOf[k] | transloco }}</option>
          }
        </select>
      </label>
      <label class="field">
        <span class="label">{{ 'discussions.f_domain' | transloco }}</span>
        <input class="input" name="domain" [(ngModel)]="domain" />
      </label>
      <label class="field">
        <span class="label">{{ 'discussions.f_older' | transloco }}</span>
        <input class="input" type="number" min="0" name="older" [(ngModel)]="older" />
      </label>
      <label class="field">
        <span class="label">{{ 'discussions.f_inactive' | transloco }}</span>
        <input class="input" type="number" min="0" name="inactive" [(ngModel)]="inactive" />
      </label>
      <button type="submit" class="btn btn-secondary">{{ 'discussions.apply' | transloco }}</button>
    </form>

    <app-problem-notice [problem]="problem()" [retryable]="true" (retry)="load()" />

    @if (loading()) {
      <p role="status">
        <span class="spinner" aria-hidden="true"></span> {{ 'common.loading' | transloco }}
      </p>
    } @else if (!problem()) {
      @if (rows().length === 0) {
        <div class="card">
          <p>{{ 'discussions.empty_' + tab() | transloco }}</p>
          @if (tab() === 'open') {
            <p class="hint">{{ 'discussions.empty_hint' | transloco }}</p>
          }
        </div>
      } @else {
        <div class="table-wrap card">
          <table class="data">
            <caption class="sr-only">
              {{
                'discussions.tab_' + tab() | transloco
              }}
            </caption>
            <thead>
              <tr>
                <th scope="col">{{ 'discussions.col_title' | transloco }}</th>
                <th scope="col">{{ 'discussions.col_item' | transloco }}</th>
                <th scope="col">{{ 'discussions.col_decider' | transloco }}</th>
                <th scope="col">{{ 'discussions.col_activity' | transloco }}</th>
                <th scope="col">{{ 'discussions.col_state' | transloco }}</th>
              </tr>
            </thead>
            <tbody>
              @for (r of rows(); track r.id) {
                <tr>
                  <th scope="row">
                    <a [routerLink]="['/discussions', r.id]">{{ r.title }}</a>
                  </th>
                  <td class="mono">{{ r.item_kind }}:{{ r.item_slug }}</td>
                  <td>
                    {{ r.decider }}
                    @if (!r.decider_active) {
                      <span class="badge badge-warning">{{
                        'discussions.decider_left' | transloco
                      }}</span>
                    }
                    @if (r.i_decide) {
                      <span class="badge badge-info">{{
                        'discussions.you_decide' | transloco
                      }}</span>
                    }
                  </td>
                  <td>
                    {{ r.last_activity | date: 'medium' : undefined : prefs.locale() }}
                    <span class="hint">{{
                      'discussions.inactive' | transloco: { n: r.inactive_days }
                    }}</span>
                  </td>
                  <td>
                    <span class="badge badge-neutral">{{
                      'discussions.status_' + r.status | transloco
                    }}</span>
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
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
    .head p {
      margin: 0;
    }
    .tabs {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      margin-bottom: var(--space-4);
    }
    .filters {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
      align-items: flex-end;
      margin-bottom: var(--space-4);
    }
  `,
})
export class DiscussionInboxPage implements OnInit {
  private readonly api = inject(Api);
  protected readonly auth = inject(Auth);
  protected readonly prefs = inject(UserPreferences);

  protected readonly routeOf = ROUTE_OF_KIND;
  protected readonly kinds = ['abb', 'sbb', 'rule', 'attribute', 'characteristic', 'lens'] as const;
  protected readonly tab = signal<Tab>('attention');
  protected readonly rows = signal<InboxRow[]>([]);
  protected readonly loading = signal(true);
  protected readonly problem = signal<ApiProblem | null>(null);
  protected kind = '';
  protected domain = '';
  protected older: number | null = null;
  protected inactive: number | null = null;

  protected tabs(): Tab[] {
    const base: Tab[] = ['attention', 'mine', 'open', 'closed'];
    return this.auth.user()?.role === 'admin' ? [...base, 'orphaned'] : base;
  }

  ngOnInit(): void {
    void this.load();
  }

  protected choose(tab: Tab): void {
    this.tab.set(tab);
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.problem.set(null);
    const q = new URLSearchParams({ tab: this.tab() });
    if (this.kind) {
      q.set('kind', this.kind);
    }
    if (this.domain.trim()) {
      q.set('domain', this.domain.trim());
    }
    if (this.older !== null && this.older !== undefined) {
      q.set('older_than_days', String(this.older));
    }
    if (this.inactive !== null && this.inactive !== undefined) {
      q.set('inactive_days', String(this.inactive));
    }
    try {
      this.rows.set(await firstValueFrom(this.api.get<InboxRow[]>(`/discussions?${q}`)));
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.loading.set(false);
    }
  }
}
