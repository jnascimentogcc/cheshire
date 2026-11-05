import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';

import { Api, toProblem } from '../core/api';
import type { ApiProblem } from '../core/models';
import { ProblemNotice } from '../shared/problem-notice';
import { type Kind, ROUTE_OF_KIND } from '../catalog/models';
import { parseProposal } from './logic';
import type { Discussion } from './models';

const KINDS: Kind[] = ['abb', 'sbb', 'rule', 'attribute', 'characteristic', 'lens'];

/**
 * Start a discussion about an existing item, or about one that does not exist yet (the
 * proposal is its draft). Arrives with `?kind=&slug=` from an item page, and `&work=` when
 * the architect has claimed a work-queue entry. The opener becomes the decider.
 */
@Component({
  selector: 'app-discussion-new',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, FormsModule, TranslocoPipe, ProblemNotice],
  template: `
    <p>
      <a routerLink="/discussions">← {{ 'discussions.title' | transloco }}</a>
    </p>
    <h1>{{ 'discussions.new' | transloco }}</h1>
    <p class="hint">{{ 'discussions.new_intro' | transloco }}</p>
    <app-problem-notice [problem]="problem()" />

    @if (existing()) {
      <div class="notice notice-warning" role="status">
        <p>{{ 'discussions.already_open' | transloco }}</p>
        <a class="btn btn-primary btn-sm" [routerLink]="['/discussions', existing()]">{{
          'discussions.join' | transloco
        }}</a>
      </div>
    }

    <form class="card form" (submit)="$event.preventDefault(); open()">
      <label class="field">
        <span class="label">{{ 'discussions.f_kind' | transloco }}</span>
        <select class="input" name="kind" [(ngModel)]="kind">
          @for (k of kinds; track k) {
            <option [value]="k">{{ 'kind.' + routeOf[k] | transloco }}</option>
          }
        </select>
      </label>
      <label class="field">
        <span class="label">{{ 'discussions.item_id' | transloco }}</span>
        <input class="input mono" name="slug" required [(ngModel)]="slug" />
        <span class="hint">{{ 'discussions.item_id_hint' | transloco }}</span>
      </label>
      <label class="field">
        <span class="label">{{ 'discussions.topic' | transloco }}</span>
        <input class="input" name="title" maxlength="200" [(ngModel)]="title" />
      </label>
      <label class="field">
        <span class="label">{{ 'discussions.new_proposal' | transloco }}</span>
        <textarea
          class="input mono"
          name="proposal"
          rows="10"
          spellcheck="false"
          [(ngModel)]="proposal"
        ></textarea>
        <span class="hint">{{ 'discussions.new_proposal_hint' | transloco }}</span>
      </label>
      @if (work()) {
        <p class="hint">{{ 'discussions.from_work' | transloco: { n: work() } }}</p>
      }
      <button type="submit" class="btn btn-primary" [disabled]="busy()">
        {{ 'discussions.open' | transloco }}
      </button>
    </form>
  `,
  styles: `
    .form {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      align-items: flex-start;
      max-width: 44rem;
      margin: var(--space-4) 0;
    }
    .form .field,
    textarea {
      width: 100%;
    }
    h1 {
      margin: 0;
    }
  `,
})
export class DiscussionNewPage implements OnInit {
  private readonly api = inject(Api);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly routeOf = ROUTE_OF_KIND;
  protected readonly kinds = KINDS;
  protected kind: Kind = 'abb';
  protected slug = '';
  protected title = '';
  protected proposal = '';
  protected readonly work = signal<number | null>(null);
  protected readonly existing = signal<number | null>(null);
  protected readonly busy = signal(false);
  protected readonly problem = signal<ApiProblem | null>(null);

  ngOnInit(): void {
    const q = this.route.snapshot.queryParamMap;
    const kind = q.get('kind');
    if (kind && (KINDS as string[]).includes(kind)) {
      this.kind = kind as Kind;
    }
    this.slug = q.get('slug') ?? '';
    const work = Number(q.get('work'));
    this.work.set(Number.isInteger(work) && work > 0 ? work : null);
  }

  protected async open(): Promise<void> {
    this.problem.set(null);
    this.existing.set(null);
    const body: Record<string, unknown> = {
      kind: this.kind,
      slug: this.slug.trim(),
      title: this.title.trim(),
    };
    if (this.proposal.trim()) {
      const parsed = parseProposal(this.proposal);
      if (!parsed.item) {
        this.problem.set({ status: 422, code: 'invalid_input', message: '' });
        return;
      }
      body['proposal'] = parsed.item;
    }
    if (this.work()) {
      body['work_item_id'] = this.work();
    }
    this.busy.set(true);
    try {
      const d = await firstValueFrom(this.api.post<Discussion>('/discussions', body));
      await this.router.navigate(['/discussions', d.id]);
    } catch (error) {
      const problem = toProblem(error);
      if (problem.code === 'already_open') {
        this.existing.set(Number(problem.detail?.['discussion_id']) || null);
      }
      this.problem.set(problem);
    } finally {
      this.busy.set(false);
    }
  }
}
