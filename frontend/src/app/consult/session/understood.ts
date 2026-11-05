import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { TranslocoPipe } from '@jsverse/transloco';

import type { CatalogAttribute, Consultation } from '../../core/models';
import { ProblemNotice } from '../../shared/problem-notice';
import { SourceBadge } from '../../shared/badges';
import { FactRow, factRows, spanSources } from '../logic';
import { SessionStore } from '../store';

/** Region 2: what was understood. Inferred values and identified ABBs can be changed. */
@Component({
  selector: 'app-understood-region',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TranslocoPipe, ProblemNotice, SourceBadge],
  template: `
    <section class="card" aria-labelledby="und-title">
      <h2 id="und-title">{{ 'understood.title' | transloco }}</h2>
      <app-problem-notice [problem]="store.problems()['understood'] ?? null" />

      <h3>{{ 'understood.attributes' | transloco }}</h3>
      @if (rows().length === 0) {
        <p class="hint">{{ 'understood.no_facts' | transloco }}</p>
      } @else {
        <div class="table-wrap">
          <table class="data">
            <caption class="sr-only">
              {{
                'understood.attributes' | transloco
              }}
            </caption>
            <thead>
              <tr>
                <th scope="col">{{ 'understood.col_attribute' | transloco }}</th>
                <th scope="col">{{ 'understood.col_value' | transloco }}</th>
                <th scope="col">{{ 'understood.col_source' | transloco }}</th>
                <th scope="col">{{ 'understood.col_span' | transloco }}</th>
              </tr>
            </thead>
            <tbody>
              @for (row of rows(); track row.attribute) {
                <tr>
                  <th scope="row" class="mono">{{ row.attribute }}</th>
                  <td>
                    @if (editingAttr() === row.attribute) {
                      <form (ngSubmit)="saveEdit(row)" class="edit">
                        @if (attr(row.attribute); as a) {
                          <fieldset>
                            <legend class="sr-only">{{ a.question }}</legend>
                            @for (v of a.values; track v) {
                              <label class="opt">
                                <input
                                  [type]="a.multi ? 'checkbox' : 'radio'"
                                  [name]="'edit-' + row.attribute"
                                  [checked]="chosen().includes(v)"
                                  (change)="toggle(a, v)"
                                />
                                <span class="mono">{{ v }}</span>
                              </label>
                            }
                          </fieldset>
                        }
                        <span class="actions">
                          <button
                            type="submit"
                            class="btn btn-primary btn-sm"
                            [disabled]="!chosen().length || busy()"
                          >
                            {{ 'common.save' | transloco }}
                          </button>
                          <button
                            type="button"
                            class="btn btn-ghost btn-sm"
                            (click)="editingAttr.set(null)"
                          >
                            {{ 'common.cancel' | transloco }}
                          </button>
                        </span>
                      </form>
                    } @else if (row.value.length) {
                      <span class="mono">{{ row.value.join(', ') }}</span>
                    } @else {
                      <span class="hint">{{ 'understood.unknown_value' | transloco }}</span>
                    }
                  </td>
                  <td>
                    <app-source-badge [source]="row.source" />
                    @if (
                      row.source === 'inferred' && !readOnly() && editingAttr() !== row.attribute
                    ) {
                      <button type="button" class="btn btn-ghost btn-sm" (click)="startEdit(row)">
                        {{ 'understood.edit' | transloco }}
                        <span class="sr-only">{{ row.attribute }}</span>
                      </button>
                    }
                  </td>
                  <td>
                    @if (indexOf('attribute', row.attribute); as n) {
                      <sup class="mono">{{ n }}</sup>
                    }
                    {{ row.span }}
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }

      <h3>{{ 'understood.abbs' | transloco }}</h3>
      @if (view().identified_abbs.length === 0) {
        <p class="hint">{{ 'understood.no_abbs' | transloco }}</p>
      } @else {
        <ul class="abbs">
          @for (abb of view().identified_abbs; track abb.id) {
            <li>
              <span>
                <strong>{{ abbName(abb.id) }}</strong>
                <span class="hint">
                  @if (abb.span) {
                    — {{ 'understood.from_text' | transloco }}
                    @if (indexOf('abb', abb.id); as n) {
                      <sup class="mono">{{ n }}</sup>
                    }
                    “{{ abb.span }}”
                  } @else {
                    — {{ 'understood.by_you' | transloco }}
                  }
                </span>
              </span>
              @if (!readOnly()) {
                <button
                  type="button"
                  class="btn btn-ghost btn-sm"
                  [disabled]="busy()"
                  (click)="store.removeAbb(abb.id)"
                >
                  {{ 'understood.remove' | transloco }}
                  <span class="sr-only">{{ abbName(abb.id) }}</span>
                </button>
              }
            </li>
          }
        </ul>
      }
      <p class="hint">{{ 'understood.rule_abbs_note' | transloco }}</p>

      @if (!readOnly() && addable().length) {
        <form class="add" (ngSubmit)="add()">
          <div class="field">
            <label for="add-abb">{{ 'understood.add_label' | transloco }}</label>
            <select id="add-abb" name="add" class="input" [(ngModel)]="toAdd">
              <option value="">{{ 'understood.add_placeholder' | transloco }}</option>
              @for (a of addable(); track a.id) {
                <option [value]="a.id">{{ a.name }}</option>
              }
            </select>
          </div>
          <button type="submit" class="btn btn-secondary" [disabled]="!toAdd || busy()">
            {{ 'understood.add' | transloco }}
          </button>
        </form>
      }
    </section>
  `,
  styles: `
    section {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    h2,
    h3 {
      margin: 0;
    }
    .abbs {
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: var(--space-2);
    }
    .abbs li {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-2);
    }
    .edit,
    .add {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-end;
      gap: var(--space-3);
    }
    fieldset {
      border: 0;
      margin: 0;
      padding: 0;
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
    }
    .opt {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      min-height: 36px;
    }
    .actions {
      display: inline-flex;
      gap: var(--space-2);
    }
    .add .field {
      min-width: 240px;
    }
  `,
})
export class UnderstoodRegion {
  protected readonly store = inject(SessionStore);
  readonly view = input.required<Consultation>();
  readonly readOnly = input(false);

