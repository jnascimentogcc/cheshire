import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';

import { Api, toProblem } from '../core/api';
import { Auth } from '../core/auth';
import type { ApiProblem, ConsultationListItem } from '../core/models';
import { UserPreferences } from '../core/preferences';
import { ProblemNotice } from '../shared/problem-notice';

@Component({
  selector: 'app-consult-list',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, TranslocoPipe, ProblemNotice],
  template: `
    <div class="page-head">
      <div>
        <h1>{{ 'list.title' | transloco }}</h1>
        <p class="hint">{{ 'list.intro' | transloco }}</p>
      </div>
      <a routerLink="/consult/new" class="btn btn-primary">{{ 'list.new' | transloco }}</a>
    </div>

    <app-problem-notice [problem]="problem()" [retryable]="true" (retry)="load()" />

    @if (loading()) {
      <p role="status">
        <span class="spinner" aria-hidden="true"></span> {{ 'common.loading' | transloco }}
      </p>
    } @else if (!problem()) {
      @if (items().length === 0) {
        <div class="card empty">
          <p>{{ 'list.empty' | transloco }}</p>
          <a routerLink="/consult/new" class="btn btn-secondary">{{
            'list.empty_action' | transloco
          }}</a>
        </div>
      } @else {
        <div class="table-wrap card">
          <table class="data">
            <caption class="sr-only">
              {{
                'list.title' | transloco
              }}
            </caption>
            <thead>
              <tr>
                <th scope="col">{{ 'list.col_title' | transloco }}</th>
                @if (auth.isArchitect()) {
                  <th scope="col">{{ 'list.col_owner' | transloco }}</th>
                }
                <th scope="col">{{ 'list.col_created' | transloco }}</th>
                <th scope="col">{{ 'list.col_revisions' | transloco }}</th>
              </tr>
            </thead>
            <tbody>
              @for (item of items(); track item.id) {
                <tr>
                  <th scope="row">
                    <a [routerLink]="['/consult', item.id]">{{ item.title }}</a>
                  </th>
                  @if (auth.isArchitect()) {
                    <td>{{ item.owner }}</td>
                  }
                  <td class="mono">
                    {{ item.created_at | date: 'medium' : undefined : prefs.locale() }}
                  </td>
                  <td class="mono">{{ item.revisions }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    }
  `,
  styles: `
    .page-head {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--space-4);
      margin-bottom: var(--space-4);
    }
    .page-head h1,
    .page-head p {
      margin: 0;
    }
    .empty {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: var(--space-3);
    }
    .empty p {
      margin: 0;
    }
    th[scope='row'] {
      font-weight: 500;
    }
  `,
})
export class ConsultListPage implements OnInit {
  private readonly api = inject(Api);
  protected readonly auth = inject(Auth);
  protected readonly prefs = inject(UserPreferences);

  protected readonly items = signal<ConsultationListItem[]>([]);
  protected readonly loading = signal(true);
  protected readonly problem = signal<ApiProblem | null>(null);

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.problem.set(null);
    try {
      this.items.set(await firstValueFrom(this.api.get<ConsultationListItem[]>('/consultations')));
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.loading.set(false);
    }
  }
}
