import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';

import { Api, toProblem } from '../core/api';
import { Announcer } from '../core/announcer';
import type { ApiProblem, Status } from '../core/models';
import { ProblemNotice } from '../shared/problem-notice';
import { ConditionBuilder } from './condition-builder';
import {
  type ConditionRows,
  conditionProblems,
  fromRows,
  referencedIn,
  toRows,
  validSlug,
} from './logic';
import {
  type Change,
  type Impact,
  type ItemResponse,
  KIND_OF_ROUTE,
  type Kind,
  ROUTE_OF_KIND,
  type RawCondition,
  type RawItem,
  type TryResult,
  type Vocabulary,
} from './models';

const EMPTY: ConditionRows = { tests: [], abbs: [], except: null };
const STATES = ['recommended', 'accepted', 'deprecating', 'prohibited'];
const COND_FIELD: Partial<Record<Kind, string[]>> = {
  sbb: ['applies_when', 'not_applies_when'],
  rule: ['when'],
};

interface Stale {
  latest_version: number;
  latest_item: RawItem;
  changes: Change[];
}

/** Structured editor for ABBs, SBBs and rules; the JSON view is the advanced path for all kinds. */
@Component({
  selector: 'app-catalog-edit',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, RouterLink, TranslocoPipe, ProblemNotice, ConditionBuilder],
  template: `
    <p>
      <a [routerLink]="back()">← {{ 'edit.back' | transloco }}</a>
    </p>
    <h1>
      @if (isNew()) {
        {{ 'edit.title_new' | transloco: { kind: ('kind.' + kind() | transloco) } }}
      } @else {
        {{ 'edit.title' | transloco: { id: slug() } }}
      }
    </h1>

    <app-problem-notice [problem]="problem()" [retryable]="true" (retry)="load()" />

    @if (stale(); as s) {
      <div class="notice notice-warning" role="alert">
        <div>
          <p class="strong">{{ 'edit.stale' | transloco: { version: s.latest_version } }}</p>
          <ul>
            @for (c of s.changes; track c.path) {
              <li>{{ c.text }}</li>
            }
          </ul>
          <div class="actions">
            <button type="button" class="btn btn-secondary btn-sm" (click)="keepMine(s)">
              {{ 'edit.keep_mine' | transloco }}
            </button>
            <button type="button" class="btn btn-secondary btn-sm" (click)="takeTheirs(s)">
              {{ 'edit.take_theirs' | transloco }}
            </button>
          </div>
        </div>
      </div>
    }

    @if (loading()) {
      <p role="status">
        <span class="spinner" aria-hidden="true"></span> {{ 'common.loading' | transloco }}
      </p>
    } @else if (vocab(); as v) {
      <form class="form" (submit)="$event.preventDefault()">
        @if (!advanced()) {
          @if (isNew()) {
            <label class="field">
              <span class="label">{{ 'edit.id' | transloco }}</span>
              <input
                class="input mono"
                name="id"
                [ngModel]="slug()"
                (ngModelChange)="slug.set($event)"
                [attr.aria-invalid]="slug() && !slugOk() ? 'true' : null"
              />
              <span class="hint">{{ 'edit.id_hint' | transloco }}</span>
              @if (slug() && !slugOk()) {
                <span class="error-text">{{ 'edit.id_invalid' | transloco }}</span>
              }
            </label>
          }

          @if (kind() === 'abb') {
            <label class="field">
              <span class="label">{{ 'edit.name' | transloco }}</span>
              <input
                class="input"
                name="name"
                [ngModel]="text('name')"
                (ngModelChange)="set('name', $event)"
              />
            </label>
            <label class="field">
              <span class="label">{{ 'edit.domain' | transloco }}</span>
              <input
                class="input"
                name="domain"
                [ngModel]="text('domain')"
                (ngModelChange)="set('domain', $event)"
              />
            </label>
            <label class="check">
              <input
                type="checkbox"
                name="cc"
                [checked]="raw()['cross_cutting'] === true"
                (change)="set('cross_cutting', $any($event.target).checked)"
              />
              {{ 'edit.cross_cutting' | transloco }}
            </label>
            <label class="field">
              <span class="label">{{ 'edit.description' | transloco }}</span>
              <textarea
                class="input"
                rows="3"
                name="description"
                [ngModel]="text('description')"
                (ngModelChange)="set('description', $event)"
              ></textarea>
            </label>
            <label class="field">
              <span class="label">{{ 'edit.recognition' | transloco }}</span>
              <textarea
                class="input"
                rows="3"
                name="recognition"
                [ngModel]="lines('recognition')"
                (ngModelChange)="setLines('recognition', $event)"
              ></textarea>
              <span class="hint">{{ 'edit.one_per_line' | transloco }}</span>
            </label>
            <label class="field">
              <span class="label">{{ 'edit.does_not_apply_when' | transloco }}</span>
              <textarea
                class="input"
                rows="2"
                name="dnaw"
                [ngModel]="text('does_not_apply_when')"
                (ngModelChange)="set('does_not_apply_when', $event)"
              ></textarea>
            </label>
          }

          @if (kind() === 'sbb') {
            <label class="field">
              <span class="label">{{ 'edit.name' | transloco }}</span>
              <input
                class="input"
                name="name"
                [ngModel]="text('name')"
                (ngModelChange)="set('name', $event)"
              />
            </label>
            <label class="field">
              <span class="label">{{ 'edit.realises' | transloco }}</span>
              <select
                class="input"
                name="realises"
                [ngModel]="text('realises')"
                (ngModelChange)="set('realises', $event)"
              >
                <option value="">{{ 'builder.choose' | transloco }}</option>
                @for (a of v.abbs; track a.id) {
                  <option [value]="a.id">{{ a.id }} — {{ a.name }}</option>
                }
              </select>
            </label>
            <label class="field">
              <span class="label">{{ 'edit.state' | transloco }}</span>
              <select
                class="input"
                name="state"
                [ngModel]="text('state')"
                (ngModelChange)="set('state', $event)"
              >
                <option value="">{{ 'builder.choose' | transloco }}</option>
                @for (s of states; track s) {
                  <option [value]="s">{{ 'sbb_state.' + s | transloco }}</option>
                }
              </select>
            </label>
            <h2>{{ 'edit.applies_when' | transloco }}</h2>
            <app-condition-builder
              [rows]="conds()['applies_when']"
              [vocab]="v"
              (rowsChange)="setCond('applies_when', $event)"
            />
            <h2>{{ 'edit.not_applies_when' | transloco }}</h2>
            <app-condition-builder
              [rows]="conds()['not_applies_when']"
              [vocab]="v"
              (rowsChange)="setCond('not_applies_when', $event)"
            />
            @for (f of sbbTexts; track f) {
              <label class="field">
                <span class="label">{{ 'edit.' + f | transloco }}</span>
                <textarea
                  class="input"
                  rows="2"
                  [name]="f"
                  [ngModel]="text(f)"
                  (ngModelChange)="set(f, $event)"
                ></textarea>
              </label>
            }
            <label class="field">
              <span class="label">{{ 'edit.owner' | transloco }}</span>
              <input
                class="input"
                name="owner"
                [ngModel]="text('owner')"
                (ngModelChange)="set('owner', $event)"
              />
            </label>
            <fieldset class="chars">
              <legend class="label">{{ 'edit.characteristics' | transloco }}</legend>
              @for (c of v.characteristics; track c.id) {
                <label class="field">
                  <span class="label">{{ c.id }}</span>
                  <select
                    class="input"
                    [name]="'char-' + c.id"
                    [ngModel]="characteristic(c.id)"
                    (ngModelChange)="setCharacteristic(c.id, $event)"
                  >
                    <option value="">{{ 'edit.not_declared' | transloco }}</option>
                    @for (val of c.values; track val) {
                      <option [value]="val">{{ val }}</option>
                    }
                  </select>
                </label>
              }
            </fieldset>
          }

          @if (kind() === 'rule') {
            <h2>{{ 'edit.when' | transloco }}</h2>
            <app-condition-builder
              [rows]="conds()['when']"
              [vocab]="v"
              (rowsChange)="setCond('when', $event)"
            />
            <label class="field">
              <span class="label">{{ 'edit.activates' | transloco }}</span>
              <select
                class="input"
                name="activates"
                [ngModel]="text('activates')"
                (ngModelChange)="set('activates', $event)"
              >
                <option value="">{{ 'builder.choose' | transloco }}</option>
                @for (a of v.abbs; track a.id) {
                  <option [value]="a.id">{{ a.id }} — {{ a.name }}</option>
                }
              </select>
            </label>
            <label class="field">
              <span class="label">{{ 'edit.strength' | transloco }}</span>
              <select
                class="input"
                name="strength"
                [ngModel]="text('strength')"
                (ngModelChange)="set('strength', $event)"
              >
                <option value="">{{ 'builder.choose' | transloco }}</option>
                <option value="requires">{{ 'abbs.strength_requires' | transloco }}</option>
                <option value="considers">{{ 'abbs.strength_considers' | transloco }}</option>
              </select>
            </label>
            <label class="field">
              <span class="label">{{ 'edit.reason' | transloco }}</span>
              <textarea
                class="input"
                rows="2"
                name="reason"
                [ngModel]="text('reason')"
                (ngModelChange)="set('reason', $event)"
              ></textarea>
            </label>
          }
        }

        @if (advanced() || !structured()) {
          <label class="field">
            <span class="label">{{ 'edit.json' | transloco }}</span>
            <textarea
              class="input mono"
              rows="16"
              name="json"
              [ngModel]="json()"
              (ngModelChange)="json.set($event)"
            ></textarea>
            <span class="hint">{{ 'edit.json_hint' | transloco }}</span>
            @if (jsonError()) {
              <span class="error-text">{{ jsonError() }}</span>
            }
          </label>
          @if (advanced()) {
            <button type="button" class="btn btn-secondary btn-sm" (click)="applyJson()">
              {{ 'edit.apply_json' | transloco }}
            </button>
          }
        }
        @if (structured()) {
          <button type="button" class="btn btn-ghost btn-sm" (click)="toggleAdvanced()">
            {{ (advanced() ? 'edit.back_to_form' : 'edit.advanced') | transloco }}
          </button>
        }

        @if (kind() === 'rule') {
          <section class="card try" [attr.aria-label]="'try.title' | transloco">
            <h2>{{ 'try.title' | transloco }}</h2>
            <p class="hint">{{ 'try.intro' | transloco }}</p>
            @for (attr of referenced().attributes; track attr) {
              <label class="field">
                <span class="label">{{ attr }}</span>
                <select
                  class="input"
                  [name]="'try-' + attr"
                  [ngModel]="tryValues()[attr] ?? 'unknown'"
                  (ngModelChange)="setTry(attr, $event)"
                >
                  <option value="unknown">{{ 'try.unknown' | transloco }}</option>
                  @for (val of valuesOf(attr); track val) {
                    <option [value]="val">{{ val }}</option>
                  }
                </select>
              </label>
            }
            @if (referenced().abbs.length > 0) {
              <fieldset class="values">
                <legend class="label">{{ 'try.present' | transloco }}</legend>
                @for (abb of referenced().abbs; track abb) {
                  <label class="check">
                    <input
                      type="checkbox"
                      [checked]="tryAbbs().includes(abb)"
                      (change)="toggleTryAbb(abb, $any($event.target).checked)"
                    />
                    {{ abb }}
                  </label>
                }
              </fieldset>
            }
            <button type="button" class="btn btn-secondary" (click)="runTry()">
              {{ 'try.run' | transloco }}
            </button>
            @if (tried(); as r) {
              <p class="strong" role="status">
                {{ 'try.result' | transloco: { outcome: ('try.' + r.outcome | transloco) } }}
              </p>
              <pre class="mono trace">{{ r.text.join('\\n') }}</pre>
            }
          </section>
        }

        <section class="card save" [attr.aria-label]="'edit.save_section' | transloco">
          <label class="field">
            <span class="label">{{ 'edit.change_note' | transloco }}</span>
            <input
              class="input"
              name="note"
              [ngModel]="note()"
              (ngModelChange)="note.set($event)"
              maxlength="500"
            />
          </label>
          @if (blockers().length > 0) {
            <ul class="error-text" role="alert">
              @for (b of blockers(); track b) {
                <li>{{ b }}</li>
              }
            </ul>
          }
          <div class="actions">
            <button type="button" class="btn btn-secondary" (click)="preview()" [disabled]="busy()">
              {{ 'impact.preview' | transloco }}
            </button>
            <button
              type="button"
              class="btn btn-primary"
              (click)="save('proposed')"
              [disabled]="busy() || blockers().length > 0"
            >
              {{ 'edit.save_proposed' | transloco }}
            </button>
            <button
              type="button"
              class="btn btn-secondary"
              (click)="save('draft')"
              [disabled]="busy() || blockers().length > 0"
            >
              {{ 'edit.save_draft' | transloco }}
            </button>
          </div>
          @if (blockers().length > 0) {
            <p class="hint">{{ 'edit.save_disabled' | transloco }}</p>
          }
        </section>

        @if (impact(); as i) {
          <section class="card" [attr.aria-label]="'impact.title' | transloco">
            <h2>{{ 'impact.title' | transloco }}</h2>
            @if (!i.effective_now) {
              <p class="notice notice-warning">{{ 'impact.not_effective' | transloco }}</p>
            }
            <p>{{ 'impact.dependents' | transloco: { n: i.dependents.length } }}</p>
            @for (issue of i.new_issues; track issue) {
              <p class="error-text">{{ issue }}</p>
            }
            <h3>{{ 'impact.cases' | transloco }}</h3>
            @if (i.reference_cases.length === 0) {
              <p class="hint">{{ 'impact.no_cases' | transloco }}</p>
            }
            @for (c of i.reference_cases; track c.id) {
              <h4>{{ c.title }}</h4>
              @if (c.already_differs) {
                <p class="hint">{{ 'impact.already_differs' | transloco }}</p>
              }
              @if (c.error) {
                <p class="error-text">{{ c.error }}</p>
              } @else if (c.differences.length === 0) {
                <p>{{ 'impact.same' | transloco }}</p>
              } @else {
                <ul>
                  @for (d of c.differences; track d.text) {
                    <li>
                      <span class="badge badge-info">{{
                        'impact.label_' + d.label | transloco
                      }}</span>
                      {{ d.text }}
                    </li>
                  }
                </ul>
              }
            }
            <h3>{{ 'impact.recent' | transloco }}</h3>
            @for (c of i.recent_consultations; track c.consultation_id) {
              <h4>
                <a [routerLink]="['/consult', c.consultation_id]">{{ c.title }}</a>
              </h4>
              @if (c.error) {
                <p class="error-text">{{ c.error }}</p>
              } @else if (c.differences.length === 0) {
                <p>{{ 'impact.same' | transloco }}</p>
              } @else {
                <ul>
                  @for (d of c.differences; track d.text) {
                    <li>
                      <span class="badge badge-info">{{
                        'impact.label_' + d.label | transloco
                      }}</span>
                      {{ d.text }}
                    </li>
                  }
                </ul>
              }
            }
          </section>
        }

        @if (warnings().length > 0) {
          <div class="notice notice-warning" role="status">
            <ul>
              @for (w of warnings(); track w) {
                <li>{{ w }}</li>
              }
            </ul>
          </div>
        }
      </form>
    }
  `,
  styles: `
    .form {
      display: flex;
      flex-direction: column;
      gap: var(--space-4);
      max-width: 52rem;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
    }
    .check {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
    }
    .values,
    .chars {
      border: 0;
      padding: 0;
      margin: 0;
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2) var(--space-4);
    }
    .strong {
      font-weight: 600;
      margin: 0 0 var(--space-2);
    }
    .trace {
      white-space: pre-wrap;
      margin: 0;
    }
    .try,
    .save {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    h1,
    h2,
    h3,
    h4 {
      margin: 0;
    }
  `,
})
export class CatalogEditPage implements OnInit {
  private readonly api = inject(Api);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly announcer = inject(Announcer);

