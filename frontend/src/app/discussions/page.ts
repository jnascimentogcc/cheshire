import { DatePipe, NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  OnInit,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { firstValueFrom } from 'rxjs';

import { ROUTE_OF_KIND } from '../catalog/models';
import { Announcer } from '../core/announcer';
import { Api, toProblem } from '../core/api';
import { Auth } from '../core/auth';
import type { ApiProblem } from '../core/models';
import { UserPreferences } from '../core/preferences';
import { ProblemNotice } from '../shared/problem-notice';
import {
  type ResponseDraft,
  catalogRefs,
  latestSynthesis,
  newEntries,
  opposing,
  parseProposal,
  prefill,
  proposalText,
  stanceNeedsReason,
  unanswered,
} from './logic';
import {
  type Discussion,
  type Entry,
  type Member,
  type Outcome,
  STANCES,
  type Stance,
} from './models';

const POLL_MS = 20000;

/**
 * One discussion: header, proposal, impact radius, mediator brief, thread, positions and the
 * decision (discussions.md section 4). Everything the page shows about the catalog is
 * computed by the server; the mediator's words are labelled as AI-generated and cite facts.
 */
@Component({
  selector: 'app-discussion',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, NgTemplateOutlet, FormsModule, TranslocoPipe, ProblemNotice],
  template: `
    <p>
      <a routerLink="/discussions">← {{ 'discussions.title' | transloco }}</a>
    </p>
    <app-problem-notice [problem]="problem()" [retryable]="true" (retry)="load()" />

    @if (loading()) {
      <p role="status">
        <span class="spinner" aria-hidden="true"></span> {{ 'common.loading' | transloco }}
      </p>
    } @else if (d(); as disc) {
      <!-- 1. header -->
      <header class="head">
        <div>
          <h1>{{ disc.title }}</h1>
          <p class="meta">
            <a [routerLink]="itemLink(disc)" class="mono"
              >{{ disc.item.kind }}:{{ disc.item.slug }}</a
            >
            <span class="badge badge-neutral">{{
              'discussions.status_' + disc.status | transloco
            }}</span>
            @if (disc.proposal.is_new_item) {
              <span class="badge badge-info">{{ 'discussions.new_item' | transloco }}</span>
            }
          </p>
          <p class="hint">
            {{
              'discussions.opened_by'
                | transloco
                  : {
                      who: disc.opener.name,
                      when: (disc.opened_at | date: 'medium' : undefined : prefs.locale()),
                    }
            }}
            ·
            {{ 'discussions.decider_is' | transloco: { who: disc.decider.name } }}
            @if (!disc.decider.active) {
              <span class="badge badge-warning">{{ 'discussions.decider_left' | transloco }}</span>
            }
          </p>
          <p class="hint">
            {{ 'discussions.participants' | transloco }}:
            @for (p of disc.participants; track p.id; let last = $last) {
              {{ p.name }}{{ last ? '' : ', ' }}
            }
          </p>
          @if (disc.related.length > 0) {
            <p class="hint">
              {{ 'discussions.related' | transloco }}:
              @for (r of disc.related; track r.kind + r.slug) {
                <a class="mono" [routerLink]="['/catalog', routeOf[r.kind], r.slug]">{{
                  r.slug
                }}</a>
                &nbsp;
              }
            </p>
          }
        </div>
        @if (!disc.can.joined && disc.status === 'open') {
          <button type="button" class="btn btn-secondary" (click)="join()">
            {{ 'discussions.join' | transloco }}
          </button>
        }
      </header>

      @if (disc.status !== 'open' && disc.decision; as dec) {
        <section class="card" aria-labelledby="h-record">
          <h2 id="h-record">{{ 'discussions.record' | transloco }}</h2>
          <p>
            <span class="badge badge-neutral">{{
              'discussions.outcome_' + dec.outcome | transloco
            }}</span>
            {{ 'discussions.decided_by' | transloco: { who: dec.decider } }}
            · {{ dec.decided_at | date: 'medium' : undefined : prefs.locale() }}
            @if (dec.version) {
              · {{ 'discussions.produced' | transloco: { n: dec.version } }}
              @if (dec.resulting_status) {
                ({{ 'status.' + dec.resulting_status | transloco }})
              }
            }
          </p>
          @if (dec.rationale) {
            <p class="body-text">{{ dec.rationale }}</p>
          }
          @if (dec.responses.length > 0) {
            <h3>{{ 'discussions.responses' | transloco }}</h3>
            <ul>
              @for (r of dec.responses; track r.position_id) {
                <li>
                  <strong>{{ r.participant }}</strong>
                  ({{ 'discussions.stance_' + r.stance | transloco }}): {{ r.reason }}
                  <br />
                  <span class="badge badge-neutral">{{
                    (r.accepted ? 'discussions.accepted_yes' : 'discussions.accepted_no')
                      | transloco
                  }}</span>
                  {{ r.response }}
                </li>
              }
            </ul>
          }
        </section>
      }

      <!-- 2. proposal -->
      <section class="card" aria-labelledby="h-proposal">
        <h2 id="h-proposal">{{ 'discussions.proposal' | transloco }}</h2>
        @if (disc.proposal.stale; as stale) {
          <div class="notice notice-warning" role="status">
            <p>
              {{
                'discussions.stale'
                  | transloco: { base: stale.base_version, latest: stale.latest_version }
              }}
            </p>
            <ul>
              @for (c of stale.changes; track c.path) {
                <li>
                  <span class="badge badge-info">{{ 'impact.label_' + c.kind | transloco }}</span>
                  {{ c.text }}
                </li>
              }
            </ul>
          </div>
        }
        @if (disc.proposal.version === null) {
          <p class="hint">{{ 'discussions.no_proposal' | transloco }}</p>
        } @else if (disc.proposal.changes.length === 0) {
          <p class="hint">{{ 'discussions.no_changes' | transloco }}</p>
        } @else {
          <ul class="changes">
            @for (c of disc.proposal.changes; track c.path) {
              <li>
                <span class="badge badge-info">{{ 'impact.label_' + c.kind | transloco }}</span>
                {{ c.text }}
              </li>
            }
          </ul>
        }
        @if (disc.proposal.version !== null) {
          <p class="hint">
            {{ 'discussions.proposal_version' | transloco: { n: disc.proposal.version } }}
          </p>
        }
        @if (disc.can.edit_proposal) {
          <details [open]="editing()" (toggle)="onToggle($event)">
            <summary>{{ 'discussions.edit_proposal' | transloco }}</summary>
            <label class="field">
              <span class="label">{{ 'discussions.proposal_json' | transloco }}</span>
              <textarea
                class="input mono"
                rows="14"
                spellcheck="false"
                [ngModel]="proposalDraft()"
                (ngModelChange)="proposalDraft.set($event)"
              ></textarea>
              <span class="hint">{{ 'discussions.proposal_hint' | transloco }}</span>
            </label>
            @if (proposalError()) {
              <p class="notice notice-danger" role="alert">
                {{ 'discussions.proposal_error_' + proposalError() | transloco }}
              </p>
            }
            <button type="button" class="btn btn-primary btn-sm" (click)="saveProposal()">
              {{ 'discussions.save_proposal' | transloco }}
            </button>
          </details>
        }
        @if (detected().length > 0) {
          <div class="notice notice-warning" role="status">
            <p>{{ 'discussions.validator' | transloco }}</p>
            <ul>
              @for (i of detected(); track i) {
                <li>{{ i }}</li>
              }
            </ul>
          </div>
        }
      </section>

      <!-- 3. impact radius -->
      <section class="card" aria-labelledby="h-impact">
        <div class="row">
          <h2 id="h-impact">{{ 'discussions.impact' | transloco }}</h2>
          @if (disc.can.comment) {
            <button type="button" class="btn btn-secondary btn-sm" (click)="refreshImpact()">
              {{ 'discussions.refresh' | transloco }}
            </button>
          }
        </div>
        <p class="hint">{{ 'discussions.impact_hint' | transloco }}</p>
        @if (disc.impact.current; as cur) {
          <ul class="stats">
            <li>
              <span class="mono num">{{ cur.content.summary.dependents }}</span>
              {{ 'discussions.i_dependents' | transloco }}
            </li>
            <li>
              <span class="mono num">{{ cur.content.summary.reference_cases_changed }}</span>
              {{ 'discussions.i_cases' | transloco }}
            </li>
            <li>
              <span class="mono num">{{ cur.content.summary.consultations_changed }}</span>
              {{ 'discussions.i_consultations' | transloco }}
            </li>
            <li>
              <span class="mono num">{{ cur.content.summary.new_issues }}</span>
              {{ 'discussions.i_issues' | transloco }}
            </li>
            @if (cur.content.usage.consultations !== undefined) {
              <li>
                <span class="mono num">{{ cur.content.usage.consultations }}</span>
                {{ 'discussions.i_used' | transloco }}
              </li>
            }
          </ul>
          <p class="hint">
            {{ 'discussions.computed' | transloco }}
            {{ cur.computed_at | date: 'medium' : undefined : prefs.locale() }}
          </p>
          @if (cur.content.dependents.length > 0) {
            <h3>{{ 'discussions.dependents' | transloco }}</h3>
            <ul>
              @for (x of cur.content.dependents; track x.kind + x.slug + x.ref_kind) {
                <li>
                  <a class="mono" [routerLink]="['/catalog', routeOf[x.kind], x.slug]">{{
                    x.slug
                  }}</a>
                  <span class="hint">({{ x.ref_kind }})</span>
                </li>
              }
            </ul>
          }
          @for (c of cur.content.reference_cases; track c.id) {
            @if (c.differences.length > 0) {
              <h3>{{ 'discussions.case' | transloco: { title: c.title } }}</h3>
              <ul>
                @for (x of c.differences; track x.text) {
                  <li>
                    <span class="badge badge-info">{{
                      'impact.label_' + x.label | transloco
                    }}</span>
                    {{ x.text }}
                  </li>
                }
              </ul>
            }
          }
          @for (c of cur.content.recent_consultations; track c.consultation_id) {
            @if (c.differences.length > 0) {
              <h3>{{ 'discussions.consultation' | transloco: { title: c.title } }}</h3>
              <ul>
                @for (x of c.differences; track x.text) {
                  <li>
                    <span class="badge badge-info">{{
                      'impact.label_' + x.label | transloco
                    }}</span>
                    {{ x.text }}
                  </li>
                }
              </ul>
            }
          }
          @if (cur.content.new_issues.length > 0) {
            <h3>{{ 'discussions.new_issues' | transloco }}</h3>
            <ul>
              @for (i of cur.content.new_issues; track i) {
                <li>{{ i }}</li>
              }
            </ul>
          }
        }
        @if (disc.impact.refreshed) {
          <h3>{{ 'discussions.since_opening' | transloco }}</h3>
          @if (
            disc.impact.since_opening.new.length === 0 &&
            disc.impact.since_opening.gone.length === 0
          ) {
            <p class="hint">{{ 'discussions.nothing_changed' | transloco }}</p>
          }
          <ul>
            @for (t of disc.impact.since_opening.new; track t) {
              <li>
                <span class="badge badge-info">{{ 'impact.label_added' | transloco }}</span> {{ t }}
              </li>
            }
            @for (t of disc.impact.since_opening.gone; track t) {
              <li>
                <span class="badge badge-info">{{ 'impact.label_removed' | transloco }}</span>
                {{ t }}
              </li>
            }
          </ul>
        }
      </section>

      <!-- 4. mediator brief and requests -->
      <section class="card" aria-labelledby="h-mediator">
        <h2 id="h-mediator">{{ 'discussions.mediator' | transloco }}</h2>
        <p class="hint">{{ 'discussions.mediator_hint' | transloco }}</p>
        <app-problem-notice [problem]="mediatorProblem()" />
        @if (disc.brief; as brief) {
          <div class="brief">
            <p>
              <span class="badge badge-info">{{ 'discussions.ai' | transloco }}</span>
              {{ 'discussions.brief' | transloco }}
            </p>
            <ng-container *ngTemplateOutlet="mediatorBody; context: { $implicit: brief }" />
          </div>
        } @else {
          <p class="hint">{{ 'discussions.no_brief' | transloco }}</p>
        }
        @if (disc.can.comment) {
          <div class="row">
            @if (!disc.brief) {
              <button
                type="button"
                class="btn btn-secondary btn-sm"
                [disabled]="mediating()"
                (click)="mediate('brief')"
              >
                {{ 'discussions.write_brief' | transloco }}
              </button>
            }
            <button
              type="button"
              class="btn btn-secondary btn-sm"
              [disabled]="mediating()"
              (click)="mediate('challenge')"
            >
              {{ 'discussions.challenge' | transloco }}
            </button>
            @if (disc.can.decide) {
              <button
                type="button"
                class="btn btn-secondary btn-sm"
                [disabled]="mediating()"
                (click)="mediate('synthesis')"
              >
                {{ 'discussions.prepare' | transloco }}
              </button>
            }
          </div>
          <form class="row" (submit)="$event.preventDefault(); mediate('ask')">
            <label class="field grow">
              <span class="label">{{ 'discussions.ask' | transloco }}</span>
              <input
                class="input"
                name="question"
                maxlength="2000"
                [ngModel]="question()"
                (ngModelChange)="question.set($event)"
              />
            </label>
            <button
              type="submit"
              class="btn btn-secondary"
              [disabled]="mediating() || !question().trim()"
            >
              {{ 'discussions.ask_action' | transloco }}
            </button>
          </form>
          @if (mediating()) {
            <p role="status">
              <span class="spinner" aria-hidden="true"></span>
              {{ 'discussions.mediating' | transloco }}
            </p>
          }
        }
      </section>

      <!-- 5. thread -->
      <section class="card" aria-labelledby="h-thread">
        <h2 id="h-thread">{{ 'discussions.thread' | transloco }}</h2>
        <ol class="thread">
          @for (e of disc.thread; track e.id) {
            <li class="entry" [class.retracted]="e.retracted_at">
              <h3 class="entry-head">
                <span
                  class="badge"
                  [class]="'badge-' + (e.kind === 'mediator' ? 'info' : 'neutral')"
                  >{{ 'discussions.kind_' + e.kind | transloco }}</span
                >
                @if (e.ai) {
                  <span class="badge badge-info">{{ 'discussions.ai' | transloco }}</span>
                }
                @if (e.author) {
                  {{ e.author }}
                }
                <span class="hint">{{
                  e.created_at | date: 'medium' : undefined : prefs.locale()
                }}</span>
                @if (e.edited_at) {
                  <span class="hint">· {{ 'discussions.edited' | transloco }}</span>
                }
                @if (e.retracted_at) {
                  <span class="badge badge-warning">{{ 'discussions.retracted' | transloco }}</span>
                }
              </h3>
              @if (e.kind === 'mediator') {
                <ng-container *ngTemplateOutlet="mediatorBody; context: { $implicit: e }" />
              } @else if (editingId() === e.id) {
                <form (submit)="$event.preventDefault(); saveEdit(e)">
                  <label class="field">
                    <span class="label">{{ 'discussions.edit_comment' | transloco }}</span>
                    <textarea
                      class="input"
                      rows="3"
                      name="edit"
                      [ngModel]="editText()"
                      (ngModelChange)="editText.set($event)"
                    ></textarea>
                  </label>
                  <div class="row">
                    <button type="submit" class="btn btn-primary btn-sm">
                      {{ 'common.save' | transloco }}
                    </button>
                    <button
                      type="button"
                      class="btn btn-ghost btn-sm"
                      (click)="editingId.set(null)"
                    >
                      {{ 'common.cancel' | transloco }}
                    </button>
                  </div>
                </form>
              } @else {
                <p class="body-text">
                  @for (part of refs(e.body); track $index) {
                    @if (part.link) {
                      <a class="mono" [routerLink]="part.link">{{ part.text }}</a>
                    } @else {
                      {{ part.text }}
                    }
                  }
                </p>
                @if (
                  e.kind === 'comment' &&
                  e.author_id === me()?.id &&
                  !e.retracted_at &&
                  disc.can.comment
                ) {
                  <div class="row">
                    <button type="button" class="btn btn-ghost btn-sm" (click)="startEdit(e)">
                      {{ 'discussions.edit' | transloco }}
                    </button>
                    <button type="button" class="btn btn-ghost btn-sm" (click)="retract(e)">
                      {{ 'discussions.retract' | transloco }}
                    </button>
                  </div>
                }
              }
            </li>
          }
        </ol>

        @if (disc.can.comment) {
          <form class="form" (submit)="$event.preventDefault(); comment()">
            <label class="field">
              <span class="label">{{ 'discussions.add_comment' | transloco }}</span>
              <textarea
                class="input"
                rows="3"
                name="comment"
                maxlength="5000"
                [ngModel]="commentText()"
                (ngModelChange)="commentText.set($event)"
              ></textarea>
              <span class="hint">{{ 'discussions.comment_hint' | transloco }}</span>
            </label>
            <fieldset class="mentions">
              <legend>{{ 'discussions.mention' | transloco }}</legend>
              @for (m of members(); track m.id) {
                @if (m.id !== me()?.id) {
                  <label class="check">
                    <input
                      type="checkbox"
                      [checked]="mentions().includes(m.id)"
                      (change)="toggleMention(m.id)"
                    />
                    {{ m.name }}
                  </label>
                }
              }
            </fieldset>
            <button type="submit" class="btn btn-primary" [disabled]="!commentText().trim()">
              {{ 'discussions.post' | transloco }}
            </button>
          </form>
        }
      </section>

      <!-- 6. positions -->
      <section class="card" aria-labelledby="h-positions">
        <h2 id="h-positions">{{ 'discussions.positions' | transloco }}</h2>
        @if (disc.positions.length === 0) {
          <p class="hint">{{ 'discussions.no_positions' | transloco }}</p>
        } @else {
          <div class="table-wrap">
            <table class="data">
              <caption class="sr-only">
                {{
                  'discussions.positions' | transloco
                }}
              </caption>
              <thead>
                <tr>
                  <th scope="col">{{ 'discussions.col_who' | transloco }}</th>
                  <th scope="col">{{ 'discussions.col_stance' | transloco }}</th>
                  <th scope="col">{{ 'discussions.col_reason' | transloco }}</th>
                </tr>
              </thead>
              <tbody>
                @for (p of disc.positions; track p.id) {
                  <tr>
                    <th scope="row">{{ p.participant }}</th>
                    <td>
                      <span
                        class="badge"
                        [class]="p.stance === 'oppose' ? 'badge-danger' : 'badge-neutral'"
                        >{{ 'discussions.stance_' + p.stance | transloco }}</span
                      >
                      @if (p.revisions > 0) {
                        <span class="hint">{{
                          'discussions.revised' | transloco: { n: p.revisions }
                        }}</span>
                      }
                    </td>
                    <td>{{ p.reason }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
        @if (disc.can.comment) {
          <form class="form" (submit)="$event.preventDefault(); takePosition()">
            <label class="field">
              <span class="label">{{ 'discussions.your_position' | transloco }}</span>
              <select
                class="input"
                name="stance"
                [ngModel]="stance()"
                (ngModelChange)="stance.set($event)"
              >
                @for (s of stances; track s) {
                  <option [value]="s">{{ 'discussions.stance_' + s | transloco }}</option>
                }
              </select>
            </label>
            <label class="field">
              <span class="label">
                {{ 'discussions.reason' | transloco }}
                {{ (needsReason() ? 'common.required' : 'common.optional') | transloco }}
              </span>
              <input
                class="input"
                name="reason"
                [ngModel]="reason()"
                (ngModelChange)="reason.set($event)"
              />
            </label>
            <button
              type="submit"
              class="btn btn-secondary"
              [disabled]="needsReason() && !reason().trim()"
            >
              {{ 'discussions.take_position' | transloco }}
            </button>
          </form>
        }
      </section>

      <!-- 7. decide -->
      <section class="card" aria-labelledby="h-decide">
        <h2 id="h-decide">{{ 'discussions.decide' | transloco }}</h2>
        @if (disc.status !== 'open') {
          <p class="hint">{{ 'discussions.closed_note' | transloco }}</p>
        } @else {
          @if (!disc.can.decide) {
            <p class="notice notice-info" role="status">
              {{ 'discussions.only_decider' | transloco: { who: disc.decider.name } }}
            </p>
          }
          <fieldset class="form" [disabled]="!disc.can.decide">
            <legend class="sr-only">{{ 'discussions.decide' | transloco }}</legend>
            <label class="field">
              <span class="label">{{ 'discussions.outcome' | transloco }}</span>
              <select
                class="input"
                name="outcome"
                [ngModel]="outcome()"
                (ngModelChange)="outcome.set($event)"
              >
                @for (o of outcomes; track o) {
                  <option [value]="o">{{ 'discussions.outcome_' + o | transloco }}</option>
                }
              </select>
            </label>
            @if (accepting()) {
              <label class="field">
                <span class="label">{{ 'discussions.result_status' | transloco }}</span>
                <select
                  class="input"
                  name="rstatus"
                  [ngModel]="resultStatus()"
                  (ngModelChange)="resultStatus.set($event)"
                >
                  <option value="validated">{{ 'status.validated' | transloco }}</option>
                  <option value="proposed">{{ 'status.proposed' | transloco }}</option>
                </select>
              </label>
            }
            @if (outcome() !== 'withdrawn') {
              @if (synthesis(); as syn) {
                <div class="notice notice-info" role="status">
                  <p>
                    <span class="badge badge-info">{{ 'discussions.ai' | transloco }}</span>
                    {{ 'discussions.draft_available' | transloco }}
                  </p>
                  @if (syn.grounding?.draft_rationale) {
                    <button type="button" class="btn btn-secondary btn-sm" (click)="useDraft(syn)">
                      {{ 'discussions.use_draft' | transloco }}
                    </button>
                  }
                </div>
              }
              <label class="field">
                <span class="label">{{ 'discussions.rationale' | transloco }}</span>
                <textarea
                  class="input"
                  rows="4"
                  name="rationale"
                  maxlength="5000"
                  [ngModel]="rationale()"
                  (ngModelChange)="rationale.set($event)"
                ></textarea>
              </label>
              @for (p of opposed(); track p.id) {
                <fieldset class="response">
                  <legend>
                    {{ 'discussions.respond_to' | transloco: { who: p.participant } }}
                  </legend>
                  <p class="hint">“{{ p.reason }}”</p>
                  <label class="check">
                    <input
                      type="radio"
                      [name]="'acc' + p.id"
                      [checked]="draft(p.id).accepted === true"
                      (change)="setDraft(p.id, { accepted: true })"
                    />
                    {{ 'discussions.accepted_yes' | transloco }}
                  </label>
                  <label class="check">
                    <input
                      type="radio"
                      [name]="'acc' + p.id"
                      [checked]="draft(p.id).accepted === false"
                      (change)="setDraft(p.id, { accepted: false })"
                    />
                    {{ 'discussions.accepted_no' | transloco }}
                  </label>
                  <label class="field">
                    <span class="label">{{ 'discussions.response' | transloco }}</span>
                    <textarea
                      class="input"
                      rows="2"
                      [name]="'resp' + p.id"
                      [ngModel]="draft(p.id).response"
                      (ngModelChange)="setDraft(p.id, { response: $event })"
                    ></textarea>
                  </label>
                </fieldset>
              }
            }
            @if (disc.proposal.stale && accepting()) {
              <label class="check">
                <input
                  type="checkbox"
                  [checked]="ackStale()"
                  (change)="ackStale.set(!ackStale())"
                />
                {{ 'discussions.ack_stale' | transloco }}
              </label>
            }
            @if (decideProblem(); as dp) {
              <div class="notice notice-danger" role="alert">
                <p>{{ 'discussions.err_' + dp.key | transloco: { who: dp.who } }}</p>
              </div>
            }
            <app-problem-notice [problem]="problem2()" />
            <button type="button" class="btn btn-primary" (click)="askConfirm()">
              {{ 'discussions.decide_action' | transloco }}
            </button>
          </fieldset>
        }
      </section>

      <!-- transfer / reassign -->
      @if (disc.status === 'open' && (disc.can.transfer || auth.user()?.role === 'admin')) {
        <section class="card" aria-labelledby="h-transfer">
          <h2 id="h-transfer">
            {{ (disc.can.transfer ? 'discussions.transfer' : 'discussions.reassign') | transloco }}
          </h2>
          <p class="hint">
            {{
              (disc.can.transfer ? 'discussions.transfer_hint' : 'discussions.reassign_hint')
                | transloco
            }}
          </p>
          <form class="form" (submit)="$event.preventDefault(); hand()">
            <label class="field">
              <span class="label">{{ 'discussions.to' | transloco }}</span>
              <select
                class="input"
                name="to"
                [ngModel]="transferTo()"
                (ngModelChange)="transferTo.set($event)"
              >
                <option [ngValue]="null">—</option>
                @for (m of members(); track m.id) {
                  @if (m.id !== disc.decider.id) {
                    <option [ngValue]="m.id">{{ m.name }}</option>
                  }
                }
              </select>
            </label>
            <label class="field">
              <span class="label">{{ 'discussions.transfer_reason' | transloco }}</span>
              <input
                class="input"
                name="treason"
                maxlength="500"
                [ngModel]="transferReason()"
                (ngModelChange)="transferReason.set($event)"
              />
            </label>
            <button type="submit" class="btn btn-secondary" [disabled]="transferTo() === null">
              {{
                (disc.can.transfer ? 'discussions.transfer_action' : 'discussions.reassign_action')
                  | transloco
              }}
            </button>
          </form>
        </section>
      }

      @if (disc.position_history.length > disc.positions.length) {
        <details class="card">
          <summary>{{ 'discussions.history' | transloco }}</summary>
          <ul>
            @for (h of disc.position_history; track h.id) {
              <li>
                {{ h.participant }}: {{ 'discussions.stance_' + h.stance | transloco }}
                @if (h.reason) {
                  — {{ h.reason }}
                }
                @if (h.superseded_at) {
                  <span class="hint">({{ 'discussions.superseded' | transloco }})</span>
                }
              </li>
            }
          </ul>
        </details>
      }

      <dialog #confirm class="dialog" aria-labelledby="confirm-title" (close)="onDialogClosed()">
        <h2 id="confirm-title">{{ 'discussions.confirm_title' | transloco }}</h2>
        <p>{{ consequence() }}</p>
        <div class="row">
          <button type="button" class="btn btn-primary" [disabled]="busy()" (click)="decide()">
            {{ 'discussions.confirm_action' | transloco }}
          </button>
          <button type="button" class="btn btn-secondary" (click)="closeConfirm()">
            {{ 'common.cancel' | transloco }}
          </button>
        </div>
      </dialog>
    }

    <ng-template #mediatorBody let-e>
      @if (e.grounding?.sentences; as sentences) {
        <ul class="sentences">
          @for (s of sentences; track $index) {
            <li>
              <span class="badge badge-neutral">{{ 'discussions.sk_' + s.kind | transloco }}</span>
              {{ s.text }}
              @if (s.refs.length > 0) {
                <span class="hint">
                  {{ 'discussions.based_on' | transloco }}
                  @for (r of s.refs; track r; let last = $last) {
                    <span class="mono" [attr.title]="e.grounding.facts?.[r] ?? ''">{{ r }}</span
                    >{{ last ? '' : ', ' }}
                  }
                </span>
              }
            </li>
          }
        </ul>
        @if (e.grounding.suggested_change) {
          <p>
            <strong>{{ 'discussions.suggested_change' | transloco }}:</strong>
            {{ e.grounding.suggested_change }}
          </p>
        }
        @if (e.grounding.draft_rationale) {
          <p>
            <strong>{{ 'discussions.draft_rationale' | transloco }}:</strong>
            {{ e.grounding.draft_rationale }}
          </p>
        }
      } @else {
        <p class="body-text">{{ e.body }}</p>
        <p class="hint">{{ 'discussions.found_by_code' | transloco }}</p>
      }
    </ng-template>
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
    h2,
    h3,
    .meta,
    .head p {
      margin: 0;
    }
    section.card,
    details.card {
      margin-bottom: var(--space-4);
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
    }
    .row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: flex-end;
    }
    .grow {
      flex: 1;
      min-width: 12rem;
    }
    .form {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      align-items: flex-start;
      border: 0;
      padding: 0;
      margin: 0;
    }
    .form .field,
    textarea {
      width: 100%;
    }
    .stats {
      list-style: none;
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3) var(--space-6);
      padding: 0;
      margin: 0;
    }
    .num {
      font-size: 1.25rem;
      font-weight: 600;
    }
    .thread {
      list-style: none;
      padding: 0;
      margin: 0;
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    .entry {
      border-left: 3px solid var(--border);
      padding-left: var(--space-3);
    }
    .entry.retracted .body-text {
      text-decoration: line-through;
      color: var(--text-2);
    }
    .entry-head {
      font-size: 1rem;
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;
    }
    .body-text {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin: var(--space-1) 0;
    }
    .sentences {
      margin: 0;
      padding-left: var(--space-5);
    }
    .mentions,
    .response {
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: var(--space-2) var(--space-3);
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2) var(--space-4);
      width: 100%;
    }
    .response {
      flex-direction: column;
    }
    .check {
      display: inline-flex;
      gap: var(--space-2);
      align-items: center;
    }
    .dialog {
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--surface);
      color: var(--text);
      max-width: 32rem;
      margin: auto;
      padding: var(--space-5);
    }
    .dialog::backdrop {
      background: rgb(0 0 0 / 0.4);
    }
  `,
})
export class DiscussionPage implements OnInit {
  private readonly api = inject(Api);
  private readonly route = inject(ActivatedRoute);
  private readonly announcer = inject(Announcer);
  private readonly destroyRef = inject(DestroyRef);
  private readonly i18n = inject(TranslocoService);
  protected readonly auth = inject(Auth);
  protected readonly prefs = inject(UserPreferences);
  private readonly dialog = viewChild<ElementRef<HTMLDialogElement>>('confirm');

