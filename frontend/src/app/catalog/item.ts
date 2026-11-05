import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';

import { Announcer } from '../core/announcer';
import { Api, toProblem } from '../core/api';
import { Auth } from '../core/auth';
import type { ApiProblem, Status } from '../core/models';
import { UserPreferences } from '../core/preferences';
import { StatusBadge } from '../shared/badges';
import type { DecisionSummary } from '../discussions/models';
import { ProblemNotice } from '../shared/problem-notice';
import {
  type Change,
  type Connection,
  type ItemResponse,
  KIND_OF_ROUTE,
  type Kind,
  ROUTE_OF_KIND,
  type Usage,
  type VersionRow,
} from './models';

interface DecisionList {
  decisions: DecisionSummary[];
  open_discussion: number | null;
}

function show(value: unknown): string {
  if (Array.isArray(value)) {
    return value.map(show).join(', ');
  }
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .map(([k, v]) => `${k}: ${show(v)}`)
      .join('; ');
  }
  return String(value);
}

/** One page structure for every entity (catalog-maintenance.md section 4). */
@Component({
  selector: 'app-catalog-item',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, TranslocoPipe, ProblemNotice, StatusBadge],
  template: `
    <p>
      <a [routerLink]="['/catalog', route()]">← {{ 'kind.' + route() | transloco }}</a>
    </p>
    <app-problem-notice [problem]="problem()" [retryable]="true" (retry)="load()" />

    @if (loading()) {
      <p role="status">
        <span class="spinner" aria-hidden="true"></span> {{ 'common.loading' | transloco }}
      </p>
    } @else if (data(); as d) {
      <header class="head">
        <div>
          <h1>{{ title() }}</h1>
          <p class="meta">
            <span class="mono">{{ slug() }}</span>
            @if (effective(); as e) {
              · <app-status-badge [status]="e.status" /> ·
              {{ 'item.version' | transloco: { n: e.number } }}
            }
            @if (latest(); as l) {
              · {{ 'item.last_change' | transloco }}: {{ l.author ?? '—' }},
              {{ l.created_at | date: 'medium' : undefined : prefs.locale() }}
            }
          </p>
        </div>
        @if (auth.isArchitect()) {
          <div class="actions">
            <a [routerLink]="['/catalog', route(), slug(), 'edit']" class="btn btn-primary">{{
              'item.edit' | transloco
            }}</a>
          </div>
        }
      </header>

      @if (pendingNote()) {
        <p class="notice notice-warning" role="status">
          {{ 'item.pending' | transloco: { n: latest()?.number } }}
        </p>
      }

      <section class="card" [attr.aria-label]="'item.content' | transloco">
        <h2>{{ 'item.content' | transloco }}</h2>
        <dl class="fields">
          @for (f of fields(); track f[0]) {
            <dt>{{ f[0] }}</dt>
            <dd>{{ f[1] }}</dd>
          }
        </dl>
        <details>
          <summary>{{ 'item.raw' | transloco }}</summary>
          <pre class="mono raw">{{ raw() }}</pre>
        </details>
      </section>

      <section class="card" [attr.aria-label]="'item.connections' | transloco">
        <h2>{{ 'item.connections' | transloco }}</h2>
        <h3>{{ 'item.uses' | transloco }}</h3>
        @if (uses().length === 0) {
          <p class="hint">{{ 'item.none' | transloco }}</p>
        }
        <ul>
          @for (c of uses(); track c.kind + c.slug + c.ref_kind) {
            <li>
              <a class="mono" [routerLink]="link(c)">{{ c.slug }}</a>
              <span class="hint">({{ c.ref_kind }})</span>
            </li>
          }
        </ul>
        <h3>{{ 'item.used_by' | transloco }}</h3>
        @if (usedBy().length === 0) {
          <p class="hint">{{ 'item.none' | transloco }}</p>
        }
        <ul>
          @for (c of usedBy(); track c.kind + c.slug + c.ref_kind) {
            <li>
              <a class="mono" [routerLink]="link(c)">{{ c.slug }}</a>
              <span class="hint">({{ c.ref_kind }})</span>
            </li>
          }
        </ul>
      </section>

      @if (usage(); as u) {
        <section class="card" [attr.aria-label]="'item.usage' | transloco">
          <h2>{{ 'item.usage' | transloco }}</h2>
          <ul class="usage">
            <li>
              <span class="mono num">{{ u.consultations }}</span>
              {{ 'item.usage_used' | transloco }}
            </li>
            <li>
              <span class="mono num">{{ u.flagged }}</span> {{ 'item.usage_flagged' | transloco }}
            </li>
            <li>
              <span class="mono num">{{ u.corrected }}</span>
              {{ 'item.usage_corrected' | transloco }}
            </li>
            @if (kind() === 'sbb') {
              <li>
                <span class="mono num">{{ u.chosen }}</span> {{ 'item.usage_chosen' | transloco }}
              </li>
            }
          </ul>
          @if (u.last_used) {
            <p class="hint">
              {{ 'item.last_used' | transloco }}:
              {{ u.last_used | date: 'medium' : undefined : prefs.locale() }}
            </p>
          }
        </section>
      }

      <section class="card" [attr.aria-label]="'item.history' | transloco">
        <h2>{{ 'item.history' | transloco }}</h2>
        <app-problem-notice [problem]="actionProblem()" />
        <div class="table-wrap">
          <table class="data">
            <caption class="sr-only">
              {{
                'item.history' | transloco
              }}
            </caption>
            <thead>
              <tr>
                <th scope="col">{{ 'item.col_version' | transloco }}</th>
                <th scope="col">{{ 'list_catalog.status' | transloco }}</th>
                <th scope="col">{{ 'item.col_author' | transloco }}</th>
                <th scope="col">{{ 'item.col_when' | transloco }}</th>
                <th scope="col">{{ 'item.col_note' | transloco }}</th>
                <th scope="col">
                  <span class="sr-only">{{ 'item.col_actions' | transloco }}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              @for (v of d.versions; track v.number) {
                <tr>
                  <th scope="row" class="mono">{{ v.number }}</th>
                  <td>
                    <app-status-badge [status]="v.status" />
                    @if (v.validated_by) {
                      <span class="hint">{{ v.validated_by }}</span>
                    }
                  </td>
                  <td>{{ v.author ?? '—' }}</td>
                  <td class="mono">
                    {{ v.created_at | date: 'medium' : undefined : prefs.locale() }}
                  </td>
                  <td>{{ v.change_note || ('item.origin_' + v.origin | transloco) }}</td>
                  <td class="row-actions">
                    @if (v.number > 1) {
                      <button type="button" class="btn btn-ghost btn-sm" (click)="compare(v)">
                        {{ 'item.show_changes' | transloco }}
                      </button>
                    }
                    @if (auth.isArchitect()) {
                      @if (v.status !== 'validated') {
                        <button type="button" class="btn btn-ghost btn-sm" (click)="validate(v)">
                          {{ 'item.validate' | transloco }}
                        </button>
                      }
                      @if (v.number !== latest()?.number) {
                        <button type="button" class="btn btn-ghost btn-sm" (click)="restore(v)">
                          {{ 'item.restore' | transloco }}
                        </button>
                      }
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
        @if (changes(); as c) {
          <h3>{{ 'item.changes_in' | transloco: { n: c.version } }}</h3>
          @if (c.list.length === 0) {
            <p>{{ 'item.no_changes' | transloco }}</p>
          }
          <ul>
            @for (ch of c.list; track ch.path) {
              <li>
                <span class="badge badge-info">{{ 'impact.label_' + ch.kind | transloco }}</span>
                {{ ch.text }}
              </li>
            }
          </ul>
        }
      </section>

      <section class="card" [attr.aria-label]="'item.discussions' | transloco">
        <h2>{{ 'item.discussions' | transloco }}</h2>
        @if (decisions().decisions.length === 0) {
          <p class="hint">{{ 'item.no_decisions' | transloco }}</p>
        }
        <ul class="decisions">
          @for (x of decisions().decisions; track x.decided_at) {
            <li>
              <span class="badge badge-neutral">{{
                'discussions.outcome_' + x.outcome | transloco
              }}</span>
              {{ 'discussions.decided_by' | transloco: { who: x.decider } }}
              · {{ x.decided_at | date: 'mediumDate' : undefined : prefs.locale() }}
              @if (x.version) {
                · {{ 'discussions.produced' | transloco: { n: x.version } }}
              }
              <p class="rationale">{{ x.rationale }}</p>
              @if (x.discussion_id) {
                <a [routerLink]="['/discussions', x.discussion_id]">{{
                  'item.full_thread' | transloco
                }}</a>
              }
            </li>
          }
        </ul>
        @if (auth.isArchitect()) {
          @if (decisions().open_discussion; as open) {
            <p>
              <a class="btn btn-primary btn-sm" [routerLink]="['/discussions', open]">{{
                'item.open_discussion' | transloco
              }}</a>
            </p>
          } @else {
            <p>
              <a
                class="btn btn-secondary btn-sm"
                routerLink="/discussions/new"
                [queryParams]="{ kind: kind(), slug: slug() }"
                >{{ 'item.start_discussion' | transloco }}</a
              >
            </p>
          }
        }
      </section>

      @if (auth.isArchitect()) {
        <section class="card" [attr.aria-label]="'item.archive' | transloco">
          <h2>{{ 'item.archive' | transloco }}</h2>
          @if (usedBy().length > 0) {
            <p>{{ 'item.archive_blocked' | transloco: { n: usedBy().length } }}</p>
          } @else {
            <p class="hint">{{ 'item.archive_hint' | transloco }}</p>
          }
          <button
            type="button"
            class="btn btn-destructive"
            [disabled]="usedBy().length > 0"
            (click)="archive()"
          >
            {{ 'item.archive_action' | transloco }}
          </button>
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
    .meta {
      margin: 0;
    }
    /* The template drops whitespace between elements, so inline neighbours need a margin:
       the author after the status badge, the reference kind after a connection id. */
    td > span.hint,
    li > span.hint {
      margin-inline-start: var(--space-2);
    }
    section {
      margin-bottom: var(--space-4);
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
    }
    .fields {
      display: grid;
      grid-template-columns: max-content 1fr;
      gap: var(--space-1) var(--space-4);
      margin: 0;
    }
    .fields dt {
      color: var(--text-2);
    }
    .fields dd {
      margin: 0;
      overflow-wrap: anywhere;
    }
    .raw {
      white-space: pre-wrap;
    }
    .usage {
      list-style: none;
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3) var(--space-6);
      padding: 0;
      margin: 0;
    }
    .num {
      font-size: 1.25rem;
      font-weight: 600;
    }
    .row-actions {
      white-space: nowrap;
    }
    .decisions {
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    .rationale {
      margin: var(--space-1) 0;
      white-space: pre-wrap;
    }
  `,
})
export class CatalogItemPage implements OnInit {
  private readonly api = inject(Api);
  private readonly route$ = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly announcer = inject(Announcer);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly auth = inject(Auth);
  protected readonly prefs = inject(UserPreferences);