  protected readonly states = STATES;
  protected readonly sbbTexts = [
    'reason_not_applies',
    'reason_prohibited',
    'when_to_choose',
    'limitations',
  ];

  protected readonly kind = signal<Kind>('abb');
  protected readonly slug = signal('');
  protected readonly isNew = signal(false);
  protected readonly raw = signal<Record<string, unknown>>({});
  protected readonly conds = signal<Record<string, ConditionRows>>({});
  protected readonly vocab = signal<Vocabulary | null>(null);
  protected readonly baseVersion = signal<number | null>(null);
  protected readonly note = signal('');
  protected readonly advanced = signal(false);
  protected readonly json = signal('');
  protected readonly jsonError = signal('');
  protected readonly loading = signal(true);
  protected readonly busy = signal(false);
  protected readonly problem = signal<ApiProblem | null>(null);
  protected readonly stale = signal<Stale | null>(null);
  protected readonly impact = signal<Impact | null>(null);
  protected readonly warnings = signal<string[]>([]);
  protected readonly tryValues = signal<Record<string, string>>({});
  protected readonly tryAbbs = signal<string[]>([]);
  protected readonly tried = signal<TryResult | null>(null);

  protected readonly structured = computed(() => ['abb', 'sbb', 'rule'].includes(this.kind()));
  protected readonly slugOk = computed(() => validSlug(this.slug()));
  protected readonly back = computed(() =>
    this.isNew()
      ? ['/catalog', ROUTE_OF_KIND[this.kind()]]
      : ['/catalog', ROUTE_OF_KIND[this.kind()], this.slug()],
  );
  protected readonly referenced = computed(() => {
    const rows = this.conds()['when'];
    return rows ? referencedIn(rows) : { attributes: [], abbs: [] };
  });
  /** What prevents saving, in words next to the button (ui-spec 7). */
  protected readonly blockers = computed(() => {
    const out: string[] = [];
    const v = this.vocab();
    if (this.isNew() && !this.slugOk()) {
      out.push(this.slug() ? 'The id is not valid.' : 'Enter an id.');
    }
    if (v && !this.advanced()) {
      for (const [name, rows] of Object.entries(this.conds())) {
        out.push(...conditionProblems(rows, v).map((p) => `${name}: ${p}`));
      }
      const required =
        (
          {
            abb: ['name', 'domain'],
            sbb: ['name', 'realises', 'state'],
            rule: ['activates', 'strength'],
          } as Record<string, string[]>
        )[this.kind()] ?? [];
      for (const f of required) {
        if (!this.text(f)) {
          out.push(`${f.replace('_', ' ')} is required.`);
        }
      }
    }
    return out;
  });