  protected readonly routeOf = ROUTE_OF_KIND;
  protected readonly stances = STANCES;
  protected readonly outcomes: Outcome[] = [
    'accepted',
    'accepted_modified',
    'rejected',
    'withdrawn',
  ];

  protected readonly d = signal<Discussion | null>(null);
  protected readonly members = signal<Member[]>([]);
  protected readonly loading = signal(true);
  protected readonly busy = signal(false);
  protected readonly problem = signal<ApiProblem | null>(null);
  protected readonly problem2 = signal<ApiProblem | null>(null);
  protected readonly mediatorProblem = signal<ApiProblem | null>(null);
  protected readonly mediating = signal(false);
  protected readonly detected = signal<string[]>([]);
  protected readonly me = computed(() => this.auth.user());

  // forms
  protected readonly commentText = signal('');
  protected readonly mentions = signal<number[]>([]);
  protected readonly editingId = signal<number | null>(null);
  protected readonly editText = signal('');
  protected readonly stance = signal<Stance>('support');
  protected readonly reason = signal('');
  protected readonly question = signal('');
  protected readonly editing = signal(false);
  protected readonly proposalDraft = signal('');
  protected readonly proposalError = signal('');
  protected readonly outcome = signal<Outcome>('accepted');
  protected readonly resultStatus = signal<'validated' | 'proposed'>('validated');
  protected readonly rationale = signal('');
  protected readonly drafts = signal<Record<number, ResponseDraft | undefined>>({});
  protected readonly ackStale = signal(false);
  protected readonly decideProblem = signal<{ key: string; who: string } | null>(null);
  protected readonly transferTo = signal<number | null>(null);
  protected readonly transferReason = signal('');

