import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';

import { Announcer } from '../core/announcer';
import { Api, toProblem } from '../core/api';
import type { ApiProblem } from '../core/models';
import { ProblemNotice } from '../shared/problem-notice';
import { type Interview, type Kind, ROUTE_OF_KIND, type Suggestion } from './models';

interface InterviewRow {
  id: number;
  status: string;
  subject: string | null;
  started_by: string;
  pending: number;
}

/** Start a guided capture, from an ABB or from scratch, or pick one up again. */
@Component({
  selector: 'app-interview-start',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, FormsModule, TranslocoPipe, ProblemNotice],
  template: `
    <p>
      <a routerLink="/catalog">← {{ 'catalog.title' | transloco }}</a>
    </p>
    <h1>{{ 'interview.title' | transloco }}</h1>
    <p class="hint">{{ 'interview.intro' | transloco }}</p>
    <app-problem-notice [problem]="problem()" />

    <form class="card form" (submit)="$event.preventDefault(); start()">
      <label class="field">
        <span class="label">{{ 'interview.subject' | transloco }}</span>
        <select
          class="input"
          name="subject"
          [ngModel]="subject()"
          (ngModelChange)="subject.set($event)"
        >
          <option value="">{{ 'interview.from_scratch' | transloco }}</option>
          @for (a of abbs(); track a.slug) {
            <option [value]="a.slug">{{ a.slug }} — {{ a.facts['name'] }}</option>
          }
        </select>
      </label>
      <button type="submit" class="btn btn-primary" [disabled]="busy()">
        {{ 'interview.start' | transloco }}
      </button>
    </form>

    @if (rows().length > 0) {
      <h2>{{ 'interview.earlier' | transloco }}</h2>
      <ul>
        @for (r of rows(); track r.id) {
          <li>
            <a [routerLink]="['/catalog/interview', r.id]">
              #{{ r.id }} · {{ r.subject ?? ('interview.from_scratch' | transloco) }} ·
              {{ r.started_by }}
            </a>
            ({{ 'interview.status_' + r.status | transloco }},
            {{ 'interview.pending' | transloco: { n: r.pending } }})
          </li>
        }
      </ul>
    }
  `,
  styles: `
    .form {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      align-items: flex-start;
      max-width: 36rem;
      margin: var(--space-4) 0;
    }
    h1,
    h2 {
      margin: 0 0 var(--space-2);
    }
  `,
})
export class InterviewStartPage implements OnInit {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  protected readonly abbs = signal<{ slug: string; facts: Record<string, string> }[]>([]);
  protected readonly rows = signal<InterviewRow[]>([]);
  protected readonly subject = signal('');
  protected readonly busy = signal(false);
  protected readonly problem = signal<ApiProblem | null>(null);

  ngOnInit(): void {
    void (async () => {
      try {
        this.abbs.set(await firstValueFrom(this.api.get('/catalog/abb?detail=true')));
        this.rows.set(await firstValueFrom(this.api.get<InterviewRow[]>('/interviews')));
      } catch (error) {
        this.problem.set(toProblem(error));
      }
    })();
  }

  protected async start(): Promise<void> {
    this.busy.set(true);
    this.problem.set(null);
    try {
      const view = await firstValueFrom(
        this.api.post<Interview>('/interviews', { subject: this.subject() || null }),
      );
      await this.router.navigate(['/catalog/interview', view.id]);
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.busy.set(false);
    }
  }
}