  ngOnInit(): void {
    const params = this.route.snapshot.paramMap;
    const kind = KIND_OF_ROUTE[params.get('kinds') ?? ''];
    if (!kind) {
      void this.router.navigate(['/not-found']);
      return;
    }
    this.kind.set(kind);
    const slug = params.get('slug');
    this.isNew.set(slug === null || slug === 'new');
    this.slug.set(this.isNew() ? '' : (slug as string));
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.problem.set(null);
    try {
      const doc = await firstValueFrom(
        this.api.get<Record<string, unknown>>('/catalog/export?format=json&include_drafts=true'),
      );
      this.vocab.set({
        attributes: (doc['attributes'] as Vocabulary['attributes']) ?? [],
        abbs: (doc['abbs'] as Vocabulary['abbs']) ?? [],
        characteristics: (doc['characteristics'] as Vocabulary['characteristics']) ?? [],
      });
      if (this.isNew()) {
        const prefill: Record<string, unknown> = {};
        const realises = this.route.snapshot.queryParamMap.get('realises');
        if (realises && this.kind() === 'sbb') {
          prefill['realises'] = realises;
        }
        this.adopt(prefill);
      } else {
        const first = await firstValueFrom(
          this.api.get<ItemResponse>(`/catalog/${this.kind()}/${this.slug()}`),
        );
        const latest = first.versions[0].number;
        const doc2 = await firstValueFrom(
          this.api.get<ItemResponse>(`/catalog/${this.kind()}/${this.slug()}?version=${latest}`),
        );
        this.baseVersion.set(latest);
        this.adopt(doc2.item);
      }
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.loading.set(false);
    }
  }

