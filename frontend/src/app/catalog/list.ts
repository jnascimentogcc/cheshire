import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';

import { Api, toProblem } from '../core/api';
import { Auth } from '../core/auth';
import type { ApiProblem } from '../core/models';
import { StatusBadge } from '../shared/badges';
import { ProblemNotice } from '../shared/problem-notice';
import { KIND_OF_ROUTE, type Kind, ROUTE_OF_KIND, type TableRow } from './models';

/** A catalog list: search and filters on top of a real table. Always ordered by id. */
@Component({
  selector: 'app-catalog-list',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, FormsModule, TranslocoPipe, ProblemNotice, StatusBadge],
  template: `
    <p>
      <a routerLink="/catalog">← {{ 'catalog.title' | transloco }}</a>
    </p>
    <div class="head">
      <h1>{{ 'kind.' + route() | transloco }}</h1>
      @if (auth.isArchitect()) {
        <a [routerLink]="['/catalog', route(), 'new']" class="btn btn-primary">{{
          'list_catalog.new' | transloco
        }}</a>
      }
    </div>

    <form class="filters" role="search" (submit)="$event.preventDefault()">
      <label class="field">
        <span class="label">{{ 'list_catalog.search' | transloco }}</span>
        <input
          class="input"
          type="search"
          name="q"
          [ngModel]="query()"
          (ngModelChange)="query.set($event)"
        />
      </label>
      <label class="field">
        <span class="label">{{ 'list_catalog.status' | transloco }}</span>
        <select
          class="input"
          name="status"
          [ngModel]="status()"
          (ngModelChange)="status.set($event)"
        >
          <option value="">{{ 'list_catalog.any' | transloco }}</option>
          @for (s of statuses; track s) {
            <option [value]="s">{{ 'status.' + s | transloco }}</option>
          }
        </select>
      </label>
      @if (kind() === 'abb') {
        <label class="field">
          <span class="label">{{ 'list_catalog.coverage' | transloco }}</span>
          <select
            class="input"
            name="coverage"
            [ngModel]="coverage()"
            (ngModelChange)="coverage.set($event)"
          >
            <option value="">{{ 'list_catalog.any' | transloco }}</option>
            <option value="gap">{{ 'list_catalog.no_sbb' | transloco }}</option>
            <option value="covered">{{ 'list_catalog.has_sbb' | transloco }}</option>
          </select>
        </label>
      }
      <label class="check">
        <input
          type="checkbox"
          name="used"
          [ngModel]="usedOnly()"
          (ngModelChange)="usedOnly.set($event)"
        />
        {{ 'list_catalog.used' | transloco }}
      </label>
      <label class="check">
        <input
          type="checkbox"
          name="corrected"
          [ngModel]="correctedOnly()"
          (ngModelChange)="correctedOnly.set($event)"
        />
        {{ 'list_catalog.corrected' | transloco }}
      </label>
    </form>

    <app-problem-notice [problem]="problem()" [retryable]="true" (retry)="load()" />

    @if (loading()) {
      <p role="status">
        <span class="spinner" aria-hidden="true"></span> {{ 'common.loading' | transloco }}
      </p>
    } @else if (!problem()) {
      <p class="hint" role="status">
        {{ 'list_catalog.count' | transloco: { n: shown().length, total: rows().length } }}
      </p>
      @if (shown().length === 0) {
        <div class="card">{{ 'list_catalog.none' | transloco }}</div>
      } @else {
        <div class="table-wrap card">
          <table class="data">
            <caption class="sr-only">
              {{
                'kind.' + route() | transloco
              }}
            </caption>
            <thead>
              <tr>
                <th scope="col">{{ 'list_catalog.col_id' | transloco }}</th>
                <th scope="col">{{ 'list_catalog.col_name' | transloco }}</th>
                <th scope="col">{{ 'list_catalog.status' | transloco }}</th>
                <th scope="col">{{ 'list_catalog.col_detail' | transloco }}</th>
                <th scope="col">{{ 'list_catalog.col_used' | transloco }}</th>
                <th scope="col">{{ 'list_catalog.col_corrected' | transloco }}</th>
              </tr>
            </thead>
            <tbody>
              @for (r of shown(); track r.slug) {
                <tr>
                  <th scope="row">
                    <a class="mono" [routerLink]="['/catalog', route(), r.slug]">{{ r.slug }}</a>
                  </th>
                  <td>{{ r.facts['name'] }}</td>
                  <td>
                    @if (r.latest_status; as s) {
                      <app-status-badge [status]="s" />
                    }
                    @if (r.archived) {
                      <span class="badge badge-neutral">{{ 'item.archived' | transloco }}</span>
                    }
                  </td>
                  <td>{{ detail(r) }}</td>
                  <td class="mono">{{ r.consultations }}</td>
                  <td class="mono">{{ r.corrections }}</td>
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
      justify-content: space-between;
      align-items: center;
      gap: var(--space-4);
    }
    h1 {
      margin: 0;
    }
    .filters {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3) var(--space-4);
      align-items: flex-end;
      margin: var(--space-4) 0;
    }
    .check {
      display: inline-flex;
      gap: var(--space-2);
      align-items: center;
      min-height: 36px;
    }
  `,
})
export class CatalogListPage implements OnInit {
  private readonly api = inject(Api);
  private readonly route$ = inject(ActivatedRoute);
  protected readonly auth = inject(Auth);