/** The conversation and its suggestions. Nothing is written until a person accepts. */
@Component({
  selector: 'app-interview',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, FormsModule, TranslocoPipe, ProblemNotice],
  template: `
    <p>
      <a routerLink="/catalog/interview">← {{ 'interview.title' | transloco }}</a>
    </p>
    <app-problem-notice
      [problem]="problem()"
      [retryable]="view()?.needs_retry ?? false"
      (retry)="retry()"
    />
    @if (view(); as v) {
      <h1>{{ 'interview.heading' | transloco: { id: v.id } }}</h1>
      <p class="hint">
        {{ v.subject ?? ('interview.from_scratch' | transloco) }} ·
        {{ 'interview.progress' | transloco: v.progress }}
      </p>

      <ol class="conversation" [attr.aria-label]="'interview.conversation' | transloco">
        @for (m of v.messages; track m.id) {
          <li class="msg" [class.me]="m.role === 'user'">
            <span class="who">{{
              (m.role === 'user' ? 'interview.you' : 'interview.assistant') | transloco
            }}</span>
            <p>{{ m.text }}</p>
          </li>
        }
      </ol>

      @if (v.status === 'open' && !v.finished) {
        <form class="card answer" (submit)="$event.preventDefault(); send(false)">
          <label class="field">
            <span class="label">{{ 'interview.your_answer' | transloco }}</span>
            <textarea
              class="input"
              rows="4"
              name="answer"
              [ngModel]="answer()"
              (ngModelChange)="answer.set($event)"
              [disabled]="v.needs_retry"
            ></textarea>
          </label>
          <div class="actions">
            <button
              type="submit"
              class="btn btn-primary"
              [disabled]="busy() || v.needs_retry || !answer().trim()"
            >
              {{ 'interview.send' | transloco }}
            </button>
            <button
              type="button"
              class="btn btn-secondary"
              [disabled]="busy() || v.needs_retry"
              (click)="send(true)"
            >
              {{ 'interview.not_applicable' | transloco }}
            </button>
            @if (v.needs_retry) {
              <button type="button" class="btn btn-secondary" [disabled]="busy()" (click)="retry()">
                {{ 'common.try_again' | transloco }}
              </button>
            }
          </div>
          @if (busy()) {
            <p role="status">
              <span class="spinner" aria-hidden="true"></span>
              {{ 'interview.thinking' | transloco }}
            </p>
          }
        </form>
      }

      <h2>{{ 'interview.suggestions' | transloco }}</h2>
      @if (v.suggestions.length === 0) {
        <p class="hint">{{ 'interview.no_suggestions' | transloco }}</p>
      }
      <ul class="suggestions">
        @for (s of v.suggestions; track s.id) {
          <li class="card suggestion">
            <p class="tag">
              <span class="badge badge-info">{{
                'interview.suggested_by_assistant' | transloco
              }}</span>
              {{ 'interview.kind_' + s.kind | transloco }}
              <span class="badge badge-neutral">{{
                'interview.state_' + s.status | transloco
              }}</span>
            </p>
            <p class="summary">{{ summary(s) }}</p>
            <p class="hint">
              {{ 'interview.because' | transloco }} “{{ s.payload.quote }}” — {{ s.payload.why }}
            </p>
            <details>
              <summary>{{ 'item.raw' | transloco }}</summary>
              <pre class="mono raw">{{ raw(s) }}</pre>
            </details>
            @if (s.status === 'pending') {
              <div class="actions">
                <button
                  type="button"
                  class="btn btn-primary btn-sm"
                  [disabled]="busy()"
                  (click)="decide(s, 'accept')"
                >
                  {{ 'interview.accept' | transloco }}
                </button>
                <button
                  type="button"
                  class="btn btn-secondary btn-sm"
                  [disabled]="busy()"
                  (click)="decide(s, 'reject')"
                >
                  {{ 'interview.reject' | transloco }}
                </button>
                <button type="button" class="btn btn-ghost btn-sm" (click)="askDepends(s)">
                  {{ 'interview.depends' | transloco }}
                </button>
              </div>
              @if (depending() === s.id) {
                <form class="depends" (submit)="$event.preventDefault(); decide(s, 'depends')">
                  <label class="field">
                    <span class="label">{{ 'interview.depends_on' | transloco }}</span>
                    <input
                      class="input"
                      name="note"
                      [ngModel]="note()"
                      (ngModelChange)="note.set($event)"
                    />
                  </label>
                  <button
                    type="submit"
                    class="btn btn-secondary btn-sm"
                    [disabled]="busy() || !note().trim()"
                  >
                    {{ 'interview.refine' | transloco }}
                  </button>
                </form>
              }
            }
            @if (s.status === 'accepted' && s.resulting_kind && s.resulting_item) {
              <p>
                {{ 'interview.saved_as' | transloco }}
                <a
                  [routerLink]="['/catalog', route(s.resulting_kind), s.resulting_item]"
                  class="mono"
                  >{{ s.resulting_item }}</a
                >
              </p>
            }
            @if (s.status === 'depends') {
              <p class="hint">{{ 'interview.depends_noted' | transloco }}: {{ s.follow_up }}</p>
            }
          </li>
        }
      </ul>

      @if (v.status === 'open') {
        <button type="button" class="btn btn-secondary" (click)="close()">
          {{ 'interview.close' | transloco }}
        </button>
      }
    }
  `,
  styles: `
    h1,
    h2 {
      margin: 0 0 var(--space-2);
    }
    .conversation {
      list-style: none;
      padding: 0;
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      max-width: 48rem;
    }
    .msg {
      padding: var(--space-3);
      border: 1px solid var(--border);
      border-radius: var(--radius);
    }
    .msg.me {
      background: var(--accent-soft-2);
    }
    .msg p {
      margin: var(--space-1) 0 0;
      white-space: pre-wrap;
    }
    .who {
      font-weight: 600;
    }
    .answer,
    .suggestion {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      max-width: 48rem;
    }
    .suggestions {
      list-style: none;
      padding: 0;
      display: grid;
      gap: var(--space-3);
      margin: 0 0 var(--space-4);
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
    }
    .tag,
    .summary {
      margin: 0;
    }
    .summary {
      font-weight: 500;
    }
    .raw {
      white-space: pre-wrap;
    }
    .depends {
      display: flex;
      gap: var(--space-3);
      align-items: flex-end;
    }
  `,
})
export class InterviewPage implements OnInit {
  private readonly api = inject(Api);
  private readonly route$ = inject(ActivatedRoute);
  private readonly announcer = inject(Announcer);