  private adopt(item: Record<string, unknown>): void {
    const { status: _status, ...rest } = item;
    const conds: Record<string, ConditionRows> = {};
    for (const f of COND_FIELD[this.kind()] ?? []) {
      conds[f] = toRows(rest[f] as RawCondition | undefined);
      delete rest[f];
    }
    this.raw.set(rest);
    this.conds.set(conds);
    this.json.set(JSON.stringify(this.assemble(), null, 2));
  }

  /** The item in the open format, conditions folded back in. */
  private assemble(): RawItem {
    const out: Record<string, unknown> = { ...this.raw(), id: this.slug() };
    for (const [name, rows] of Object.entries(this.conds())) {
      const cond = fromRows(rows);
      if (Object.keys(cond).length > 0 || name === 'when') {
        out[name] = cond;
      }
    }
    for (const key of Object.keys(out)) {
      const v = out[key];
      if (v === '' || (Array.isArray(v) && v.length === 0)) {
        delete out[key];
      }
    }
    return out as RawItem;
  }

  protected text(field: string): string {
    const v = this.raw()[field];
    return typeof v === 'string' ? v : '';
  }

  protected lines(field: string): string {
    const v = this.raw()[field];
    return Array.isArray(v) ? v.join('\n') : '';
  }

  protected set(field: string, value: unknown): void {
    this.raw.update((r) => ({ ...r, [field]: value }));
    this.impact.set(null);
  }