  protected readonly accepting = computed(
    () => this.outcome() === 'accepted' || this.outcome() === 'accepted_modified',
  );
  protected readonly needsReason = computed(() => stanceNeedsReason(this.stance()));
  protected readonly opposed = computed(() => opposing(this.d()?.positions ?? []));
  protected readonly synthesis = computed(() => latestSynthesis(this.d()?.thread ?? []));
  protected readonly consequence = computed(() =>
    this.i18n.translate(`discussions.consequence_${this.outcome()}`, {
      item: `${this.d()?.item.kind}:${this.d()?.item.slug}`,
      status: this.i18n.translate(`status.${this.resultStatus()}`),
    }),
  );

  private id = 0;
  private proposalSeeded = false;

  ngOnInit(): void {
    this.id = Number(this.route.snapshot.paramMap.get('id'));
    void this.load();
    void firstValueFrom(this.api.get<Member[]>('/discussions/members'))
      .then((m) => this.members.set(m))
      .catch(() => this.members.set([]));
    const timer = setInterval(() => {
      if (!document.hidden && !this.busy() && !this.mediating()) {
        void this.load(true);
      }
    }, POLL_MS);
    this.destroyRef.onDestroy(() => clearInterval(timer));
  }

  protected itemLink(disc: Discussion): string[] {
    return ['/catalog', ROUTE_OF_KIND[disc.item.kind], disc.item.slug];
  }