  protected readonly route = signal('abbs');
  protected readonly kind = computed<Kind>(() => KIND_OF_ROUTE[this.route()] ?? 'abb');
  protected readonly slug = signal('');
  protected readonly data = signal<ItemResponse | null>(null);
  protected readonly connections = signal<{ uses: Connection[]; used_by: Connection[] }>({
    uses: [],
    used_by: [],
  });
  protected readonly usage = signal<Usage | null>(null);
  protected readonly decisions = signal<DecisionList>({ decisions: [], open_discussion: null });
  protected readonly changes = signal<{ version: number; list: Change[] } | null>(null);
  protected readonly loading = signal(true);
  protected readonly problem = signal<ApiProblem | null>(null);
  protected readonly actionProblem = signal<ApiProblem | null>(null);

  protected readonly uses = computed(() => this.connections().uses);
  protected readonly usedBy = computed(() => this.connections().used_by);
  protected readonly latest = computed<VersionRow | null>(() => this.data()?.versions[0] ?? null);
  /** Latest validated, else latest proposed (docs/rule-language.md, Effective catalog). */
  protected readonly effective = computed<VersionRow | null>(() => {
    const versions = this.data()?.versions ?? [];
    return (
      versions.find((v) => v.status === 'validated') ??
      versions.find((v) => v.status === 'proposed') ??
      null
    );
  });
  protected readonly pendingNote = computed(() => {
    const l = this.latest();
    const e = this.effective();
    return !!l && (!e || l.number !== e.number);
  });
  protected readonly title = computed(() => {
    const item = this.data()?.item;
    return String(item?.['name'] ?? item?.['id'] ?? this.slug());
  });
  protected readonly fields = computed<[string, string][]>(() =>
    Object.entries(this.data()?.item ?? {})
      .filter(([key]) => key !== 'id')
      .map(([key, value]) => [key, show(value)]),
  );
  protected readonly raw = computed(() => JSON.stringify(this.data()?.item ?? {}, null, 2));

