import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import type { Coverage, FactSource, SbbResultKind, SbbState, Status } from '../core/models';

type Variant = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

/** A badge always carries text; colour only reinforces it (ui-spec 6.5). */
@Component({
  selector: 'app-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="badge" [class]="'badge-' + variant()"><ng-content /></span>`,
})
export class Badge {
  readonly variant = input<Variant>('neutral');
}

/** Coverage colours: covered=success, conditional=warning, blocked=danger, gap=info. */
@Component({
  selector: 'app-coverage-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Badge, TranslocoPipe],
  template: `<app-badge [variant]="variant()">{{
    'coverage.' + coverage() | transloco
  }}</app-badge>`,
})
export class CoverageBadge {
  readonly coverage = input.required<Coverage>();
  protected readonly variant = computed<Variant>(
    () =>
      ({ covered: 'success', conditional: 'warning', blocked: 'danger', gap: 'info' })[
        this.coverage()
      ] as Variant,
  );
}

/** Validation status is always visible on rules and entries (invariant 8). */
@Component({
  selector: 'app-status-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Badge, TranslocoPipe],
  template: `<app-badge [variant]="status() === 'validated' ? 'success' : 'warning'">{{
    'status.' + status() | transloco
  }}</app-badge>`,
})
export class StatusBadge {
  readonly status = input.required<Status>();
}

/**
 * SBB state labels are neutral so colour never ranks options; only an exclusion for
 * `prohibited` uses the danger style (tech-stack 6).
 */
@Component({
  selector: 'app-state-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Badge, TranslocoPipe],
  template: `<app-badge variant="neutral">{{ 'sbb_state.' + state() | transloco }}</app-badge>`,
})
export class StateBadge {
  readonly state = input.required<SbbState>();
}

@Component({
  selector: 'app-result-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Badge, TranslocoPipe],
  template: `<app-badge [variant]="result() === 'excluded' ? 'danger' : 'neutral'">{{
    'sbb_result.' + result() | transloco
  }}</app-badge>`,
})
export class ResultBadge {
  readonly result = input.required<SbbResultKind>();
}

@Component({
  selector: 'app-source-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [Badge, TranslocoPipe],
  template: `<app-badge [variant]="source() === 'unknown' ? 'warning' : 'neutral'">{{
    'source.' + source() | transloco
  }}</app-badge>`,
})
export class SourceBadge {
  readonly source = input.required<FactSource | 'unknown'>();
}
