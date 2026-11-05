import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';

import { Announcer } from '../core/announcer';
import { Api, toProblem } from '../core/api';
import { Auth } from '../core/auth';
import type { ApiProblem } from '../core/models';
import { UserPreferences } from '../core/preferences';
import { ProblemNotice } from '../shared/problem-notice';
import { openTarget } from './logic';
import type { Health, WorkItem, WorkKind } from './models';

const KIND_ORDER: WorkKind[] = [
  'gap',
  'unrecognised',
  'feedback',
  'draft_review',
  'validation_backlog',
  'validator_finding',
];

/** Catalog home: the health of the catalog and the work queue (catalog-maintenance.md 3). */
@Component({
  selector: 'app-catalog-home',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, FormsModule, TranslocoPipe, ProblemNotice],
  template: `
    <div class="head">
      <div>
        <h1>{{ 'catalog.title' | transloco }}</h1>
        <p class="hint">{{ 'catalog.intro' | transloco }}</p>
      </div>
      <nav [attr.aria-label]="'catalog.sections' | transloco" class="sections">
        <a routerLink="/catalog/abbs" class="btn btn-secondary btn-sm">{{
          'kind.abbs' | transloco
        }}</a>
        <a routerLink="/catalog/sbbs" class="btn btn-secondary btn-sm">{{
          'kind.sbbs' | transloco
        }}</a>
        <a routerLink="/catalog/rules" class="btn btn-secondary btn-sm">{{
          'kind.rules' | transloco
        }}</a>
        <a routerLink="/catalog/vocabulary" class="btn btn-secondary btn-sm">{{
          'catalog.vocabulary' | transloco
        }}</a>
        @if (auth.isArchitect()) {
          <a routerLink="/catalog/reference-cases" class="btn btn-secondary btn-sm">{{
            'catalog.reference_cases' | transloco
          }}</a>
          <a routerLink="/catalog/import-export" class="btn btn-secondary btn-sm">{{
            'catalog.import_export' | transloco
          }}</a>
          <a routerLink="/catalog/interview" class="btn btn-secondary btn-sm">{{
            'catalog.interview' | transloco
          }}</a>
        }
      </nav>
    </div>

    <app-problem-notice [problem]="problem()" [retryable]="true" (retry)="load()" />

    @if (loading()) {
      <p role="status">
        <span class="spinner" aria-hidden="true"></span> {{ 'common.loading' | transloco }}
      </p>
    } @else if (health(); as h) {
      @if (h.empty) {
        <div class="card empty">
          <h2>{{ 'catalog.empty_title' | transloco }}</h2>
          <p>{{ 'catalog.empty_body' | transloco }}</p>
          @if (auth.isArchitect()) {
            <div class="actions">
              <a routerLink="/catalog/import-export" class="btn btn-primary">{{
                'catalog.empty_starter' | transloco
              }}</a>
              <a routerLink="/catalog/abbs/new" class="btn btn-secondary">{{
                'catalog.empty_first' | transloco
              }}</a>
              <a routerLink="/catalog/interview" class="btn btn-secondary">{{
                'catalog.empty_interview' | transloco
              }}</a>
            </div>
          }
        </div>
      } @else {
        <section [attr.aria-label]="'health.title' | transloco">
          <h2>{{ 'health.title' | transloco }}</h2>
          <ul class="health">
            @for (s of statuses; track s) {
              <li class="card">
                <a [routerLink]="['/catalog/abbs']" [queryParams]="{ status: s }">
                  <span class="num mono">{{ h.items_by_status[s] }}</span>
                  {{ 'health.' + s | transloco }}
                </a>
              </li>
            }
            <li class="card">
              <a routerLink="/catalog/abbs" [queryParams]="{ coverage: 'gap' }">
                <span class="num mono">{{ h.abbs_without_sbb.length }}</span>
                {{ 'health.gaps' | transloco }}
              </a>
            </li>
            <li class="card">
              <span class="num mono">{{ h.validator_errors }}</span>
              {{ 'health.errors' | transloco }}
            </li>
            <li class="card">
              <span class="num mono">{{ h.validator_warnings }}</span>
              {{ 'health.warnings' | transloco }}
            </li>
          </ul>
        </section>
      }

      @if (auth.isArchitect()) {
        <section [attr.aria-label]="'queue.title' | transloco">
          <h2>{{ 'queue.title' | transloco }}</h2>
          <app-problem-notice [problem]="actionProblem()" />
          @if (work().length === 0) {
            <p class="card">{{ 'queue.empty' | transloco }}</p>
          }
          @for (kind of kinds; track kind) {
            @if (byKind(kind).length > 0) {
              <h3>{{ 'queue_kind.' + kind | transloco }}</h3>
              <ul class="queue">
                @for (w of byKind(kind); track w.id) {
                  <li class="card item">
                    <div class="what">
                      <p class="text">{{ describe(w) }}</p>
                      @if (w.sessions > 0) {
                        <p class="hint">{{ 'queue.sessions' | transloco: { n: w.sessions } }}</p>
                      }
                      @if (w.status === 'claimed') {
                        <p class="hint">
                          {{ 'queue.claimed_by' | transloco: { who: w.claimed_by } }}
                          @if (w.claim_expires_at) {
                            · {{ 'queue.until' | transloco }}
                            {{
                              w.claim_expires_at | date: 'mediumDate' : undefined : prefs.locale()
                            }}
                          }
                        </p>
                        @if (w.expiring_soon && w.claimed_by_me) {
                          <p class="notice notice-warning" role="status">
                            {{ 'queue.expiring' | transloco }}
                          </p>
                        }
                      }
                    </div>
                    <div class="actions">
                      @if (w.status === 'open') {
                        <button type="button" class="btn btn-primary btn-sm" (click)="claim(w)">
                          {{ 'queue.claim' | transloco }}
                        </button>
                      }
                      @if (w.status === 'claimed' && w.claimed_by_me) {
                        <button
                          type="button"
                          class="btn btn-secondary btn-sm"
                          (click)="act(w, 'renew')"
                        >
                          {{ 'queue.renew' | transloco }}
                        </button>
                        <button
                          type="button"
                          class="btn btn-secondary btn-sm"
                          (click)="act(w, 'release')"
                        >
                          {{ 'queue.release' | transloco }}
                        </button>
                      }
                      @if (target(w); as t) {
                        <a
                          class="btn btn-secondary btn-sm"
                          [routerLink]="t.link"
                          [queryParams]="t.query"
                          >{{ 'queue.open' | transloco }}</a
                        >
                      }
                      @if (discussQuery(w); as q) {
                        <a
                          class="btn btn-secondary btn-sm"
                          routerLink="/discussions/new"
                          [queryParams]="q"
                          >{{ 'queue.discuss' | transloco }}</a
                        >
                      }
                      <button type="button" class="btn btn-ghost btn-sm" (click)="startDismiss(w)">
                        {{ 'queue.dismiss' | transloco }}
                      </button>
                    </div>
                    @if (dismissing() === w.id) {
                      <form class="dismiss" (submit)="$event.preventDefault(); dismiss(w)">
                        <label class="field">
                          <span class="label">{{ 'queue.reason' | transloco }}</span>
                          <input
                            class="input"
                            name="reason"
                            [ngModel]="reason()"
                            (ngModelChange)="reason.set($event)"
                            required
                          />
                        </label>
                        <button
                          type="submit"
                          class="btn btn-primary btn-sm"
                          [disabled]="!reason().trim()"
                        >
                          {{ 'queue.confirm_dismiss' | transloco }}
                        </button>
                      </form>
                    }
                  </li>
                }
              </ul>
            }
          }
        </section>
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
    h2,
    h3,
    .head p {
      margin: 0;
    }
    h2,
    h3 {
      margin-top: var(--space-5);
      margin-bottom: var(--space-2);
    }
    .sections,
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: flex-start;
    }
    .health,
    .queue {
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: var(--space-3);
    }
    .health {
      grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
    }
    .num {
      font-size: 1.5rem;
      font-weight: 600;
      margin-right: var(--space-1);
    }
    .item {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: var(--space-3);
    }
    .what {
      flex: 1 1 20rem;
      min-width: 0;
    }
    .what p {
      margin: 0;
    }
    .text {
      font-weight: 500;
      overflow-wrap: anywhere;
    }
    .dismiss {
      width: 100%;
      display: flex;
      gap: var(--space-3);
      align-items: flex-end;
    }
    .empty {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      align-items: flex-start;
    }
    .empty h2,
    .empty p {
      margin: 0;
    }
  `,
})
export class CatalogHomePage implements OnInit {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly announcer = inject(Announcer);
  protected readonly auth = inject(Auth);
  protected readonly prefs = inject(UserPreferences);