  protected setLines(field: string, value: string): void {
    this.set(
      field,
      value
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean),
    );
  }

  protected setCond(name: string, rows: ConditionRows): void {
    this.conds.update((c) => ({ ...c, [name]: rows }));
    this.impact.set(null);
    this.tried.set(null);
  }

  protected characteristic(id: string): string {
    const c = this.raw()['characteristics'];
    return c && typeof c === 'object' ? ((c as Record<string, string>)[id] ?? '') : '';
  }

  protected setCharacteristic(id: string, value: string): void {
    const current = { ...((this.raw()['characteristics'] as Record<string, string>) ?? {}) };
    if (value) {
      current[id] = value;
    } else {
      delete current[id];
    }
    this.set('characteristics', current);
  }

  protected toggleAdvanced(): void {
    if (this.advanced()) {
      this.applyJson();
      if (this.jsonError()) {
        return;
      }
    } else {
      this.json.set(JSON.stringify(this.assemble(), null, 2));
    }
    this.advanced.update((a) => !a);
  }

  protected applyJson(): void {
    try {
      const parsed = JSON.parse(this.json()) as Record<string, unknown>;
      if (parsed['id'] !== undefined && typeof parsed['id'] === 'string' && this.isNew()) {
        this.slug.set(parsed['id']);
      }
      this.jsonError.set('');
      this.adopt({ ...parsed, id: this.slug() });
    } catch {
      this.jsonError.set('This is not valid JSON.');
    }
  }

  private body(): RawItem {
    if (this.advanced() || !this.structured()) {
      this.applyJson();
    }
    return this.assemble();
  }

  protected valuesOf(attribute: string): string[] {
    return this.vocab()?.attributes.find((a) => a.id === attribute)?.values ?? [];
  }

  protected setTry(attribute: string, value: string): void {
    this.tryValues.update((t) => ({ ...t, [attribute]: value }));
    this.tried.set(null);
  }

  protected toggleTryAbb(abb: string, on: boolean): void {
    this.tryAbbs.update((a) => (on ? [...a, abb] : a.filter((x) => x !== abb)));
    this.tried.set(null);
  }

  protected async runTry(): Promise<void> {
    this.problem.set(null);
    try {
      const attributes: Record<string, string> = {};
      for (const attr of this.referenced().attributes) {
        attributes[attr] = this.tryValues()[attr] ?? 'unknown';
      }
      const result = await firstValueFrom(
        this.api.post<TryResult>('/catalog/try', {
          condition: fromRows(this.conds()['when']),
          attributes,
          abbs: this.tryAbbs().filter((a) => this.referenced().abbs.includes(a)),
        }),
      );
      this.tried.set(result);
      this.announcer.say(`Result: ${result.outcome}`);
    } catch (error) {
      this.problem.set(toProblem(error));
    }
  }

  protected async preview(): Promise<void> {
    this.busy.set(true);
    this.problem.set(null);
    try {
      this.impact.set(
        await firstValueFrom(
          this.api.post<Impact>('/catalog/impact', {
            kind: this.kind(),
            item: this.body(),
            status: 'proposed',
          }),
        ),
      );
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.busy.set(false);
    }
  }

  protected async save(status: Status): Promise<void> {
    this.busy.set(true);
    this.problem.set(null);
    this.stale.set(null);
    this.warnings.set([]);
    const query = new URLSearchParams({ status, change_note: this.note() });
    const base = this.baseVersion();
    if (base !== null) {
      query.set('base_version', String(base));
    }
    try {
      const out = await firstValueFrom(
        this.api.put<{ version: number; issues: string[] }>(
          `/catalog/${this.kind()}/${this.slug()}?${query.toString()}`,
          this.body(),
        ),
      );
      this.announcer.say(`Saved version ${out.version}`);
      this.warnings.set(out.issues);
      await this.router.navigate(['/catalog', ROUTE_OF_KIND[this.kind()], this.slug()]);
    } catch (error) {
      const detail =
        error instanceof HttpErrorResponse ? (error.error as { detail?: unknown })?.detail : null;
      if (
        error instanceof HttpErrorResponse &&
        error.status === 409 &&
        detail &&
        typeof detail === 'object' &&
        (detail as { code?: string }).code === 'stale'
      ) {
        this.stale.set(detail as Stale);
      } else {
        this.problem.set(toProblem(error));
      }
    } finally {
      this.busy.set(false);
    }
  }

  /** Continue from their version while keeping what was typed (nothing is lost). */
  protected keepMine(s: Stale): void {
    this.baseVersion.set(s.latest_version);
    this.stale.set(null);
  }

  protected takeTheirs(s: Stale): void {
    this.baseVersion.set(s.latest_version);
    this.adopt(s.latest_item);
    this.stale.set(null);
  }
}