  protected refs(text: string): { text: string; link: string[] | null }[] {
    return catalogRefs(text);
  }

  protected async load(silent = false): Promise<void> {
    if (!silent) {
      this.loading.set(true);
    }
    try {
      const next = await firstValueFrom(this.api.get<Discussion>(`/discussions/${this.id}`));
      this.adopt(next, silent);
      if (!silent) {
        await firstValueFrom(this.api.post(`/discussions/${this.id}/seen`));
      }
      this.problem.set(null);
    } catch (error) {
      if (!silent) {
        this.problem.set(toProblem(error));
      }
    } finally {
      this.loading.set(false);
    }
  }

  /** A new view: announce what is new politely, never move focus, keep what is being typed. */
  private adopt(next: Discussion, silent: boolean): void {
    const added = silent ? newEntries(this.d(), next) : 0;
    this.d.set(next);
    if (added > 0) {
      this.announcer.say(`${added} new ${added === 1 ? 'entry' : 'entries'} in this discussion`);
    }
    if (!this.proposalSeeded || !this.editing()) {
      const proposed = next.proposal.item;
      const item = Object.keys(proposed).length > 0 ? proposed : next.proposal.base_item;
      this.proposalDraft.set(Object.keys(item).length > 0 ? proposalText(item) : '');
      this.proposalSeeded = true;
    }
    const pre = prefill(next.thread, next.positions);
    this.drafts.update((cur) => {
      const merged = { ...cur };
      for (const [id, draft] of Object.entries(pre)) {
        const existing = merged[Number(id)];
        if (!existing || (!existing.response && existing.accepted === null)) {
          merged[Number(id)] = draft;
        }
      }
      return merged;
    });
  }