  protected readonly statuses = ['draft', 'proposed', 'validated'];
  protected readonly route = signal('abbs');
  protected readonly kind = computed<Kind>(() => KIND_OF_ROUTE[this.route()] ?? 'abb');
  protected readonly rows = signal<TableRow[]>([]);
  protected readonly loading = signal(true);
  protected readonly problem = signal<ApiProblem | null>(null);
  protected readonly query = signal('');
  protected readonly status = signal('');
  protected readonly coverage = signal('');
  protected readonly usedOnly = signal(false);
  protected readonly correctedOnly = signal(false);

  protected readonly shown = computed(() => {
    const q = this.query().trim().toLowerCase();
    return this.rows().filter(
      (r) =>
        (!q ||
          r.slug.toLowerCase().includes(q) ||
          String(r.facts['name']).toLowerCase().includes(q)) &&
        (!this.status() || r.latest_status === this.status()) &&
        (!this.coverage() ||
          (this.coverage() === 'gap' ? (r.sbbs ?? 0) === 0 : (r.sbbs ?? 0) > 0)) &&
        (!this.usedOnly() || r.consultations > 0) &&
        (!this.correctedOnly() || r.corrections > 0),
    );
  });

  ngOnInit(): void {
    const route = this.route$.snapshot.paramMap.get('kinds') ?? 'abbs';
    this.route.set(ROUTE_OF_KIND[KIND_OF_ROUTE[route]] ?? 'abbs');
    const query = this.route$.snapshot.queryParamMap;
    this.status.set(query.get('status') ?? '');
    this.coverage.set(query.get('coverage') ?? '');
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.problem.set(null);
    try {
      this.rows.set(
        await firstValueFrom(this.api.get<TableRow[]>(`/catalog/${this.kind()}?detail=true`)),
      );
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.loading.set(false);
    }
  }

  protected detail(r: TableRow): string {
    const f = r.facts;
    switch (this.kind()) {
      case 'abb':
        return `${String(f['domain'])}${f['cross_cutting'] ? ' · cross-cutting' : ''} · ${r.sbbs ?? 0} SBB`;
      case 'sbb':
        return `${String(f['realises'])} · ${String(f['state'])}`;
      case 'rule':
        return `→ ${String(f['activates'])} (${String(f['strength'])})`;
      default:
        return f['values'] !== undefined ? `${String(f['values'])} values` : '';
    }
  }
}

/** The three vocabulary lists in one place (catalog-maintenance.md section 11). */
@Component({
  selector: 'app-catalog-vocabulary',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslocoPipe],
  template: `
    <p>
      <a routerLink="/catalog">← {{ 'catalog.title' | transloco }}</a>
    </p>
    <h1>{{ 'catalog.vocabulary' | transloco }}</h1>
    <p class="hint">{{ 'vocabulary.intro' | transloco }}</p>
    <ul class="links">
      <li>
        <a routerLink="/catalog/attributes" class="btn btn-secondary">{{
          'kind.attributes' | transloco
        }}</a>
      </li>
      <li>
        <a routerLink="/catalog/characteristics" class="btn btn-secondary">{{
          'kind.characteristics' | transloco
        }}</a>
      </li>
      <li>
        <a routerLink="/catalog/lenses" class="btn btn-secondary">{{
          'kind.lenses' | transloco
        }}</a>
      </li>
    </ul>
  `,
  styles: `
    .links {
      list-style: none;
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
      padding: 0;
    }
  `,
})
export class CatalogVocabularyPage {}
