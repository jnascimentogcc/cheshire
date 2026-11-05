import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import type { ConditionRows, ConditionTest } from './logic';
import type { Vocabulary } from './models';

/**
 * One level of condition rows: tests that must all hold (AND). Fully keyboard operable,
 * every control has a name (catalog-maintenance.md 6 and 13).
 */
@Component({
  selector: 'app-condition-rows',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoPipe],
  template: `
    <div class="rows">
      @for (test of rows().tests; track $index; let i = $index) {
        <fieldset class="row card">
          <legend class="sr-only">{{ 'builder.test_n' | transloco: { n: i + 1 } }}</legend>
          <label class="field">
            <span class="label">{{ 'builder.attribute' | transloco }}</span>
            <select
              class="input"
              [value]="test.attribute"
              (change)="setAttribute(i, $any($event.target).value)"
            >
              <option value="">{{ 'builder.choose' | transloco }}</option>
              @for (a of vocab().attributes; track a.id) {
                <option [value]="a.id" [selected]="a.id === test.attribute">{{ a.id }}</option>
              }
            </select>
          </label>
          @if (valuesOf(test); as options) {
            <fieldset class="values">
              <legend class="label">{{ 'builder.is_one_of' | transloco }}</legend>
              @for (v of options; track v) {
                <label class="check">
                  <input
                    type="checkbox"
                    [checked]="test.values.includes(v)"
                    (change)="toggleValue(i, v, $any($event.target).checked)"
                  />
                  {{ v }}
                </label>
              }
            </fieldset>
          }
          <button type="button" class="btn btn-ghost btn-sm" (click)="removeTest(i)">
            {{ 'builder.remove_test' | transloco }}
          </button>
        </fieldset>
      }
      <button type="button" class="btn btn-secondary btn-sm" (click)="addTest()">
        {{ 'builder.add_test' | transloco }}
      </button>

      <div class="abbs">
        <span class="label">{{ 'builder.abb_present' | transloco }}</span>
        <ul class="chips">
          @for (abb of rows().abbs; track abb) {
            <li class="chip">
              <span class="mono">{{ abb }}</span>
              <button
                type="button"
                class="btn btn-ghost btn-sm"
                [attr.aria-label]="'builder.remove_abb' | transloco: { id: abb }"
                (click)="removeAbb(abb)"
              >
                ×
              </button>
            </li>
          }
        </ul>
        <label class="field">
          <span class="sr-only">{{ 'builder.add_abb' | transloco }}</span>
          <select class="input" (change)="addAbb($any($event.target))">
            <option value="">{{ 'builder.add_abb' | transloco }}</option>
            @for (a of vocab().abbs; track a.id) {
              @if (!rows().abbs.includes(a.id)) {
                <option [value]="a.id">{{ a.id }} — {{ a.name }}</option>
              }
            }
          </select>
        </label>
      </div>
    </div>
  `,
  styles: `
    .rows {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      align-items: flex-start;
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
      align-items: flex-end;
      width: 100%;
    }
    .values {
      border: 0;
      padding: 0;
      margin: 0;
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-1) var(--space-3);
    }
    .check {
      display: inline-flex;
      gap: var(--space-1);
      align-items: center;
    }
    .chips {
      list-style: none;
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      padding: 0;
      margin: var(--space-1) 0;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      gap: var(--space-1);
      padding: 0 var(--space-2);
      border: 1px solid var(--border);
      border-radius: var(--radius);
    }
  `,
})
export class ConditionRowsEditor {
  readonly rows = input.required<ConditionRows>();
  readonly vocab = input.required<Vocabulary>();
  readonly rowsChange = output<ConditionRows>();

  protected valuesOf(test: ConditionTest): string[] | null {
    return this.vocab().attributes.find((a) => a.id === test.attribute)?.values ?? null;
  }

  private emit(patch: Partial<ConditionRows>): void {
    this.rowsChange.emit({ ...this.rows(), ...patch });
  }

  private withTest(i: number, patch: Partial<ConditionTest>): ConditionTest[] {
    return this.rows().tests.map((t, n) => (n === i ? { ...t, ...patch } : t));
  }

  protected setAttribute(i: number, attribute: string): void {
    this.emit({ tests: this.withTest(i, { attribute, values: [] }) });
  }

  protected toggleValue(i: number, value: string, on: boolean): void {
    const current = this.rows().tests[i].values;
    const values = on ? [...current, value] : current.filter((v) => v !== value);
    this.emit({ tests: this.withTest(i, { values }) });
  }

  protected addTest(): void {
    this.emit({ tests: [...this.rows().tests, { attribute: '', values: [] }] });
  }

  protected removeTest(i: number): void {
    this.emit({ tests: this.rows().tests.filter((_, n) => n !== i) });
  }

  protected addAbb(select: HTMLSelectElement): void {
    if (select.value) {
      this.emit({ abbs: [...this.rows().abbs, select.value] });
      select.value = '';
    }
  }

  protected removeAbb(abb: string): void {
    this.emit({ abbs: this.rows().abbs.filter((a) => a !== abb) });
  }
}

/** The rows plus the optional "except" group (the test rows of a group that must NOT hold). */
@Component({
  selector: 'app-condition-builder',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ConditionRowsEditor, TranslocoPipe],
  template: `
    <app-condition-rows
      [rows]="rows()"
      [vocab]="vocab()"
      (rowsChange)="rowsChange.emit({ ...$event, except: rows().except })"
    />
    @if (rows().except; as except) {
      <fieldset class="except card">
        <legend class="label">{{ 'builder.except' | transloco }}</legend>
        <app-condition-rows
          [rows]="except"
          [vocab]="vocab()"
          (rowsChange)="rowsChange.emit({ ...rows(), except: $event })"
        />
        <button
          type="button"
          class="btn btn-ghost btn-sm"
          (click)="rowsChange.emit({ ...rows(), except: null })"
        >
          {{ 'builder.remove_except' | transloco }}
        </button>
      </fieldset>
    } @else if (allowExcept()) {
      <button
        type="button"
        class="btn btn-secondary btn-sm add-except"
        (click)="rowsChange.emit({ ...rows(), except: { tests: [], abbs: [], except: null } })"
      >
        {{ 'builder.add_except' | transloco }}
      </button>
    }
  `,
  styles: `
    .except {
      margin-top: var(--space-3);
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      align-items: flex-start;
    }
    .add-except {
      margin-top: var(--space-3);
    }
  `,
})
export class ConditionBuilder {
  readonly rows = input.required<ConditionRows>();
  readonly vocab = input.required<Vocabulary>();
  readonly allowExcept = input(true);
  readonly rowsChange = output<ConditionRows>();
}