  private async act(request: Promise<Discussion>): Promise<boolean> {
    this.busy.set(true);
    this.problem.set(null);
    try {
      this.adopt(await request, false);
      return true;
    } catch (error) {
      this.problem.set(toProblem(error));
      return false;
    } finally {
      this.busy.set(false);
    }
  }

  protected async join(): Promise<void> {
    await this.act(firstValueFrom(this.api.post<Discussion>(`/discussions/${this.id}/join`)));
  }

  // --- thread

  protected toggleMention(id: number): void {
    this.mentions.update((m) => (m.includes(id) ? m.filter((x) => x !== id) : [...m, id]));
  }

  protected async comment(): Promise<void> {
    const body = this.commentText().trim();
    const ok = await this.act(
      firstValueFrom(
        this.api.post<Discussion>(`/discussions/${this.id}/comments`, {
          body,
          mentions: this.mentions(),
        }),
      ),
    );
    if (ok) {
      this.commentText.set('');
      this.mentions.set([]);
      this.announcer.say('Comment posted');
    }
  }

  protected startEdit(e: Entry): void {
    this.editingId.set(e.id);
    this.editText.set(e.body);
  }

  protected async saveEdit(e: Entry): Promise<void> {
    const ok = await this.act(
      firstValueFrom(
        this.api.patch<Discussion>(`/discussions/${this.id}/comments/${e.id}`, {
          body: this.editText(),
        }),
      ),
    );
    if (ok) {
      this.editingId.set(null);
    }
  }