  ngOnInit(): void {
    // The router reuses this page when only the parameters change (a link from one item to
    // another), so the item is reloaded on every change of parameters, not once.
    this.route$.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const kind = KIND_OF_ROUTE[params.get('kinds') ?? ''];
      if (!kind) {
        void this.router.navigate(['/not-found']);
        return;
      }
      this.route.set(ROUTE_OF_KIND[kind]);
      this.slug.set(params.get('slug') ?? '');
      this.changes.set(null);
      this.actionProblem.set(null);
      void this.load();
    });
  }

  protected link(c: Connection): string[] {
    return ['/catalog', ROUTE_OF_KIND[c.kind], c.slug];
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.problem.set(null);
    const base = `/catalog/${this.kind()}/${this.slug()}`;
    try {
      this.data.set(await firstValueFrom(this.api.get<ItemResponse>(base)));
      this.connections.set(await firstValueFrom(this.api.get(`${base}/connections`)));
      this.usage.set(await firstValueFrom(this.api.get<Usage>(`${base}/usage`)));
      this.decisions.set(await firstValueFrom(this.api.get<DecisionList>(`${base}/decisions`)));
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.loading.set(false);
    }
  }

  protected async compare(v: VersionRow): Promise<void> {
    this.actionProblem.set(null);
    try {
      const out = await firstValueFrom(
        this.api.get<{ changes: Change[] }>(
          `/catalog/${this.kind()}/${this.slug()}/diff?from_version=${v.number - 1}&to_version=${v.number}`,
        ),
      );
      this.changes.set({ version: v.number, list: out.changes });
    } catch (error) {
      this.actionProblem.set(toProblem(error));
    }
  }

  protected async validate(v: VersionRow): Promise<void> {
    await this.setStatus(v, 'validated');
  }

  private async setStatus(v: VersionRow, status: Status): Promise<void> {
    this.actionProblem.set(null);
    try {
      await firstValueFrom(
        this.api.post(`/catalog/${this.kind()}/${this.slug()}/versions/${v.number}/status`, {
          status,
        }),
      );
      this.announcer.say(`Version ${v.number} is ${status}`);
      await this.load();
    } catch (error) {
      this.actionProblem.set(toProblem(error));
    }
  }

  protected async restore(v: VersionRow): Promise<void> {
    this.actionProblem.set(null);
    try {
      await firstValueFrom(
        this.api.post(`/catalog/${this.kind()}/${this.slug()}/versions/${v.number}/restore`),
      );
      this.announcer.say(`Version ${v.number} restored as a new version`);
      await this.load();
    } catch (error) {
      this.actionProblem.set(toProblem(error));
    }
  }

  protected async archive(): Promise<void> {
    this.actionProblem.set(null);
    try {
      await firstValueFrom(this.api.post(`/catalog/${this.kind()}/${this.slug()}/archive`));
      await this.router.navigate(['/catalog', this.route()]);
    } catch (error) {
      this.actionProblem.set(toProblem(error));
    }
  }
}
