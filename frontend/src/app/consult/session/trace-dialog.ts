import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  Injectable,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';

import type { TraceEntry } from '../../core/models';

/** Opens the "Why?" panel from anywhere on the page. */
@Injectable({ providedIn: 'root' })
export class TraceViewer {
  readonly heading = signal('');
  readonly entries = signal<TraceEntry[]>([]);
  /** Bumped on every request so the same entries can be opened twice in a row. */
  readonly request = signal(0);

  open(heading: string, entries: TraceEntry[]): void {
    this.heading.set(heading);
    this.entries.set(entries);
    this.request.update((n) => n + 1);
  }
}

/**
 * The rule trace in a modal dialog: rule, reason and each test with its value and source.
 * It is a native `<dialog>`, so focus is trapped, Escape closes it and focus returns to
 * the control that opened it. The same text is plain text, readable by keyboard.
 */
@Component({
  selector: 'app-trace-dialog',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [TranslocoPipe],
  template: `
    <dialog #dialog aria-labelledby="trace-title" (click)="backdrop($event)">
      <div class="head">
        <h2 id="trace-title">{{ viewer.heading() }}</h2>
        <button type="button" class="btn btn-secondary btn-sm" (click)="close()">
          {{ 'common.close' | transloco }}
        </button>
      </div>
      @for (entry of viewer.entries(); track entry.ref) {
        <section class="entry">
          <h3 class="mono ref">{{ entry.ref }}</h3>
          <pre class="text">{{ entry.text }}</pre>
        </section>
      } @empty {
        <p>{{ 'trace.empty' | transloco }}</p>
      }
    </dialog>
  `,
  styles: `
    dialog {
      width: min(720px, calc(100vw - 2 * var(--space-4)));
      max-height: 85vh;
      padding: var(--space-4);
      color: var(--text);
      background: var(--surface);
      border: 1px solid var(--border-2);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow-md);
    }
    dialog::backdrop {
      background: rgba(31, 37, 50, 0.5);
    }
    .head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: var(--space-3);
      margin-bottom: var(--space-3);
    }
    .head h2 {
      margin: 0;
    }
    .entry {
      padding: var(--space-3) 0;
      border-top: 1px solid var(--border);
    }
    .ref {
      margin: 0 0 var(--space-1);
      font-size: 0.93rem;
      color: var(--text-2);
    }
    .text {
      margin: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-family: var(--mono);
      font-size: 0.93rem;
    }
  `,
})
export class TraceDialog {
  protected readonly viewer = inject(TraceViewer);
  private readonly dialog = viewChild.required<ElementRef<HTMLDialogElement>>('dialog');

  constructor() {
    effect(() => {
      if (this.viewer.request() > 0) {
        const el = this.dialog().nativeElement;
        if (!el.open) {
          el.showModal();
        }
      }
    });
  }

  protected close(): void {
    this.dialog().nativeElement.close();
  }

  /** A click on the backdrop closes it: nothing is lost, this dialog only reads. */
  protected backdrop(event: MouseEvent): void {
    if (event.target === this.dialog().nativeElement) {
      this.close();
    }
  }
}