  protected async retract(e: Entry): Promise<void> {
    await this.act(
      firstValueFrom(this.api.post<Discussion>(`/discussions/${this.id}/comments/${e.id}/retract`)),
    );
  }

  // --- positions

  protected async takePosition(): Promise<void> {
    const ok = await this.act(
      firstValueFrom(
        this.api.put<Discussion>(`/discussions/${this.id}/position`, {
          stance: this.stance(),
          reason: this.reason().trim(),
        }),
      ),
    );
    if (ok) {
      this.reason.set('');
      this.announcer.say('Position saved');
    }
  }

  // --- proposal and impact

  protected onToggle(event: Event): void {
    this.editing.set((event.target as HTMLDetailsElement).open);
  }

  protected async saveProposal(): Promise<void> {
    const parsed = parseProposal(this.proposalDraft());
    if (!parsed.item) {
      this.proposalError.set(parsed.error);
      return;
    }
    this.proposalError.set('');
    this.busy.set(true);
    this.problem.set(null);
    try {
      const view = await firstValueFrom(
        this.api.put<Discussion>(`/discussions/${this.id}/proposal`, { item: parsed.item }),
      );
      this.editing.set(false);
      this.detected.set(view.issues ?? []);
      this.adopt(view, false);
      this.announcer.say('Proposal saved');
    } catch (error) {
      this.problem.set(toProblem(error));
    } finally {
      this.busy.set(false);
    }
  }