  protected readonly rows = computed(() => factRows(this.view()));
  protected readonly sources = computed(() => spanSources(this.view()));
  protected readonly editingAttr = signal<string | null>(null);
  protected readonly chosen = signal<string[]>([]);
  protected toAdd = '';
  protected readonly busy = computed(() => !!this.store.busy()['understood']);

  protected readonly addable = computed(() => {
    const identified = new Set(this.view().identified_abbs.map((a) => a.id));
    return this.view().catalog.abbs.filter((a) => !identified.has(a.id));
  });

  protected abbName(id: string): string {
    return this.view().catalog.abbs.find((a) => a.id === id)?.name ?? id;
  }

  protected attr(id: string): CatalogAttribute | undefined {
    return this.view().catalog.attributes.find((a) => a.id === id);
  }

  protected indexOf(kind: 'abb' | 'attribute', id: string): number | null {
    return this.sources().find((s) => s.kind === kind && s.id === id)?.index ?? null;
  }

  protected startEdit(row: FactRow): void {
    this.chosen.set([...row.value]);
    this.editingAttr.set(row.attribute);
  }

  protected toggle(attr: CatalogAttribute, value: string): void {
    if (!attr.multi) {
      this.chosen.set([value]);
    } else {
      this.chosen.update((all) =>
        all.includes(value) ? all.filter((v) => v !== value) : [...all, value],
      );
    }
  }

  protected async saveEdit(row: FactRow): Promise<void> {
    const values = this.chosen();
    if (!values.length) {
      return;
    }
    await this.store.editFact(row.attribute, values.length === 1 ? values[0] : values);
    if (!this.store.problems()['understood']) {
      this.editingAttr.set(null);
    }
  }

  protected async add(): Promise<void> {
    if (!this.toAdd) {
      return;
    }
    await this.store.addAbb(this.toAdd);
    this.toAdd = '';
  }
}