  protected readonly kinds = KIND_ORDER;
  protected readonly statuses = ['draft', 'proposed', 'validated'] as const;
  protected readonly health = signal<Health | null>(null);
  protected readonly work = signal<WorkItem[]>([]);
  protected readonly loading = signal(true);
  protected readonly problem = signal<ApiProblem | null>(null);
  protected readonly actionProblem = signal<ApiProblem | null>(null);
  protected readonly dismissing = signal<number | null>(null);
  protected readonly reason = signal('');

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.problem.set(null);
    try {
      this.health.set(await firstValueFrom(this.api.get<Health>('/catalog/health')));
      if (this.auth.isArchitect()) {
        this.work.set(await firstValueFrom(this.api.get<WorkItem[]>('/catalog/work')));
      }
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.loading.set(false);
    }
  }

  protected byKind(kind: WorkKind): WorkItem[] {
    return this.work().filter((w) => w.kind === kind);
  }

  protected target(w: WorkItem) {
    return openTarget(w);
  }

  protected describe(w: WorkItem): string {
    const p = w.payload;
    switch (w.kind) {
      case 'gap':
        return String(p['abb']);
      case 'unrecognised':
        return String(p['requirement']);
      case 'feedback':
        return `${String(p['text'])}${p['abb'] ? ` (${String(p['abb'])})` : ''}`;
      case 'draft_review':
      case 'validation_backlog':
        return `${String(p['item_kind'])} ${String(p['item'])} · v${String(p['version'])}`;
      default:
        return `${String(p['subject'])}: ${String(p['message'])}`;
    }
  }

  private replace(updated: WorkItem): void {
    this.work.update((list) => list.map((w) => (w.id === updated.id ? updated : w)));
  }

  /** A claimed gap or feedback entry can become a discussion; the claimer will be its decider. */
  protected discussQuery(w: WorkItem): Record<string, string | number> | null {
    if (w.status !== 'claimed' || !w.claimed_by_me || !w.subject || !w.subject_kind) {
      return null;
    }
    return w.kind === 'gap' || w.kind === 'feedback'
      ? { kind: w.subject_kind, slug: w.subject, work: w.id }
      : null;
  }

  protected async claim(w: WorkItem): Promise<void> {
    await this.act(w, 'claim');
    const t = openTarget(w);
    if (t && !this.actionProblem()) {
      await this.router.navigate(t.link, { queryParams: t.query });
    }
  }

  protected async act(w: WorkItem, action: 'claim' | 'renew' | 'release'): Promise<void> {
    this.actionProblem.set(null);
    try {
      this.replace(
        await firstValueFrom(this.api.post<WorkItem>(`/catalog/work/${w.id}/${action}`)),
      );
      this.announcer.say(action);
    } catch (error) {
      this.actionProblem.set(toProblem(error));
      await this.load();
    }
  }

  protected startDismiss(w: WorkItem): void {
    this.reason.set('');
    this.dismissing.set(this.dismissing() === w.id ? null : w.id);
  }

  protected async dismiss(w: WorkItem): Promise<void> {
    this.actionProblem.set(null);
    try {
      await firstValueFrom(
        this.api.post(`/catalog/work/${w.id}/dismiss`, { reason: this.reason() }),
      );
      this.work.update((list) => list.filter((x) => x.id !== w.id));
      this.dismissing.set(null);
    } catch (error) {
      this.actionProblem.set(toProblem(error));
    }
  }
}