  protected async refreshImpact(): Promise<void> {
    const ok = await this.act(
      firstValueFrom(this.api.post<Discussion>(`/discussions/${this.id}/impact/refresh`)),
    );
    if (ok) {
      this.announcer.say('Impact refreshed');
    }
  }

  // --- mediator

  protected async mediate(mode: 'brief' | 'ask' | 'challenge' | 'synthesis'): Promise<void> {
    this.mediatorProblem.set(null);
    this.mediating.set(true);
    try {
      this.adopt(
        await firstValueFrom(
          this.api.post<Discussion>(`/discussions/${this.id}/mediator`, {
            mode,
            question: mode === 'ask' ? this.question() : '',
          }),
        ),
        false,
      );
      if (mode === 'ask') {
        this.question.set('');
      }
    } catch (error) {
      this.mediatorProblem.set(toProblem(error));
    } finally {
      this.mediating.set(false);
    }
  }

  // --- deciding

  protected draft(id: number): ResponseDraft {
    return this.drafts()[id] ?? { accepted: null, response: '' };
  }

  protected setDraft(id: number, patch: Partial<ResponseDraft>): void {
    this.drafts.update((all) => ({ ...all, [id]: { ...this.draft(id), ...patch } }));
  }

  protected useDraft(syn: Entry): void {
    this.rationale.set(syn.grounding?.draft_rationale ?? this.rationale());
  }

