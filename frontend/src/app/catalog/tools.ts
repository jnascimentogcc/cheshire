import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';

import { Announcer } from '../core/announcer';
import { Api, toProblem } from '../core/api';
import type { ApiProblem } from '../core/models';
import { UserPreferences } from '../core/preferences';
import { ProblemNotice } from '../shared/problem-notice';
import type { ImportReport, ReferenceCase, StarterPack } from './models';

function download(name: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

/** Pinned consultations: "this is how it should behave" (catalog-maintenance.md section 7). */
@Component({
  selector: 'app-reference-cases',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, TranslocoPipe, ProblemNotice],
  template: `
    <p>
      <a routerLink="/catalog">← {{ 'catalog.title' | transloco }}</a>
    </p>
    <div class="head">
      <div>
        <h1>{{ 'cases.title' | transloco }}</h1>
        <p class="hint">{{ 'cases.intro' | transloco }}</p>
      </div>
      @if (cases().length > 0) {
        <button type="button" class="btn btn-secondary" (click)="export()">
          {{ 'cases.export' | transloco }}
        </button>
      }
    </div>
    <app-problem-notice [problem]="problem()" [retryable]="true" (retry)="load()" />
    @if (!loading() && !problem()) {
      @if (cases().length === 0) {
        <div class="card">{{ 'cases.empty' | transloco }}</div>
      } @else {
        <div class="table-wrap card">
          <table class="data">
            <caption class="sr-only">
              {{
                'cases.title' | transloco
              }}
            </caption>
            <thead>
              <tr>
                <th scope="col">{{ 'cases.col_title' | transloco }}</th>
                <th scope="col">{{ 'cases.col_pinned' | transloco }}</th>
                <th scope="col">
                  <span class="sr-only">{{ 'item.col_actions' | transloco }}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              @for (c of cases(); track c.id) {
                <tr>
                  <th scope="row">
                    <a [routerLink]="['/consult', c.consultation_id]">{{ c.title }}</a>
                  </th>
                  <td>
                    {{ c.pinned_by }} ·
                    {{ c.pinned_at | date: 'medium' : undefined : prefs.locale() }}
                  </td>
                  <td>
                    <button type="button" class="btn btn-ghost btn-sm" (click)="unpin(c)">
                      {{ 'cases.unpin' | transloco }}
                    </button>
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
  `,
})
export class ReferenceCasesPage implements OnInit {
  private readonly api = inject(Api);
  private readonly announcer = inject(Announcer);
  protected readonly prefs = inject(UserPreferences);
  protected readonly cases = signal<ReferenceCase[]>([]);
  protected readonly loading = signal(true);
  protected readonly problem = signal<ApiProblem | null>(null);

  ngOnInit(): void {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.problem.set(null);
    try {
      this.cases.set(await firstValueFrom(this.api.get<ReferenceCase[]>('/reference-cases')));
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.loading.set(false);
    }
  }

  protected async unpin(c: ReferenceCase): Promise<void> {
    try {
      await firstValueFrom(this.api.delete(`/consultations/${c.consultation_id}/pin`));
      this.cases.update((list) => list.filter((x) => x.id !== c.id));
      this.announcer.say(`${c.title} unpinned`);
    } catch (error) {
      this.problem.set(toProblem(error));
    }
  }

  protected export(): void {
    download('reference-cases.json', JSON.stringify(this.cases(), null, 2), 'application/json');
  }
}