  protected readonly view = signal<Interview | null>(null);
  protected readonly answer = signal('');
  protected readonly note = signal('');
  protected readonly depending = signal<number | null>(null);
  protected readonly busy = signal(false);
  protected readonly problem = signal<ApiProblem | null>(null);
  private id = 0;

  ngOnInit(): void {
    this.id = Number(this.route$.snapshot.paramMap.get('id'));
    void this.refresh();
  }

  protected route(kind: Kind): string {
    return ROUTE_OF_KIND[kind];
  }

  protected summary(s: Suggestion): string {
    if (s.kind === 'attribute_value') {
      return `${s.payload.attribute} + ${s.payload.value}`;
    }
    const item = s.payload.item ?? { id: '' };
    return [item.id, item['name'], item['realises'] ?? item['activates']]
      .filter(Boolean)
      .join(' · ');
  }

  protected raw(s: Suggestion): string {
    return JSON.stringify(
      s.payload.item ?? { attribute: s.payload.attribute, value: s.payload.value },
      null,
      2,
    );
  }

  private async refresh(): Promise<void> {
    try {
      this.view.set(await firstValueFrom(this.api.get<Interview>(`/interviews/${this.id}`)));
    } catch (error) {
      this.problem.set(toProblem(error));
    }
  }

  /** Runs an action that returns the whole interview; a failure keeps what was typed. */
  private async act(call: () => Promise<Interview>): Promise<boolean> {
    this.busy.set(true);
    this.problem.set(null);
    try {
      this.view.set(await call());
      return true;
    } catch (error) {
      this.problem.set(toProblem(error));
      await this.refresh();
      return false;
    } finally {
      this.busy.set(false);
    }
  }

  protected async send(notApplicable: boolean): Promise<void> {
    const ok = await this.act(() =>
      firstValueFrom(
        this.api.post<Interview>(`/interviews/${this.id}/answers`, {
          text: this.answer(),
          not_applicable: notApplicable,
        }),
      ),
    );
    if (ok) {
      this.answer.set('');
      this.announcer.say('Answer recorded');
    }
  }

  protected async retry(): Promise<void> {
    await this.act(() => firstValueFrom(this.api.post<Interview>(`/interviews/${this.id}/retry`)));
  }

  protected askDepends(s: Suggestion): void {
    this.note.set('');
    this.depending.set(this.depending() === s.id ? null : s.id);
  }

  protected async decide(s: Suggestion, decision: 'accept' | 'reject' | 'depends'): Promise<void> {
    const ok = await this.act(() =>
      firstValueFrom(
        this.api.post<Interview>(`/suggestions/${s.id}/decision`, {
          decision,
          note: decision === 'depends' ? this.note() : '',
        }),
      ),
    );
    if (ok) {
      this.depending.set(null);
      this.announcer.say(
        `Suggestion ${decision === 'accept' ? 'accepted' : decision === 'reject' ? 'rejected' : 'refined'}`,
      );
    }
  }

  protected async close(): Promise<void> {
    await this.act(() => firstValueFrom(this.api.post<Interview>(`/interviews/${this.id}/close`)));
  }
}
