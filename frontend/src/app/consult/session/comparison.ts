import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import type { Consultation } from '../../core/models';
import { ResultBadge, StateBadge } from '../../shared/badges';
import { comparable, comparisonTable } from '../logic';

/**
 * Region 6: SBBs side by side, built only from declared facts. Columns are alphabetical;
 * there is no sorting control and no "best" mark (invariant 2).
 */
@Component({
  selector: 'app-comparison-region',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoPipe, ResultBadge, StateBadge],
  template: `
    @if (tables().length) {
      <section class="card" aria-labelledby="cmp-title">
        <h2 id="cmp-title">{{ 'comparison.title' | transloco }}</h2>
        <p class="hint">{{ 'comparison.note' | transloco }}</p>
        @for (t of tables(); track t.abb) {
          <h3>{{ t.name }}</h3>
          <div class="table-wrap">
            <table class="data">
              <caption class="sr-only">
                {{
                  t.name
                }}
              </caption>
              <thead>
                <tr>
                  <td></td>
                  @for (col of t.table.columns; track col.id) {
                    <th scope="col">
                      {{ col.name }}
                      <div class="labels">
                        <app-result-badge [result]="col.result" />
                        <app-state-badge [state]="col.state" />
                      </div>
                    </th>
                  }
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">{{ 'comparison.when_to_choose' | transloco }}</th>
                  @for (col of t.table.columns; track col.id) {
                    <td>{{ t.table.details.get(col.id)?.when_to_choose || '—' }}</td>
                  }
                </tr>
                <tr>
                  <th scope="row">{{ 'comparison.limitations' | transloco }}</th>
                  @for (col of t.table.columns; track col.id) {
                    <td>{{ t.table.details.get(col.id)?.limitations || '—' }}</td>
                  }
                </tr>
                @for (name of t.table.characteristics; track name) {
                  <tr>
                    <th scope="row" class="mono">{{ name }}</th>
                    @for (col of t.table.columns; track col.id) {
                      <td class="mono">
                        {{ t.table.details.get(col.id)?.characteristics?.[name] ?? '—' }}
                      </td>
                    }
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </section>
    }
  `,
  styles: `
    section {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    h2,
    h3,
    p {
      margin: 0;
    }
    th[scope='col'] {
      min-width: 180px;
    }
    .labels {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-1);
      margin-top: var(--space-1);
      font-weight: 400;
    }
  `,
})
export class ComparisonRegion {
  readonly view = input.required<Consultation>();

  protected readonly tables = computed(() => {
    const view = this.view();
    const result = view.evaluation?.result;
    if (!result) {
      return [];
    }
    return comparable(result).map((abb) => ({
      abb: abb.id,
      name: view.catalog.abbs.find((a) => a.id === abb.id)?.name ?? abb.id,
      table: comparisonTable(abb, view.catalog.sbbs),
    }));
  });
}