/** Export the catalog, import a file or a starter pack with a dry-run diff first. */
@Component({
  selector: 'app-import-export',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslocoPipe, ProblemNotice],
  template: `
    <p>
      <a routerLink="/catalog">← {{ 'catalog.title' | transloco }}</a>
    </p>
    <h1>{{ 'io.title' | transloco }}</h1>
    <app-problem-notice [problem]="problem()" />

    <section class="card">
      <h2>{{ 'io.export' | transloco }}</h2>
      <p class="hint">{{ 'io.export_hint' | transloco }}</p>
      <div class="actions">
        <button type="button" class="btn btn-secondary" (click)="export('yaml')">YAML</button>
        <button type="button" class="btn btn-secondary" (click)="export('json')">JSON</button>
      </div>
    </section>

    <section class="card">
      <h2>{{ 'io.import' | transloco }}</h2>
      <p class="hint">{{ 'io.import_hint' | transloco }}</p>
      <label class="field">
        <span class="label">{{ 'io.file' | transloco }}</span>
        <input
          class="input"
          type="file"
          accept=".yaml,.yml,.json"
          (change)="pick($any($event.target).files)"
        />
      </label>
    </section>

    @if (packs().length > 0) {
      <section class="card">
        <h2>{{ 'io.starter' | transloco }}</h2>
        @for (p of packs(); track p.name) {
          <p>
            <strong>{{ p.title }}</strong> — {{ p.description }}
          </p>
          <p class="hint">{{ 'io.starter_counts' | transloco: p.counts }}</p>
          <button type="button" class="btn btn-secondary" (click)="usePack(p)">
            {{ 'io.preview' | transloco }}
          </button>
        }
      </section>
    }

    @if (report(); as r) {
      <section class="card" [attr.aria-label]="'io.report' | transloco">
        <h2>{{ (applied() ? 'io.applied' : 'io.dry_run') | transloco }}</h2>
        @if (r.issues.length > 0) {
          <div
            class="notice"
            [class.notice-danger]="r.blocking"
            [class.notice-warning]="!r.blocking"
            role="alert"
          >
            <ul>
              @for (i of r.issues; track i) {
                <li>{{ i }}</li>
              }
            </ul>
          </div>
        }
        <ul class="summary">
          <li>{{ 'io.created' | transloco: { n: count(r.created) } }}</li>
          <li>{{ 'io.changed' | transloco: { n: count(r.changed) } }}</li>
          <li>{{ 'io.unchanged' | transloco: { n: count(r.unchanged) } }}</li>
          <li>{{ 'io.absent' | transloco: { n: count(r.absent) } }}</li>
        </ul>
        <p class="hint">{{ 'io.lands_proposed' | transloco }}</p>
        @if (!applied()) {
          <button
            type="button"
            class="btn btn-primary"
            [disabled]="r.blocking || busy()"
            (click)="apply()"
          >
            {{ 'io.apply' | transloco }}
          </button>
          @if (r.blocking) {
            <p class="hint">{{ 'io.blocked' | transloco }}</p>
          }
        } @else {
          <a routerLink="/catalog" class="btn btn-secondary">{{ 'io.done' | transloco }}</a>
        }
      </section>
    }
  `,
  styles: `
    section {
      margin-bottom: var(--space-4);
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      align-items: flex-start;
    }
    h1,
    h2,
    p {
      margin: 0;
    }
    .actions {
      display: flex;
      gap: var(--space-2);
    }
    .summary {
      margin: 0;
      padding-left: var(--space-5);
    }
  `,
})
export class ImportExportPage implements OnInit {
  private readonly api = inject(Api);
  private readonly announcer = inject(Announcer);

  protected readonly problem = signal<ApiProblem | null>(null);
  protected readonly report = signal<ImportReport | null>(null);
  protected readonly applied = signal(false);
  protected readonly busy = signal(false);
  protected readonly packs = signal<StarterPack[]>([]);
  private source:
    | { kind: 'file'; content: string; format: 'yaml' | 'json'; name: string }
    | { kind: 'pack'; name: string }
    | null = null;

  ngOnInit(): void {
    void firstValueFrom(this.api.get<StarterPack[]>('/catalog/starter-packs'))
      .then((p) => this.packs.set(p))
      .catch(() => this.packs.set([]));
  }

  protected count(group: Record<string, string[]>): number {
    return Object.values(group).reduce((n, ids) => n + ids.length, 0);
  }

  protected async export(format: 'yaml' | 'json'): Promise<void> {
    this.problem.set(null);
    try {
      const response = await fetch(`/api/catalog/export?format=${format}`, {
        credentials: 'same-origin',
      });
      if (!response.ok) {
        throw { status: response.status, code: `http_${response.status}`, message: '' };
      }
      download(
        `catalog.${format}`,
        await response.text(),
        format === 'json' ? 'application/json' : 'application/yaml',
      );
    } catch (error) {
      this.problem.set(toProblem(error));
    }
  }

  protected async pick(files: FileList | null): Promise<void> {
    const file = files?.[0];
    if (!file) {
      return;
    }
    const content = await file.text();
    this.source = {
      kind: 'file',
      content,
      format: file.name.endsWith('.json') ? 'json' : 'yaml',
      name: file.name,
    };
    await this.run(true);
  }

  protected async usePack(pack: StarterPack): Promise<void> {
    this.source = { kind: 'pack', name: pack.name };
    await this.run(true);
  }

  protected async apply(): Promise<void> {
    await this.run(false);
  }

  private async run(dryRun: boolean): Promise<void> {
    const source = this.source;
    if (!source) {
      return;
    }
    this.busy.set(true);
    this.problem.set(null);
    try {
      const report =
        source.kind === 'pack'
          ? await firstValueFrom(
              this.api.post<ImportReport>(`/catalog/starter-packs/${source.name}/import`, {
                dry_run: dryRun,
              }),
            )
          : await firstValueFrom(
              this.api.post<ImportReport>('/catalog/import', {
                format: source.format,
                content: source.content,
                filename: source.name,
                dry_run: dryRun,
              }),
            );
      this.report.set(report);
      this.applied.set(!dryRun);
      this.announcer.say(dryRun ? 'Preview ready' : 'Import applied');
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.busy.set(false);
    }
  }
}