  protected askConfirm(): void {
    this.decideProblem.set(null);
    const disc = this.d();
    if (!disc) {
      return;
    }
    if (this.outcome() !== 'withdrawn') {
      if (!this.rationale().trim()) {
        this.decideProblem.set({ key: 'rationale', who: '' });
        return;
      }
      const missing = unanswered(disc.positions, this.drafts());
      if (missing.length > 0) {
        this.decideProblem.set({ key: 'responses', who: missing.join(', ') });
        return;
      }
    }
    this.dialog()?.nativeElement.showModal();
  }

  protected closeConfirm(): void {
    this.dialog()?.nativeElement.close();
  }

  protected onDialogClosed(): void {
    // focus returns to the element that opened the dialog (native behaviour)
  }

  protected async decide(): Promise<void> {
    const responses = this.opposed().map((p) => ({
      position_id: p.id,
      accepted: this.draft(p.id).accepted === true,
      response: this.draft(p.id).response.trim(),
    }));
    this.problem2.set(null);
    this.busy.set(true);
    try {
      const view = await firstValueFrom(
        this.api.post<Discussion>(`/discussions/${this.id}/decision`, {
          outcome: this.outcome(),
          status: this.resultStatus(),
          rationale: this.rationale().trim(),
          responses: this.outcome() === 'withdrawn' ? [] : responses,
          acknowledge_stale: this.ackStale(),
        }),
      );
      this.closeConfirm();
      this.adopt(view, false);
      this.announcer.say('Decision saved. The discussion is closed.');
    } catch (error) {
      this.closeConfirm();
      this.problem2.set(toProblem(error));
    } finally {
      this.busy.set(false);
    }
  }

  protected async hand(): Promise<void> {
    const disc = this.d();
    const to = this.transferTo();
    if (!disc || to === null) {
      return;
    }
    const path = disc.can.transfer ? 'transfer' : 'reassign';
    const ok = await this.act(
      firstValueFrom(
        this.api.post<Discussion>(`/discussions/${this.id}/${path}`, {
          to_user_id: to,
          reason: this.transferReason().trim(),
        }),
      ),
    );
    if (ok) {
      this.transferTo.set(null);
      this.transferReason.set('');
    }
  }
}
